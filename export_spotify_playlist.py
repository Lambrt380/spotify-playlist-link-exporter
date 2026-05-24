#!/usr/bin/env python3
"""Export Spotify track names and artists from copied track links.

The script reads Spotify track and local-file URLs from a text file, fetches
Spotify's public embed metadata for regular tracks, decodes local-file URLs, and
writes a CSV with the track title and artists. It does not need Spotify API
credentials.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen


TRACK_ID_RE = re.compile(r"(?:open\.spotify\.com/track/|spotify:track:)([A-Za-z0-9]{22})")
NEXT_DATA_RE = re.compile(
    r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125 Safari/537.36"
)
METADATA_FIELDS = [
    "track_name",
    "artists",
    "album",
    "release_date",
    "duration_ms",
    "explicit",
    "spotify_uri",
    "thumbnail_url",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract track names and artists from Spotify track links."
    )
    parser.add_argument(
        "-i",
        "--input",
        default="links.txt",
        help="Text file containing Spotify track links, one per line. Default: links.txt",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="spotify_track_links.csv",
        help="CSV file to write. Default: spotify_track_links.csv",
    )
    parser.add_argument(
        "--simple-output",
        default="spotify_tracks_simple.txt",
        help=(
            "Plain text list to write as '1, Song - Artist'. "
            "Default: spotify_tracks_simple.txt"
        ),
    )
    parser.add_argument(
        "--cache",
        default="spotify_track_cache.json",
        help="Metadata cache file for faster reruns. Default: spotify_track_cache.json",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.10,
        help="Seconds to wait between uncached Spotify requests. Default: 0.10",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Network timeout in seconds. Default: 20",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Retries for temporary network errors. Default: 2",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N non-empty input lines. Useful for testing.",
    )
    return parser.parse_args()


def extract_track_id(line: str) -> str | None:
    match = TRACK_ID_RE.search(line)
    if match:
        return match.group(1)

    parsed = urlparse(line.strip())
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "track" and re.fullmatch(r"[A-Za-z0-9]{22}", parts[1]):
        return parts[1]

    return None


def clean_local_text(value: str) -> str:
    cleaned = unquote(value).replace("+", " ").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\.(mp3|m4a|flac|wav|ogg)$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def split_artist_from_title(title: str) -> tuple[str, str]:
    for separator in (" - ", " \u2014 ", " \u2013 "):
        if separator in title:
            artist, track_name = title.split(separator, 1)
            artist = artist.strip()
            track_name = track_name.strip()
            if artist and track_name:
                return artist, track_name

    return "", title


def parse_local_link(link: str) -> dict[str, Any] | None:
    parsed = urlparse(link.strip())
    parts = parsed.path.split("/")

    if parsed.netloc not in {"open.spotify.com", "www.open.spotify.com"}:
        return None
    if len(parts) < 2 or parts[1] != "local":
        return None

    local_parts = [clean_local_text(part) for part in parts[2:]]
    duration_ms: int | str = ""
    if local_parts and local_parts[-1].isdigit():
        duration_ms = int(local_parts.pop()) * 1000

    artist = local_parts[0] if len(local_parts) >= 1 else ""
    album = local_parts[1] if len(local_parts) >= 2 else ""
    track_name = local_parts[2] if len(local_parts) >= 3 else ""

    if not track_name and local_parts:
        track_name = local_parts[-1]

    if not artist and track_name:
        artist, track_name = split_artist_from_title(track_name)

    return {
        "track_id": "",
        "url": link,
        "track_name": track_name,
        "artists": artist,
        "album": album,
        "release_date": "",
        "duration_ms": duration_ms,
        "explicit": "",
        "spotify_uri": "",
        "thumbnail_url": "",
        "status": "ok" if track_name else "skipped",
        "error": "" if track_name else "Could not parse local Spotify link",
    }


def read_links(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        link = raw_line.strip()
        if not link:
            continue

        local_metadata = parse_local_link(link)
        if local_metadata:
            rows.append({"line_number": line_number, **local_metadata})
            continue

        track_id = extract_track_id(link)
        if not track_id:
            rows.append(
                {
                    "line_number": line_number,
                    "track_id": "",
                    "url": link,
                    "status": "skipped",
                    "error": "No Spotify track ID found",
                }
            )
            continue

        rows.append(
            {
                "line_number": line_number,
                "track_id": track_id,
                "url": f"https://open.spotify.com/track/{track_id}",
                "status": "pending",
                "error": "",
            }
        )

    return rows


def load_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"Warning: ignoring broken cache file: {path}", file=sys.stderr)
        return {}

    if not isinstance(data, dict):
        return {}

    return {str(key): value for key, value in data.items() if isinstance(value, dict)}


def save_cache(path: Path, cache: dict[str, dict[str, Any]]) -> None:
    path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def fetch_url(url: str, timeout: float) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def find_entity(next_data: dict[str, Any]) -> dict[str, Any]:
    props = next_data.get("props", {})
    page_props = props.get("pageProps", {})
    state = page_props.get("state", {})
    data = state.get("data", {})
    entity = data.get("entity", {})
    if not isinstance(entity, dict):
        return {}
    return entity


def parse_track_page(page_html: str) -> dict[str, Any]:
    match = NEXT_DATA_RE.search(page_html)
    if not match:
        raise ValueError("Could not find __NEXT_DATA__ metadata in Spotify page")

    next_data = json.loads(html.unescape(match.group(1)))
    entity = find_entity(next_data)
    if not entity:
        raise ValueError("Could not find track entity metadata in Spotify page")

    artists = entity.get("artists") or []
    artist_names = [
        str(artist.get("name", "")).strip()
        for artist in artists
        if isinstance(artist, dict) and str(artist.get("name", "")).strip()
    ]

    images = entity.get("visualIdentity", {}).get("image", [])
    thumbnail_url = ""
    if isinstance(images, list) and images:
        first_image = images[0]
        if isinstance(first_image, dict):
            thumbnail_url = str(first_image.get("url", ""))

    return {
        "track_name": str(entity.get("title") or entity.get("name") or "").strip(),
        "artists": ", ".join(artist_names),
        "album": "",
        "release_date": (entity.get("releaseDate") or {}).get("isoString", ""),
        "duration_ms": entity.get("duration", ""),
        "explicit": entity.get("isExplicit", ""),
        "spotify_uri": entity.get("uri", ""),
        "thumbnail_url": thumbnail_url,
    }


def fetch_track_metadata(track_id: str, timeout: float, retries: int) -> dict[str, Any]:
    url = f"https://open.spotify.com/embed/track/{quote(track_id)}"
    last_error: Exception | None = None

    for attempt in range(retries + 1):
        try:
            return parse_track_page(fetch_url(url, timeout))
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
            last_error = error
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))

    raise RuntimeError(str(last_error) if last_error else "Unknown error")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "playlist_position",
        "track_name",
        "artists",
        "album",
        "url",
        "track_id",
        "release_date",
        "duration_ms",
        "explicit",
        "spotify_uri",
        "thumbnail_url",
        "status",
        "error",
    ]

    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in fieldnames} for row in rows)


def write_simple_list(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as text_file:
        for row in rows:
            position = str(row.get("playlist_position", "")).strip()
            track_name = str(row.get("track_name", "")).strip()
            artists = str(row.get("artists", "")).strip()

            if not position or not track_name:
                continue

            line = f"{position}, {track_name}"
            if artists:
                line += f" - {artists}"
            text_file.write(line + "\n")


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    simple_output_path = Path(args.simple_output)
    cache_path = Path(args.cache)

    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 1

    input_rows = read_links(input_path)
    if args.limit is not None:
        input_rows = input_rows[: args.limit]

    cache = load_cache(cache_path)
    output_rows: list[dict[str, Any]] = []

    track_rows = [row for row in input_rows if row["status"] == "pending"]
    local_rows = [row for row in input_rows if row["status"] == "ok" and not row["track_id"]]
    unique_track_ids = list(dict.fromkeys(row["track_id"] for row in track_rows))
    total_unique = len(unique_track_ids)
    fetched_count = 0

    print(
        f"Found {len(track_rows)} Spotify track links ({total_unique} unique) "
        f"and {len(local_rows)} local file links."
    )

    for index, track_id in enumerate(unique_track_ids, start=1):
        if track_id in cache and cache[track_id].get("status") == "ok":
            continue

        print(f"[{index}/{total_unique}] Fetching {track_id}...")
        try:
            cache[track_id] = {
                **fetch_track_metadata(track_id, timeout=args.timeout, retries=args.retries),
                "status": "ok",
                "error": "",
            }
            fetched_count += 1
        except RuntimeError as error:
            cache[track_id] = {
                "track_name": "",
                "artists": "",
                "album": "",
                "release_date": "",
                "duration_ms": "",
                "explicit": "",
                "spotify_uri": "",
                "thumbnail_url": "",
                "status": "error",
                "error": str(error),
            }

        if fetched_count and fetched_count % 25 == 0:
            save_cache(cache_path, cache)

        if args.delay > 0:
            time.sleep(args.delay)

    for position, row in enumerate(input_rows, start=1):
        track_id = row.get("track_id", "")
        metadata = cache.get(track_id, {}) if track_id else row
        output_rows.append(
            {
                "playlist_position": position,
                **{field: metadata.get(field, "") for field in METADATA_FIELDS},
                "url": row.get("url", ""),
                "track_id": track_id,
                "status": row.get("status") if row.get("status") != "pending" else metadata.get("status", ""),
                "error": row.get("error") or metadata.get("error", ""),
            }
        )

    write_csv(output_path, output_rows)
    write_simple_list(simple_output_path, output_rows)
    save_cache(cache_path, cache)

    ok_count = sum(1 for row in output_rows if row["status"] == "ok")
    error_count = sum(1 for row in output_rows if row["status"] != "ok")
    print(f"Done. Wrote {len(output_rows)} rows to {output_path}.")
    print(f"Wrote simple list to {simple_output_path}.")
    print(f"Successful rows: {ok_count}. Rows with errors/skips: {error_count}.")

    return 0 if ok_count else 1


if __name__ == "__main__":
    raise SystemExit(main())

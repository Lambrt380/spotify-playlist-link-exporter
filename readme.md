# Spotify Playlist Link Exporter

Export song titles and artists from Spotify playlist links copied into a text
file.

The script reads Spotify track URLs from `links.txt`, fetches public Spotify
embed metadata for regular tracks, decodes Spotify local-file URLs, and writes
both a full CSV export and a clean text list.

## Features

- No Spotify API key required
- No Python dependencies outside the standard library
- Preserves playlist order
- Handles normal Spotify track links
- Handles `open.spotify.com/local/...` links when possible
- Caches fetched metadata for faster reruns
- Writes a simple `1, Song - Artist` list automatically

## Requirements

- Python 3.10+
- Internet access for fetching regular Spotify track metadata

## Quick Start

Clone or download this project, then put your copied Spotify links in
`links.txt`.

```bash
python3 export_spotify_playlist.py
```

On Windows, depending on your Python installation:

```bash
python export_spotify_playlist.py
```

After the script finishes, it creates:

- `spotify_track_links.csv` - full export with metadata
- `spotify_tracks_simple.txt` - clean list in `position, title - artists` format
- `spotify_track_cache.json` - local metadata cache

## Example

The `example/` folder contains a full sample run:

- `example/links.txt` - copied Spotify playlist links
- `example/spotify_track_links.csv` - full CSV output
- `example/spotify_tracks_simple.txt` - simplified text output

Use it as a reference for the input and output formats.

## Copying Playlist Links

1. Open a Spotify playlist.
2. Click inside the track list.
3. Press `Ctrl+A`.
4. Press `Ctrl+C`.
5. Paste the copied links into `links.txt`.
6. Run the exporter.

The input file should contain one Spotify URL per line:

```text
https://open.spotify.com/track/7JEzAlwHhCD2M1cYE6BeqJ
https://open.spotify.com/track/6ie0uyyvOKTTuIFBMPiNIl
https://open.spotify.com/local/Kanye%20West//New%20Body/222
```

## Output

The simple output looks like this:

```text
1, Loving Machine - TV Girl
2, Judge Judy - Tyler, The Creator
3, Taking What's Not Yours - TV Girl
```

The CSV output includes additional fields such as:

- playlist position
- track name
- artists
- album, when available from local-file links
- Spotify URL
- Spotify track ID
- release date
- duration
- explicit flag
- thumbnail URL
- status and error fields

## Usage

Use a custom input file:

```bash
python3 export_spotify_playlist.py -i my_links.txt
```

Use a custom CSV output file:

```bash
python3 export_spotify_playlist.py -o my_tracks.csv
```

Use a custom simple-list output file:

```bash
python3 export_spotify_playlist.py --simple-output my_tracks.txt
```

Test only the first 10 links:

```bash
python3 export_spotify_playlist.py --limit 10
```

Disable the request delay:

```bash
python3 export_spotify_playlist.py --delay 0
```

Use a custom cache file:

```bash
python3 export_spotify_playlist.py --cache my_cache.json
```

## Cache

Fetched Spotify metadata is saved in `spotify_track_cache.json`. Keep this file
if you want future runs to finish faster.

Delete the cache file if you want to force the script to fetch fresh metadata.

## Notes

Spotify local-file links do not have public Spotify track IDs. For those rows,
the script decodes whatever title, artist, album, and duration data is available
inside the copied local URL.

If a run fails because of a temporary network issue, run the same command again.
Tracks already stored in the cache will be skipped.

# Image and Video Duplicate Finder

This repository contains Python CLIs that scan directories for duplicate and near-duplicate images or videos.

## Setup

Python 3.11 or newer is required.

```bash
python3 -m pip install -r requirements.txt
```

PyAV supplies the bundled FFmpeg libraries used to decode videos, so a separate FFmpeg installation is not required when a binary wheel is available.

## Find Duplicate Images

```bash
python3 find_duplicates.py /path/to/images
```

Optional threshold tuning:

```bash
python3 find_duplicates.py /path/to/images --threshold 6
```

Recursive scan:

```bash
python3 find_duplicates.py /path/to/images --recursive
```

Behavior:

- Compares top-level image files in the target directory.
- Optionally scans subdirectories with `--recursive`.
- Treats images with a perceptual hash distance at or below the threshold as duplicates.
- Moves the smaller file from each duplicate match into `duplicates/`.
- Prints the total size of moved duplicate files.

## Find Duplicate Videos

```bash
python3 find_video_duplicates.py /path/to/videos
```

Optional threshold tuning:

```bash
python3 find_video_duplicates.py /path/to/videos --threshold 6
```

Recursive scan:

```bash
python3 find_video_duplicates.py /path/to/videos --recursive
```

Behavior:

- Compares top-level video files in the target directory.
- Optionally scans subdirectories with `--recursive`.
- Supports common formats including MP4, MOV, MKV, WebM, AVI, WMV, FLV, MPEG, transport streams, 3GP, Ogg video, and VOB.
- Samples frames throughout each video to identify the same footage across containers, codecs, resolutions, and moderate re-encoding changes.
- Ignores audio tracks and metadata when deciding whether videos are duplicates.
- Does not treat trimmed, reordered, rotated, cropped, or otherwise edited footage as the same complete video.
- Moves the smaller file from each duplicate match into `duplicates/` and keeps the larger file.
- Uses the lexicographically earlier path as the deterministic keeper when file sizes are equal.
- Skips unreadable videos with a warning and continues scanning.
- Falls back to sequential decoding when a valid video does not permit random seeking.
- Caches video fingerprints in `.video_hash_cache.json` to speed up later scans.
- Prints the total size of moved duplicate files.

## Tests

```bash
mise run test
```

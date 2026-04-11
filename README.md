# Image Duplicate Finder

This repository contains a Python CLI that scans a directory for duplicate and near-duplicate images.

## Setup

```bash
python3 -m pip install -r requirements.txt
```

## Usage

```bash
python3 find_duplicates.py /path/to/images
```

Optional threshold tuning:

```bash
python3 find_duplicates.py /path/to/images --threshold 6
```

Behavior:

- Compares top-level image files in the target directory.
- Treats images with a perceptual hash distance at or below the threshold as duplicates.
- Moves the smaller file from each duplicate match into `duplicates/`.
- Prints the total size of moved duplicate files.

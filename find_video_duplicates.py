#!/usr/bin/env python3

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from duplicate_utils import (
    choose_duplicate,
    format_bytes,
    is_out_of_space,
    unique_destination,
)
from video_utils import VideoInfo, collect_videos, videos_are_duplicates


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find duplicate and near-duplicate videos in a directory."
    )
    parser.add_argument("directory", help="Directory containing videos to compare")
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recursively scan subdirectories for videos",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=6,
        help="Maximum per-frame perceptual hash distance (default: 6)",
    )
    return parser.parse_args()


def move_video_duplicates(
    videos: list[VideoInfo], directory: Path, threshold: int
) -> tuple[int, int]:
    duplicates_dir = directory / "duplicates"
    moved_paths: set[Path] = set()
    moved_count = 0
    moved_bytes = 0

    if videos:
        print(f"Comparing {len(videos)} video(s) for duplicates...")

    for index, video in enumerate(videos):
        if video.path in moved_paths:
            continue

        for candidate in videos[index + 1 :]:
            if candidate.path in moved_paths:
                continue
            if not videos_are_duplicates(video, candidate, threshold):
                continue

            duplicate, original = choose_duplicate(video, candidate)
            if duplicate.path in moved_paths:
                continue

            duplicates_dir.mkdir(exist_ok=True)
            destination = unique_destination(duplicates_dir, duplicate.path.name)
            shutil.move(str(duplicate.path), str(destination))
            moved_paths.add(duplicate.path)
            moved_count += 1
            moved_bytes += duplicate.size_bytes
            print(
                f"Moved duplicate {duplicate.path.name} "
                f"({format_bytes(duplicate.size_bytes)}) -> duplicates/; "
                f"kept {original.path.name} ({format_bytes(original.size_bytes)})"
            )

            if duplicate.path == video.path:
                break

    return moved_count, moved_bytes


def main() -> int:
    args = parse_args()
    directory = Path(args.directory).expanduser().resolve()

    if not directory.exists():
        print(f"Directory does not exist: {directory}", file=sys.stderr)
        return 1
    if not directory.is_dir():
        print(f"Path is not a directory: {directory}", file=sys.stderr)
        return 1
    if args.threshold < 0:
        print("Threshold must be zero or greater.", file=sys.stderr)
        return 1

    videos = collect_videos(directory, recursive=args.recursive)
    try:
        moved_count, moved_bytes = move_video_duplicates(videos, directory, args.threshold)
    except OSError as error:
        if not is_out_of_space(error):
            raise
        location = f" while writing {error.filename}" if error.filename else ""
        print(
            f"No space left on device{location}. "
            "Free up space and run again; "
            "files already moved remain in duplicates/.",
            file=sys.stderr,
        )
        return 1
    print(f"Scanned {len(videos)} video(s).")
    print(f"Moved {moved_count} duplicate video(s).")
    print(f"Total duplicate size: {moved_bytes} bytes ({format_bytes(moved_bytes)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

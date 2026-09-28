#!/usr/bin/env python3

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from duplicate_utils import format_bytes, is_out_of_space, unique_destination
from image_utils import (
    ImageInfo,
    collect_images,
    images_are_duplicates,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Copy images from source to destination if a duplicate exists in destination. "
            "The larger copy is kept in destination; the smaller is moved to "
            "a 'duplicates' folder in the source image's parent directory."
        )
    )
    parser.add_argument("source", help="Source directory containing images to evaluate")
    parser.add_argument("destination", help="Destination directory to copy images into")
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recursively scan subdirectories for images",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=6,
        help="Maximum perceptual hash distance for duplicates (default: 6)",
    )
    return parser.parse_args()


def copy_file(source: Path, destination: Path) -> None:
    try:
        shutil.copy2(str(source), str(destination))
    except OSError:
        destination.unlink(missing_ok=True)
        raise


def copy_duplicates(
    source_images: list[ImageInfo],
    dest_images: list[ImageInfo],
    threshold: int,
    dest_dir: Path,
) -> tuple[int, int, int]:
    """
    For each source image that has a duplicate in dest:
    - If source is larger: copy source to dest (collision-safe), move the smaller dest
      image to a 'duplicates' folder in the dest image's parent directory.
    - If dest is larger or equal: move source image to a 'duplicates' folder in the
      source image's parent directory.
    - If no duplicate exists in dest: copy source image directly to dest_dir.

    Returns (copied_count, moved_count, saved_bytes).
    saved_bytes is the total size of images moved to duplicates.
    """
    processed_source: set[Path] = set()
    processed_dest: set[Path] = set()
    copied_count = 0
    moved_count = 0
    saved_bytes = 0

    for src in source_images:
        if src.path in processed_source:
            continue

        for dst in dest_images:
            if dst.path in processed_dest:
                continue

            if not images_are_duplicates(src, dst, threshold):
                continue

            if src.size_bytes > dst.size_bytes:
                # Source is the better copy — copy it to dest, move smaller dest to duplicates
                dest_duplicates_dir = dst.path.parent / "duplicates"
                dest_duplicates_dir.mkdir(exist_ok=True)
                dest_dupe_dest = unique_destination(dest_duplicates_dir, dst.path.name)
                shutil.move(str(dst.path), str(dest_dupe_dest))
                processed_dest.add(dst.path)

                copy_dest = unique_destination(dst.path.parent, src.path.name)
                try:
                    copy_file(src.path, copy_dest)
                except OSError:
                    # Restore the destination copy so a failed replacement loses nothing
                    shutil.move(str(dest_dupe_dest), str(dst.path))
                    raise
                copied_count += 1
                moved_count += 1
                saved_bytes += dst.size_bytes
                print(
                    f"Copied {src.path.name} ({format_bytes(src.size_bytes)}) "
                    f"-> {copy_dest}; "
                    f"moved smaller duplicate {dst.path.name} "
                    f"({format_bytes(dst.size_bytes)}) -> {dest_dupe_dest}"
                )
            else:
                # Dest is the better copy (or equal) — move source to its duplicates folder
                src_duplicates_dir = src.path.parent / "duplicates"
                src_duplicates_dir.mkdir(exist_ok=True)
                src_dupe_dest = unique_destination(src_duplicates_dir, src.path.name)
                shutil.move(str(src.path), str(src_dupe_dest))
                processed_source.add(src.path)
                moved_count += 1
                saved_bytes += src.size_bytes
                print(
                    f"Moved {src.path.name} ({format_bytes(src.size_bytes)}) "
                    f"-> {src_dupe_dest}; "
                    f"kept larger duplicate {dst.path.name} "
                    f"({format_bytes(dst.size_bytes)}) in destination"
                )
                break

            processed_source.add(src.path)
            break
        else:
            # No duplicate found in dest — copy source as-is
            copy_dest = unique_destination(dest_dir, src.path.name)
            copy_file(src.path, copy_dest)
            copied_count += 1
            print(f"Copied {src.path.name} ({format_bytes(src.size_bytes)}) -> {copy_dest}")

    return copied_count, moved_count, saved_bytes


def main() -> int:
    args = parse_args()
    source = Path(args.source).expanduser().resolve()
    destination = Path(args.destination).expanduser().resolve()

    for label, path in [("Source", source), ("Destination", destination)]:
        if not path.exists():
            print(f"{label} directory does not exist: {path}", file=sys.stderr)
            return 1
        if not path.is_dir():
            print(f"{label} path is not a directory: {path}", file=sys.stderr)
            return 1

    if args.threshold < 0:
        print("Threshold must be zero or greater.", file=sys.stderr)
        return 1

    print("Scanning source...")
    source_images = collect_images(source, recursive=args.recursive)
    print("Scanning destination...")
    dest_images = collect_images(destination, recursive=args.recursive)

    print(
        f"Comparing {len(source_images)} source image(s) against "
        f"{len(dest_images)} destination image(s)..."
    )
    try:
        copied_count, moved_count, saved_bytes = copy_duplicates(
            source_images, dest_images, args.threshold, destination
        )
    except OSError as error:
        if not is_out_of_space(error):
            raise
        location = f" while writing {error.filename}" if error.filename else ""
        print(
            f"No space left on device{location}. "
            "Free up space and run again; "
            "files already copied or moved remain in place.",
            file=sys.stderr,
        )
        return 1

    print(f"Copied {copied_count} image(s) to destination.")
    print(f"Moved {moved_count} duplicate(s) to 'duplicates' folder.")
    print(f"Total duplicate size: {format_bytes(saved_bytes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

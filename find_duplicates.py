#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    from PIL import Image, ImageOps, UnidentifiedImageError
except ImportError:
    print(
        "Pillow is required. Install it with: python3 -m pip install -r requirements.txt",
        file=sys.stderr,
    )
    sys.exit(1)


SUPPORTED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp",
}
VISUAL_COMPARE_SIZE = 32
MAX_VISUAL_DIFFERENCE = 18.0


@dataclass(frozen=True)
class ImageInfo:
    path: Path
    size_bytes: int
    perceptual_hash: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find duplicate and near-duplicate images in a directory."
    )
    parser.add_argument("directory", help="Directory containing images to compare")
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


def average_hash(path: Path, hash_size: int = 8) -> int:
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image)
        image = image.convert("L").resize((hash_size, hash_size), Image.Resampling.LANCZOS)
        pixels = list(image.getdata())

    average = sum(pixels) / len(pixels)
    value = 0
    for pixel in pixels:
        value <<= 1
        if pixel >= average:
            value |= 1
    return value


def hamming_distance(left: int, right: int) -> int:
    return bin(left ^ right).count("1")


def visual_difference(
    left_path: Path, right_path: Path, compare_size: int = VISUAL_COMPARE_SIZE
) -> float:
    with Image.open(left_path) as left_image, Image.open(right_path) as right_image:
        left_image = ImageOps.exif_transpose(left_image).convert("RGB")
        right_image = ImageOps.exif_transpose(right_image).convert("RGB")
        left_image = left_image.resize(
            (compare_size, compare_size), Image.Resampling.LANCZOS
        )
        right_image = right_image.resize(
            (compare_size, compare_size), Image.Resampling.LANCZOS
        )
        left_pixels = list(left_image.getdata())
        right_pixels = list(right_image.getdata())

    total_difference = 0
    for left_pixel, right_pixel in zip(left_pixels, right_pixels):
        total_difference += sum(
            abs(left_channel - right_channel)
            for left_channel, right_channel in zip(left_pixel, right_pixel)
        )

    return total_difference / (len(left_pixels) * 3)


def images_are_duplicates(first: ImageInfo, second: ImageInfo, threshold: int) -> bool:
    hash_distance = hamming_distance(first.perceptual_hash, second.perceptual_hash)
    if hash_distance > threshold:
        return False

    return visual_difference(first.path, second.path) <= MAX_VISUAL_DIFFERENCE


def iter_image_paths(directory: Path, recursive: bool = False) -> Iterable[Path]:
    iterator = directory.rglob("*") if recursive else directory.iterdir()

    for path in sorted(iterator):
        relative = path.relative_to(directory)
        if "duplicates" in relative.parts[:-1]:
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield path


def build_image_info(path: Path) -> ImageInfo:
    return ImageInfo(
        path=path,
        size_bytes=path.stat().st_size,
        perceptual_hash=average_hash(path),
    )


def collect_images(directory: Path, recursive: bool = False) -> list[ImageInfo]:
    image_paths = list(iter_image_paths(directory, recursive=recursive))
    images: list[ImageInfo] = []
    total = len(image_paths)

    if total:
        print(f"Hashing {total} image(s)...")

    if not total:
        return images

    max_workers = min(32, max(1, (os.cpu_count() or 1) + 4), total)
    completed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_path = {executor.submit(build_image_info, path): path for path in image_paths}
        for future in as_completed(future_to_path):
            path = future_to_path[future]
            try:
                images.append(future.result())
            except (OSError, UnidentifiedImageError) as exc:
                print(f"Skipping unreadable image {path.name}: {exc}", file=sys.stderr)

            completed += 1
            print(f"\r[hash {completed}/{total}]", end="", flush=True)

    print()
    images.sort(key=lambda image: image.path)
    return images


def choose_duplicate(first: ImageInfo, second: ImageInfo) -> tuple[ImageInfo, ImageInfo]:
    if first.size_bytes < second.size_bytes:
        return first, second
    if second.size_bytes < first.size_bytes:
        return second, first
    if str(first.path) < str(second.path):
        return second, first
    return first, second


def unique_destination(destination_dir: Path, original_name: str) -> Path:
    candidate = destination_dir / original_name
    if not candidate.exists():
        return candidate

    stem = Path(original_name).stem
    suffix = Path(original_name).suffix
    index = 1
    while True:
        candidate = destination_dir / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def move_duplicates(
    images: list[ImageInfo], directory: Path, threshold: int
) -> tuple[int, int]:
    duplicates_dir = directory / "duplicates"
    moved_paths: set[Path] = set()
    moved_count = 0
    moved_bytes = 0
    total_images = len(images)

    if total_images:
        print(f"Comparing {total_images} image(s) for duplicates...")

    for index, image in enumerate(images):
        if image.path in moved_paths:
            continue

        for candidate in images[index + 1 :]:
            if candidate.path in moved_paths:
                continue

            if not images_are_duplicates(image, candidate, threshold):
                continue

            duplicate, original = choose_duplicate(image, candidate)
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

            if duplicate.path == image.path:
                break

    return moved_count, moved_bytes


def format_bytes(size_bytes: int) -> str:
    if size_bytes == 0:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size_bytes)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024

    return f"{size_bytes} B"


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

    images = collect_images(directory, recursive=args.recursive)
    moved_count, moved_bytes = move_duplicates(images, directory, args.threshold)
    print(f"Scanned {len(images)} image(s).")
    print(f"Moved {moved_count} duplicate image(s).")
    print(f"Total duplicate size: {moved_bytes} bytes ({format_bytes(moved_bytes)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

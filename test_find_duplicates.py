import shutil
from pathlib import Path

import pytest
from PIL import Image

from find_duplicates import (
    ImageInfo,
    average_hash,
    choose_duplicate,
    format_bytes,
    hamming_distance,
    iter_image_paths,
    move_duplicates,
    unique_destination,
)


# --- hamming_distance ---

def test_hamming_distance_identical():
    assert hamming_distance(0b1010, 0b1010) == 0


def test_hamming_distance_one_bit():
    assert hamming_distance(0b1010, 0b1011) == 1


def test_hamming_distance_all_bits():
    assert hamming_distance(0xFF, 0x00) == 8


def test_hamming_distance_symmetric():
    assert hamming_distance(0b1100, 0b0011) == hamming_distance(0b0011, 0b1100)


# --- format_bytes ---

def test_format_bytes_zero():
    assert format_bytes(0) == "0 B"


def test_format_bytes_bytes():
    assert format_bytes(512) == "512 B"


def test_format_bytes_kilobytes():
    assert format_bytes(1024) == "1.00 KB"


def test_format_bytes_megabytes():
    assert format_bytes(1024 * 1024) == "1.00 MB"


def test_format_bytes_gigabytes():
    assert format_bytes(1024 ** 3) == "1.00 GB"


def test_format_bytes_fractional():
    assert format_bytes(1536) == "1.50 KB"


# --- choose_duplicate ---

def _make_info(path_str: str, size: int, phash: int = 0) -> ImageInfo:
    return ImageInfo(path=Path(path_str), size_bytes=size, perceptual_hash=phash)


def test_choose_duplicate_smaller_is_duplicate():
    small = _make_info("/a/small.jpg", 100)
    large = _make_info("/a/large.jpg", 200)
    duplicate, original = choose_duplicate(small, large)
    assert duplicate is small
    assert original is large


def test_choose_duplicate_larger_first():
    large = _make_info("/a/large.jpg", 200)
    small = _make_info("/a/small.jpg", 100)
    duplicate, original = choose_duplicate(large, small)
    assert duplicate is small
    assert original is large


def test_choose_duplicate_same_size_lexicographic():
    # When sizes are equal, the one with the greater path string is the duplicate
    a = _make_info("/a/aaa.jpg", 100)
    b = _make_info("/a/zzz.jpg", 100)
    duplicate, original = choose_duplicate(a, b)
    assert duplicate is b
    assert original is a


def test_choose_duplicate_same_size_same_path_fallback():
    a = _make_info("/a/img.jpg", 100)
    b = _make_info("/b/img.jpg", 100)
    duplicate, original = choose_duplicate(a, b)
    # /b/img.jpg > /a/img.jpg lexicographically, so b is duplicate
    assert duplicate is b
    assert original is a


# --- unique_destination ---

def test_unique_destination_no_conflict(tmp_path):
    dest = unique_destination(tmp_path, "photo.jpg")
    assert dest == tmp_path / "photo.jpg"


def test_unique_destination_one_conflict(tmp_path):
    (tmp_path / "photo.jpg").touch()
    dest = unique_destination(tmp_path, "photo.jpg")
    assert dest == tmp_path / "photo_1.jpg"


def test_unique_destination_multiple_conflicts(tmp_path):
    (tmp_path / "photo.jpg").touch()
    (tmp_path / "photo_1.jpg").touch()
    (tmp_path / "photo_2.jpg").touch()
    dest = unique_destination(tmp_path, "photo.jpg")
    assert dest == tmp_path / "photo_3.jpg"


# --- iter_image_paths ---

def test_iter_image_paths_basic(tmp_path):
    (tmp_path / "a.jpg").touch()
    (tmp_path / "b.png").touch()
    (tmp_path / "c.txt").touch()
    paths = list(iter_image_paths(tmp_path))
    names = {p.name for p in paths}
    assert names == {"a.jpg", "b.png"}


def test_iter_image_paths_skips_duplicates_dir(tmp_path):
    (tmp_path / "a.jpg").touch()
    dupes_dir = tmp_path / "duplicates"
    dupes_dir.mkdir()
    (dupes_dir / "b.jpg").touch()
    paths = list(iter_image_paths(tmp_path))
    assert all(p.name != "b.jpg" for p in paths)


def test_iter_image_paths_non_recursive_skips_subdir(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "a.jpg").touch()
    paths = list(iter_image_paths(tmp_path, recursive=False))
    assert paths == []


def test_iter_image_paths_recursive(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "a.jpg").touch()
    paths = list(iter_image_paths(tmp_path, recursive=True))
    assert len(paths) == 1
    assert paths[0].name == "a.jpg"


def test_iter_image_paths_case_insensitive_extension(tmp_path):
    (tmp_path / "photo.JPG").touch()
    paths = list(iter_image_paths(tmp_path))
    assert len(paths) == 1


# --- average_hash ---

def _solid_image(tmp_path: Path, color: int, name: str = "img.png") -> Path:
    path = tmp_path / name
    Image.new("L", (64, 64), color).save(path)
    return path


def test_average_hash_returns_int(tmp_path):
    path = _solid_image(tmp_path, 128)
    result = average_hash(path)
    assert isinstance(result, int)


def test_average_hash_identical_images_same_hash(tmp_path):
    p1 = _solid_image(tmp_path, 100, "a.png")
    p2 = _solid_image(tmp_path, 100, "b.png")
    assert average_hash(p1) == average_hash(p2)


def _gradient_image(tmp_path: Path, name: str, left_color: int, right_color: int) -> Path:
    """8x8 image: left half is left_color, right half is right_color."""
    path = tmp_path / name
    img = Image.new("L", (8, 8), left_color)
    for y in range(8):
        for x in range(4, 8):
            img.putpixel((x, y), right_color)
    img.save(path)
    return path


def test_average_hash_different_images_differ(tmp_path):
    # left-bright / right-dark  vs  left-dark / right-bright → different hashes
    a = _gradient_image(tmp_path, "a.png", 255, 0)
    b = _gradient_image(tmp_path, "b.png", 0, 255)
    assert average_hash(a) != average_hash(b)


# --- move_duplicates ---

def _make_solid_image_file(path: Path, color: int) -> Path:
    Image.new("RGB", (64, 64), (color, color, color)).save(path)
    return path


def test_move_duplicates_moves_smaller(tmp_path):
    # Create two identical (visually) images, one larger (more bytes via padding)
    img_a = tmp_path / "a.png"
    img_b = tmp_path / "b.png"
    _make_solid_image_file(img_a, 200)
    _make_solid_image_file(img_b, 200)

    # Make b artificially larger by appending bytes
    with img_b.open("ab") as f:
        f.write(b"\x00" * 1000)

    hash_a = average_hash(img_a)
    hash_b = average_hash(img_b)

    images = [
        ImageInfo(path=img_a, size_bytes=img_a.stat().st_size, perceptual_hash=hash_a),
        ImageInfo(path=img_b, size_bytes=img_b.stat().st_size, perceptual_hash=hash_b),
    ]

    moved_count, moved_bytes = move_duplicates(images, tmp_path, threshold=6)

    # choose_duplicate returns (smaller, larger) = (duplicate, original)
    # img_a is smaller → img_a is the duplicate and gets moved
    assert moved_count == 1
    assert moved_bytes > 0
    assert not img_a.exists()
    assert img_b.exists()
    assert (tmp_path / "duplicates" / "a.png").exists()


def test_move_duplicates_no_duplicates(tmp_path):
    img_a = tmp_path / "a.png"
    img_b = tmp_path / "b.png"
    # Use visually distinct images (left-bright/right-dark vs inverse)
    _gradient_image(tmp_path, "a.png", 255, 0)
    _gradient_image(tmp_path, "b.png", 0, 255)

    images = [
        ImageInfo(path=img_a, size_bytes=img_a.stat().st_size, perceptual_hash=average_hash(img_a)),
        ImageInfo(path=img_b, size_bytes=img_b.stat().st_size, perceptual_hash=average_hash(img_b)),
    ]

    moved_count, moved_bytes = move_duplicates(images, tmp_path, threshold=6)

    assert moved_count == 0
    assert moved_bytes == 0
    assert img_a.exists()
    assert img_b.exists()


def test_move_duplicates_unique_destination_collision(tmp_path):
    # Both images are identical; also pre-create the collision file
    img_a = tmp_path / "a.png"
    img_b = tmp_path / "b.png"
    _make_solid_image_file(img_a, 128)
    _make_solid_image_file(img_b, 128)
    # Make b larger so a is the duplicate
    with img_b.open("ab") as f:
        f.write(b"\x00" * 500)

    dupes_dir = tmp_path / "duplicates"
    dupes_dir.mkdir()
    (dupes_dir / "a.png").touch()  # pre-existing collision

    images = [
        ImageInfo(path=img_a, size_bytes=img_a.stat().st_size, perceptual_hash=average_hash(img_a)),
        ImageInfo(path=img_b, size_bytes=img_b.stat().st_size, perceptual_hash=average_hash(img_b)),
    ]

    move_duplicates(images, tmp_path, threshold=6)

    assert (dupes_dir / "a_1.png").exists()

from pathlib import Path

import pytest
from PIL import Image

from copy_duplicates import copy_duplicates
from image_utils import ImageInfo, average_hash


def _make_solid_image_file(path: Path, color: int) -> Path:
    Image.new("RGB", (64, 64), (color, color, color)).save(path)
    return path


def _make_info(path: Path) -> ImageInfo:
    return ImageInfo(
        path=path,
        size_bytes=path.stat().st_size,
        perceptual_hash=average_hash(path),
    )


def _gradient_image(path: Path, left_color: int, right_color: int) -> Path:
    img = Image.new("L", (8, 8), left_color)
    for y in range(8):
        for x in range(4, 8):
            img.putpixel((x, y), right_color)
    img.save(path)
    return path


# --- copy_duplicates ---

def test_source_larger_copies_to_dest(tmp_path):
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()

    _make_solid_image_file(src_dir / "photo.png", 128)
    _make_solid_image_file(dst_dir / "photo.png", 128)

    # Make source artificially larger
    with (src_dir / "photo.png").open("ab") as f:
        f.write(b"\x00" * 2000)

    src_info = _make_info(src_dir / "photo.png")
    dst_info = _make_info(dst_dir / "photo.png")

    copied, moved, saved = copy_duplicates([src_info], [dst_info], threshold=6, dest_dir=dst_dir)

    assert copied == 1
    assert moved == 1
    # Smaller dest image moved to dest's duplicates
    assert (dst_dir / "duplicates" / "photo.png").exists()
    # Source copied to dest
    assert (dst_dir / "photo.png").exists()
    # Source image still exists (was copied, not moved)
    assert (src_dir / "photo.png").exists()


def test_dest_larger_moves_source_to_duplicates(tmp_path):
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()

    _make_solid_image_file(src_dir / "photo.png", 128)
    _make_solid_image_file(dst_dir / "photo.png", 128)

    # Make dest artificially larger
    with (dst_dir / "photo.png").open("ab") as f:
        f.write(b"\x00" * 2000)

    src_info = _make_info(src_dir / "photo.png")
    dst_info = _make_info(dst_dir / "photo.png")

    copied, moved, saved = copy_duplicates([src_info], [dst_info], threshold=6, dest_dir=dst_dir)

    assert copied == 0
    assert moved == 1
    # Source moved to src's duplicates
    assert (src_dir / "duplicates" / "photo.png").exists()
    assert not (src_dir / "photo.png").exists()
    # Dest untouched
    assert (dst_dir / "photo.png").exists()
    assert not (dst_dir / "duplicates").exists()


def test_equal_size_moves_source_to_duplicates(tmp_path):
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()

    _make_solid_image_file(src_dir / "photo.png", 128)
    _make_solid_image_file(dst_dir / "photo.png", 128)

    src_info = _make_info(src_dir / "photo.png")
    dst_info = _make_info(dst_dir / "photo.png")

    # Ensure equal size
    assert src_info.size_bytes == dst_info.size_bytes

    copied, moved, saved = copy_duplicates([src_info], [dst_info], threshold=6, dest_dir=dst_dir)

    assert copied == 0
    assert moved == 1
    assert (src_dir / "duplicates" / "photo.png").exists()
    assert not (src_dir / "photo.png").exists()


def test_no_duplicate_in_dest_copies_to_dest(tmp_path):
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()

    _gradient_image(src_dir / "a.png", 255, 0)
    _gradient_image(dst_dir / "b.png", 0, 255)

    src_info = _make_info(src_dir / "a.png")
    dst_info = _make_info(dst_dir / "b.png")

    copied, moved, saved = copy_duplicates([src_info], [dst_info], threshold=6, dest_dir=dst_dir)

    assert copied == 1
    assert moved == 0
    # Source image copied to dest
    assert (dst_dir / "a.png").exists()
    # Source still exists (was copied, not moved)
    assert (src_dir / "a.png").exists()
    assert not (src_dir / "duplicates").exists()
    assert not (dst_dir / "duplicates").exists()


def test_dest_collision_uses_unique_destination(tmp_path):
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()

    _make_solid_image_file(src_dir / "photo.png", 128)
    _make_solid_image_file(dst_dir / "photo.png", 128)

    # Make source larger so it gets copied to dest
    with (src_dir / "photo.png").open("ab") as f:
        f.write(b"\x00" * 2000)

    # Pre-create a collision in dest so unique_destination kicks in for the copy
    _make_solid_image_file(dst_dir / "photo_copy.png", 50)

    # Pre-create a collision in dest/duplicates
    dupes = dst_dir / "duplicates"
    dupes.mkdir()
    (dupes / "photo.png").touch()

    src_info = _make_info(src_dir / "photo.png")
    dst_info = _make_info(dst_dir / "photo.png")

    copied, moved, saved = copy_duplicates([src_info], [dst_info], threshold=6, dest_dir=dst_dir)

    assert copied == 1
    # The smaller dest image should land at photo_1.png inside duplicates/
    assert (dupes / "photo_1.png").exists()


def test_already_processed_source_not_double_moved(tmp_path):
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()

    _make_solid_image_file(src_dir / "photo.png", 128)
    _make_solid_image_file(dst_dir / "copy1.png", 128)
    _make_solid_image_file(dst_dir / "copy2.png", 128)

    # Make dest images larger so source gets moved to duplicates on first match
    for name in ["copy1.png", "copy2.png"]:
        with (dst_dir / name).open("ab") as f:
            f.write(b"\x00" * 2000)

    src_info = _make_info(src_dir / "photo.png")
    dst1_info = _make_info(dst_dir / "copy1.png")
    dst2_info = _make_info(dst_dir / "copy2.png")

    copied, moved, saved = copy_duplicates(
        [src_info], [dst1_info, dst2_info], threshold=6, dest_dir=dst_dir
    )

    # Source should only be moved once
    assert moved == 1
    assert not (src_dir / "photo.png").exists()
    assert (src_dir / "duplicates" / "photo.png").exists()

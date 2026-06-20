import json
import time
from pathlib import Path

from PIL import Image

from image_utils import _load_cache, _save_cache, collect_images


def _make_solid(path: Path, color: int = 128) -> Path:
    Image.new("RGB", (64, 64), (color, color, color)).save(path)
    return path


# --- _load_cache / _save_cache ---

def test_load_cache_missing_file(tmp_path):
    assert _load_cache(tmp_path / "nope.json") == {}


def test_load_cache_corrupt_file(tmp_path):
    f = tmp_path / "cache.json"
    f.write_text("not json {{")
    assert _load_cache(f) == {}


def test_save_and_load_roundtrip(tmp_path):
    cache_file = tmp_path / "cache.json"
    data = {"key": {"mtime": 1.0, "size": 100, "hash": 42}}
    _save_cache(data, cache_file)
    assert _load_cache(cache_file) == data


# --- collect_images cache behaviour ---

def test_cache_hit_skips_rehash(tmp_path):
    img = _make_solid(tmp_path / "photo.png")
    cache_file = tmp_path / "cache.json"

    # First pass: compute real hash and populate cache
    images = collect_images(tmp_path, cache_file=cache_file)
    assert len(images) == 1
    real_hash = images[0].perceptual_hash

    # Overwrite the cached hash with a known sentinel
    sentinel = real_hash ^ 0xFFFF
    cache = _load_cache(cache_file)
    cache[str(img)]["hash"] = sentinel
    _save_cache(cache, cache_file)

    # Second pass: must return the sentinel (cache hit)
    images2 = collect_images(tmp_path, cache_file=cache_file)
    assert images2[0].perceptual_hash == sentinel


def test_cache_miss_on_mtime_change(tmp_path):
    img = _make_solid(tmp_path / "photo.png")
    cache_file = tmp_path / "cache.json"

    images = collect_images(tmp_path, cache_file=cache_file)
    real_hash = images[0].perceptual_hash

    # Poison the cache
    sentinel = real_hash ^ 0xFFFF
    cache = _load_cache(cache_file)
    cache[str(img)]["hash"] = sentinel
    # Invalidate by bumping mtime
    cache[str(img)]["mtime"] -= 1.0
    _save_cache(cache, cache_file)

    images2 = collect_images(tmp_path, cache_file=cache_file)
    assert images2[0].perceptual_hash == real_hash


def test_cache_miss_on_size_change(tmp_path):
    img = _make_solid(tmp_path / "photo.png")
    cache_file = tmp_path / "cache.json"

    images = collect_images(tmp_path, cache_file=cache_file)
    real_hash = images[0].perceptual_hash

    # Poison the cache with wrong size
    sentinel = real_hash ^ 0xFFFF
    cache = _load_cache(cache_file)
    cache[str(img)]["hash"] = sentinel
    cache[str(img)]["size"] -= 1
    _save_cache(cache, cache_file)

    images2 = collect_images(tmp_path, cache_file=cache_file)
    assert images2[0].perceptual_hash == real_hash


def test_cache_file_none_disables_cache(tmp_path):
    _make_solid(tmp_path / "photo.png")
    images = collect_images(tmp_path, cache_file=None)
    assert len(images) == 1
    # No cache file created anywhere in tmp_path
    assert not list(tmp_path.glob("*.json"))


def test_cache_file_written_after_first_run(tmp_path):
    _make_solid(tmp_path / "photo.png")
    cache_file = tmp_path / "cache.json"
    assert not cache_file.exists()
    collect_images(tmp_path, cache_file=cache_file)
    assert cache_file.exists()


def test_cache_not_rewritten_when_all_hits(tmp_path):
    img = _make_solid(tmp_path / "photo.png")
    cache_file = tmp_path / "cache.json"

    collect_images(tmp_path, cache_file=cache_file)
    mtime_after_first = cache_file.stat().st_mtime

    # Small sleep to ensure mtime would differ if file were rewritten
    time.sleep(0.05)
    collect_images(tmp_path, cache_file=cache_file)
    assert cache_file.stat().st_mtime == mtime_after_first

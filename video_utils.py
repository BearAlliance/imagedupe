from __future__ import annotations

import base64
import binascii
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    import av
except ImportError:
    print(
        "PyAV is required. Install it with: python3 -m pip install -r requirements.txt",
        file=sys.stderr,
    )
    sys.exit(1)

from PIL import Image

from duplicate_utils import hamming_distance


SUPPORTED_VIDEO_EXTENSIONS = {
    ".3g2",
    ".3gp",
    ".avi",
    ".flv",
    ".m2ts",
    ".m2v",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".mts",
    ".ogv",
    ".ts",
    ".vob",
    ".webm",
    ".wmv",
}
SAMPLE_POSITIONS = tuple(index / 10 for index in range(1, 10))
THUMBNAIL_SIZE = 16
MAX_VISUAL_DIFFERENCE = 18.0
MIN_MATCHING_SAMPLES = 8
CACHE_VERSION = 1
CACHE_FILE = Path(__file__).parent / ".video_hash_cache.json"


@dataclass(frozen=True)
class FrameFingerprint:
    perceptual_hash: int
    pixels: bytes


@dataclass(frozen=True)
class VideoInfo:
    path: Path
    size_bytes: int
    duration_seconds: float
    samples: tuple[FrameFingerprint, ...]


def _load_cache(cache_file: Path) -> dict:
    try:
        cache = json.loads(cache_file.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"version": CACHE_VERSION, "files": {}}

    if cache.get("version") != CACHE_VERSION or not isinstance(
        cache.get("files"), dict
    ):
        return {"version": CACHE_VERSION, "files": {}}
    return cache


def _save_cache(cache: dict, cache_file: Path) -> None:
    try:
        cache_file.write_text(json.dumps(cache))
    except OSError:
        pass


def iter_video_paths(directory: Path, recursive: bool = False) -> Iterable[Path]:
    iterator = directory.rglob("*") if recursive else directory.iterdir()

    for path in sorted(iterator):
        relative = path.relative_to(directory)
        if "duplicates" in relative.parts[:-1]:
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS:
            yield path


def _duration_seconds(
    container: av.container.InputContainer, stream: av.VideoStream
) -> float:
    if stream.duration is not None and stream.time_base is not None:
        duration = float(stream.duration * stream.time_base)
    elif container.duration is not None:
        duration = float(container.duration / av.time_base)
    else:
        raise ValueError("video duration is unavailable")

    if duration <= 0:
        raise ValueError("video duration must be greater than zero")
    return duration


def _average_hash(image: Image.Image, hash_size: int = 8) -> int:
    grayscale = image.convert("L").resize(
        (hash_size, hash_size), Image.Resampling.LANCZOS
    )
    pixels = list(grayscale.getdata())
    average = sum(pixels) / len(pixels)
    value = 0
    for pixel in pixels:
        value <<= 1
        if pixel >= average:
            value |= 1
    return value


def _fingerprint_frame(frame: av.VideoFrame) -> FrameFingerprint:
    image = frame.to_image().convert("RGB").resize(
        (THUMBNAIL_SIZE, THUMBNAIL_SIZE), Image.Resampling.LANCZOS
    )
    return FrameFingerprint(
        perceptual_hash=_average_hash(image), pixels=image.tobytes()
    )


def _frame_at_time(
    container: av.container.InputContainer, target_seconds: float
) -> av.VideoFrame:
    container.seek(int(target_seconds * av.time_base), backward=True)
    closest_frame = None
    closest_distance = float("inf")

    for frame in container.decode(video=0):
        if frame.time is None:
            if closest_frame is None:
                closest_frame = frame
            continue

        distance = abs(float(frame.time) - target_seconds)
        if distance < closest_distance:
            closest_frame = frame
            closest_distance = distance
        if float(frame.time) >= target_seconds:
            break

    if closest_frame is None:
        raise ValueError(f"could not decode a frame at {target_seconds:.3f} seconds")
    return closest_frame


def build_video_info(path: Path) -> VideoInfo:
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise ValueError("file has no video stream")
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        duration = _duration_seconds(container, stream)
        samples = tuple(
            _fingerprint_frame(_frame_at_time(container, duration * position))
            for position in SAMPLE_POSITIONS
        )

    return VideoInfo(
        path=path,
        size_bytes=path.stat().st_size,
        duration_seconds=duration,
        samples=samples,
    )


def _cache_entry(info: VideoInfo, mtime_ns: int) -> dict:
    return {
        "mtime_ns": mtime_ns,
        "size": info.size_bytes,
        "duration": info.duration_seconds,
        "samples": [
            {
                "hash": sample.perceptual_hash,
                "pixels": base64.b64encode(sample.pixels).decode("ascii"),
            }
            for sample in info.samples
        ],
    }


def _cached_video_info(path: Path, entry: dict) -> VideoInfo:
    samples = tuple(
        FrameFingerprint(
            perceptual_hash=int(sample["hash"]),
            pixels=base64.b64decode(sample["pixels"], validate=True),
        )
        for sample in entry["samples"]
    )
    expected_pixels = THUMBNAIL_SIZE * THUMBNAIL_SIZE * 3
    if len(samples) != len(SAMPLE_POSITIONS) or any(
        len(sample.pixels) != expected_pixels for sample in samples
    ):
        raise ValueError("invalid cached sample data")
    return VideoInfo(
        path=path,
        size_bytes=int(entry["size"]),
        duration_seconds=float(entry["duration"]),
        samples=samples,
    )


def collect_videos(
    directory: Path,
    recursive: bool = False,
    cache_file: Path | None = CACHE_FILE,
) -> list[VideoInfo]:
    video_paths = list(iter_video_paths(directory, recursive=recursive))
    videos: list[VideoInfo] = []
    if not video_paths:
        return videos

    cache = _load_cache(cache_file) if cache_file is not None else {
        "version": CACHE_VERSION,
        "files": {},
    }
    cached_files = cache["files"]
    to_hash: list[Path] = []

    for path in video_paths:
        stat = path.stat()
        entry = cached_files.get(str(path))
        if (
            isinstance(entry, dict)
            and entry.get("mtime_ns") == stat.st_mtime_ns
            and entry.get("size") == stat.st_size
        ):
            try:
                videos.append(_cached_video_info(path, entry))
                continue
            except (KeyError, TypeError, ValueError, binascii.Error):
                pass
        to_hash.append(path)

    total = len(to_hash)
    if total:
        print(f"Fingerprinting {total} video(s)...")

    cache_updated = False
    completed = 0
    max_workers = min(4, max(1, os.cpu_count() or 1), total) if total else 1

    if total:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_path = {
                executor.submit(build_video_info, path): path for path in to_hash
            }
            for future in as_completed(future_to_path):
                path = future_to_path[future]
                try:
                    info = future.result()
                    videos.append(info)
                    cached_files[str(path)] = _cache_entry(
                        info, path.stat().st_mtime_ns
                    )
                    cache_updated = True
                except Exception as exc:
                    print(f"Skipping unreadable video {path.name}: {exc}", file=sys.stderr)

                completed += 1
                print(f"\r[fingerprint {completed}/{total}]", end="", flush=True)
        print()

    if cache_file is not None and cache_updated:
        _save_cache(cache, cache_file)

    videos.sort(key=lambda video: video.path)
    return videos


def _pixel_difference(left: bytes, right: bytes) -> float:
    if len(left) != len(right) or not left:
        return float("inf")
    return sum(abs(a - b) for a, b in zip(left, right)) / len(left)


def videos_are_duplicates(first: VideoInfo, second: VideoInfo, threshold: int) -> bool:
    duration_tolerance = max(
        0.5, 0.01 * max(first.duration_seconds, second.duration_seconds)
    )
    if abs(first.duration_seconds - second.duration_seconds) > duration_tolerance:
        return False
    if len(first.samples) != len(second.samples):
        return False

    matching_samples = sum(
        hamming_distance(left.perceptual_hash, right.perceptual_hash) <= threshold
        and _pixel_difference(left.pixels, right.pixels) <= MAX_VISUAL_DIFFERENCE
        for left, right in zip(first.samples, second.samples)
    )
    return matching_samples >= MIN_MATCHING_SAMPLES

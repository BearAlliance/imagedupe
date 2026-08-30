from pathlib import Path

from find_video_duplicates import move_video_duplicates
from video_utils import FrameFingerprint, VideoInfo


def _info(path: Path, size: int) -> VideoInfo:
    pixels = bytes([80] * (16 * 16 * 3))
    sample = FrameFingerprint(perceptual_hash=0, pixels=pixels)
    return VideoInfo(
        path=path,
        size_bytes=size,
        duration_seconds=5.0,
        samples=tuple(sample for _ in range(9)),
    )


def test_move_video_duplicates_keeps_larger_file(tmp_path):
    smaller = tmp_path / "small.mp4"
    larger = tmp_path / "large.mkv"
    smaller.write_bytes(b"small")
    larger.write_bytes(b"larger video")

    moved_count, moved_bytes = move_video_duplicates(
        [_info(smaller, smaller.stat().st_size), _info(larger, larger.stat().st_size)],
        tmp_path,
        threshold=6,
    )

    assert moved_count == 1
    assert moved_bytes == len(b"small")
    assert not smaller.exists()
    assert larger.exists()
    assert (tmp_path / "duplicates" / "small.mp4").exists()


def test_move_video_duplicates_uses_unique_destination(tmp_path):
    first = tmp_path / "clip.mp4"
    second = tmp_path / "keeper.mp4"
    first.write_bytes(b"small")
    second.write_bytes(b"larger video")
    duplicates = tmp_path / "duplicates"
    duplicates.mkdir()
    (duplicates / "clip.mp4").write_bytes(b"existing")

    move_video_duplicates(
        [_info(first, first.stat().st_size), _info(second, second.stat().st_size)],
        tmp_path,
        threshold=6,
    )

    assert (duplicates / "clip.mp4").read_bytes() == b"existing"
    assert (duplicates / "clip_1.mp4").read_bytes() == b"small"


def test_move_video_duplicates_does_not_create_empty_directory(tmp_path):
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    different_sample = FrameFingerprint(perceptual_hash=0, pixels=bytes([255] * 768))
    different = VideoInfo(
        path=second,
        size_bytes=second.stat().st_size,
        duration_seconds=5.0,
        samples=tuple(different_sample for _ in range(9)),
    )

    assert move_video_duplicates(
        [_info(first, first.stat().st_size), different], tmp_path, threshold=6
    ) == (0, 0)
    assert not (tmp_path / "duplicates").exists()

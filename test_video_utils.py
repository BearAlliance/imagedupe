from pathlib import Path

import av
from PIL import Image, ImageDraw

import video_utils
from video_utils import (
    FrameFingerprint,
    VideoInfo,
    build_video_info,
    collect_videos,
    iter_video_paths,
    videos_are_duplicates,
)


def _sample(value: int = 64, perceptual_hash: int = 0) -> FrameFingerprint:
    return FrameFingerprint(
        perceptual_hash=perceptual_hash,
        pixels=bytes([value] * (video_utils.THUMBNAIL_SIZE**2 * 3)),
    )


def _info(
    path: Path,
    size: int = 100,
    duration: float = 10.0,
    samples: tuple[FrameFingerprint, ...] | None = None,
) -> VideoInfo:
    return VideoInfo(
        path=path,
        size_bytes=size,
        duration_seconds=duration,
        samples=samples or tuple(_sample() for _ in video_utils.SAMPLE_POSITIONS),
    )


def _write_video(path: Path, width: int = 64, height: int = 64) -> Path:
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("mpeg4", rate=10)
        stream.width = width
        stream.height = height
        stream.pix_fmt = "yuv420p"

        for index in range(20):
            image = Image.new("RGB", (width, height), (20 + index * 4, 40, 120))
            draw = ImageDraw.Draw(image)
            offset = int(index * (width - width // 4) / 19)
            draw.rectangle(
                (offset, height // 4, offset + width // 4, height // 2),
                fill=(220, 180, 20),
            )
            frame = av.VideoFrame.from_image(image)
            for packet in stream.encode(frame):
                container.mux(packet)

        for packet in stream.encode():
            container.mux(packet)

    return path


def test_iter_video_paths_supports_formats_and_case(tmp_path):
    for name in ["a.mp4", "b.MKV", "c.webm", "d.mov", "ignored.txt"]:
        (tmp_path / name).touch()

    assert {path.name for path in iter_video_paths(tmp_path)} == {
        "a.mp4",
        "b.MKV",
        "c.webm",
        "d.mov",
    }


def test_iter_video_paths_recursive_skips_duplicates(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "clip.mp4").touch()
    duplicates = nested / "duplicates"
    duplicates.mkdir()
    (duplicates / "old.mp4").touch()

    assert list(iter_video_paths(tmp_path)) == []
    assert list(iter_video_paths(tmp_path, recursive=True)) == [nested / "clip.mp4"]


def test_videos_are_duplicates_allows_one_bad_sample(tmp_path):
    matching = [_sample() for _ in video_utils.SAMPLE_POSITIONS]
    one_bad = matching.copy()
    one_bad[4] = _sample(value=255, perceptual_hash=(1 << 64) - 1)

    assert videos_are_duplicates(
        _info(tmp_path / "a.mp4", samples=tuple(matching)),
        _info(tmp_path / "b.mkv", samples=tuple(one_bad)),
        threshold=6,
    )


def test_videos_are_duplicates_rejects_visual_difference(tmp_path):
    assert not videos_are_duplicates(
        _info(tmp_path / "a.mp4"),
        _info(
            tmp_path / "b.mp4",
            samples=tuple(_sample(value=200) for _ in video_utils.SAMPLE_POSITIONS),
        ),
        threshold=6,
    )


def test_videos_are_duplicates_rejects_duration_difference(tmp_path):
    assert not videos_are_duplicates(
        _info(tmp_path / "a.mp4", duration=10.0),
        _info(tmp_path / "b.mp4", duration=11.0),
        threshold=6,
    )


def test_build_video_info_matches_reencoded_resolution(tmp_path):
    first = build_video_info(_write_video(tmp_path / "first.mp4", 64, 64))
    second = build_video_info(_write_video(tmp_path / "second.avi", 96, 96))

    assert len(first.samples) == len(video_utils.SAMPLE_POSITIONS)
    assert videos_are_duplicates(first, second, threshold=6)


def test_build_video_info_falls_back_when_seeking_is_not_permitted(
    tmp_path, monkeypatch
):
    path = _write_video(tmp_path / "nonseekable.mp4")

    def fail_seeking(candidate: Path):
        raise video_utils.VideoSeekError("[Errno 1] Operation not permitted")

    monkeypatch.setattr(video_utils, "_fingerprints_with_seeking", fail_seeking)
    info = build_video_info(path)

    assert info.path == path
    assert len(info.samples) == len(video_utils.SAMPLE_POSITIONS)


def test_frame_at_time_identifies_seek_errors():
    class NonSeekableContainer:
        def seek(self, offset: int, backward: bool):
            raise PermissionError(1, "Operation not permitted")

    try:
        video_utils._frame_at_time(NonSeekableContainer(), 1.0)
    except video_utils.VideoSeekError as exc:
        assert "Operation not permitted" in str(exc)
    else:
        raise AssertionError("Expected VideoSeekError")


def test_collect_videos_uses_cache(tmp_path, monkeypatch):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"video")
    cache_file = tmp_path / "cache.json"
    built = _info(path, size=path.stat().st_size)
    calls = 0

    def fake_build(candidate: Path) -> VideoInfo:
        nonlocal calls
        calls += 1
        assert candidate == path
        return built

    monkeypatch.setattr(video_utils, "build_video_info", fake_build)
    assert collect_videos(tmp_path, cache_file=cache_file) == [built]
    assert collect_videos(tmp_path, cache_file=cache_file) == [built]
    assert calls == 1


def test_collect_videos_invalidates_cache_on_schema_change(tmp_path, monkeypatch):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"video")
    cache_file = tmp_path / "cache.json"
    cache_file.write_text('{"version": 0, "files": {}}')
    built = _info(path, size=path.stat().st_size)
    calls = 0

    def fake_build(candidate: Path) -> VideoInfo:
        nonlocal calls
        calls += 1
        return built

    monkeypatch.setattr(video_utils, "build_video_info", fake_build)
    assert collect_videos(tmp_path, cache_file=cache_file) == [built]
    assert calls == 1


def test_collect_videos_invalidates_cache_on_file_change(tmp_path, monkeypatch):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"video")
    cache_file = tmp_path / "cache.json"
    calls = 0

    def fake_build(candidate: Path) -> VideoInfo:
        nonlocal calls
        calls += 1
        return _info(candidate, size=candidate.stat().st_size)

    monkeypatch.setattr(video_utils, "build_video_info", fake_build)
    collect_videos(tmp_path, cache_file=cache_file)
    path.write_bytes(b"changed video")
    collect_videos(tmp_path, cache_file=cache_file)
    assert calls == 2


def test_collect_videos_recovers_from_corrupt_cache(tmp_path, monkeypatch):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"video")
    cache_file = tmp_path / "cache.json"
    cache_file.write_text("not json")
    built = _info(path, size=path.stat().st_size)
    monkeypatch.setattr(video_utils, "build_video_info", lambda candidate: built)

    assert collect_videos(tmp_path, cache_file=cache_file) == [built]


def test_collect_videos_skips_unreadable_file(tmp_path, capsys):
    (tmp_path / "broken.mp4").write_bytes(b"not a video")

    assert collect_videos(tmp_path, cache_file=None) == []
    assert "Skipping unreadable video broken.mp4" in capsys.readouterr().err

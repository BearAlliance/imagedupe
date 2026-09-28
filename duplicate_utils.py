from __future__ import annotations

import errno
from pathlib import Path
from typing import Protocol, TypeVar


class SizedFile(Protocol):
    path: Path
    size_bytes: int


SizedFileT = TypeVar("SizedFileT", bound=SizedFile)


def choose_duplicate(
    first: SizedFileT, second: SizedFileT
) -> tuple[SizedFileT, SizedFileT]:
    if first.size_bytes < second.size_bytes:
        return first, second
    if second.size_bytes < first.size_bytes:
        return second, first
    if str(first.path) < str(second.path):
        return second, first
    return first, second


def is_out_of_space(error: OSError) -> bool:
    return error.errno in (errno.ENOSPC, errno.EDQUOT)


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


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

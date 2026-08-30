# AGENTS.md

## Architecture

Keep image-specific discovery and fingerprinting in `image_utils.py`.

Keep video-specific discovery, decoding, fingerprinting, and cache handling in `video_utils.py`.

Keep media-independent file selection, byte formatting, and collision handling in `duplicate_utils.py`.

CLI entry points should validate arguments, delegate media analysis to their utility module, and handle reporting and file moves.

## Documentation

When changing structural or architectural aspects of the codebase, update `AGENTS.md` or `CLAUDE.md` to reflect the new guidance.

When changing the user interface, update the relevant sections of `README.md` or other existing user documentation.

## Markdown

Use one sentence per line when writing Markdown while preserving intended formatting.

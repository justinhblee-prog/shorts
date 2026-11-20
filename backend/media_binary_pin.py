"""Verify local media tool binaries against an image-baked SHA-256 manifest."""
from __future__ import annotations

import hashlib
import hmac
import re
from pathlib import Path


_SHA256 = re.compile(r"^[a-f0-9]{64}$")


class MediaBinaryPinError(RuntimeError):
    """A required FFmpeg/ffprobe binary does not match the image manifest."""


def verify_binary_manifest(binary_paths, manifest_path):
    manifest = Path(manifest_path)
    if not manifest.is_absolute() or manifest.is_symlink() or not manifest.is_file():
        raise MediaBinaryPinError("media binary SHA-256 manifest is missing or unsafe")
    expected = {}
    try:
        lines = manifest.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError) as exc:
        raise MediaBinaryPinError("media binary SHA-256 manifest could not be read") from exc
    for line in lines:
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or not _SHA256.fullmatch(parts[0]):
            raise MediaBinaryPinError("media binary SHA-256 manifest is malformed")
        path = parts[1].lstrip("*")
        if path in expected:
            raise MediaBinaryPinError("media binary SHA-256 manifest contains duplicates")
        expected[path] = parts[0]

    verified = {}
    for value in binary_paths:
        binary = Path(value)
        if not binary.is_absolute() or binary.is_symlink() or not binary.is_file():
            raise MediaBinaryPinError("configured media binary must be an absolute regular file")
        key = str(binary)
        digest = expected.get(key)
        if digest is None:
            raise MediaBinaryPinError("configured media binary is not pinned by the image manifest")
        actual = hashlib.sha256()
        with binary.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                actual.update(chunk)
        actual_hex = actual.hexdigest()
        if not hmac.compare_digest(actual_hex, digest):
            raise MediaBinaryPinError("configured media binary checksum does not match image manifest")
        verified[key] = actual_hex
    return verified

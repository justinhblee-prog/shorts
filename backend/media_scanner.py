"""Fail-closed ClamAV scanning for staged renderer artifacts."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


class MediaScanError(RuntimeError):
    pass


class ClamAVScanner:
    """Run the local ClamAV scanner without a shell or following symlinks."""

    def __init__(self, executable=None, timeout=None, runner=None):
        self.executable = executable or os.getenv("NEXUS_CLAMSCAN_PATH", "clamscan")
        self.timeout = int(timeout or os.getenv("NEXUS_MEDIA_SCAN_TIMEOUT_SECONDS", "120"))
        self.runner = runner or subprocess.run
        if not self.executable or self.timeout < 1:
            raise ValueError("scanner executable and positive timeout are required")

    def scan(self, path):
        target = Path(path)
        if target.is_symlink() or not target.is_file():
            raise MediaScanError("Media scan target must be a regular non-symlink file")
        try:
            result = self.runner(
                [self.executable, "--no-summary", "--infected", "--stdout", str(target)],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise MediaScanError("Malware scanner timed out") from exc
        except OSError as exc:
            raise MediaScanError("Malware scanner could not be started") from exc

        if result.returncode == 0:
            return {"status": "clean", "engine": "clamav"}
        if result.returncode == 1:
            raise MediaScanError("Malware scanner detected an infected artifact")
        raise MediaScanError("Malware scanner failed; artifact was not staged")

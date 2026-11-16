"""Fail-closed ClamAV scanning for staged renderer artifacts."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


class MediaScanError(RuntimeError):
    pass


class ClamAVScanner:
    """Run ClamAV without a shell and require an explicit clean exit."""

    def __init__(self, executable=None, timeout=None, database_dir=None, runner=None,
                 max_bytes=None):
        self.executable = str(
            executable if executable is not None
            else os.getenv("NEXUS_CLAMSCAN_PATH", "clamscan")
        ).strip()
        raw_timeout = (
            timeout if timeout is not None
            else os.getenv("NEXUS_MEDIA_SCAN_TIMEOUT_SECONDS", "120")
        )
        try:
            self.timeout = int(raw_timeout)
        except (TypeError, ValueError) as exc:
            raise ValueError("malware scanner timeout must be a positive integer") from exc
        self.database_dir = str(
            database_dir if database_dir is not None
            else os.getenv("NEXUS_CLAMAV_DATABASE_DIR", "/var/lib/clamav")
        ).strip()
        raw_max_bytes = (
            max_bytes if max_bytes is not None
            else os.getenv("NEXUS_MAX_MEDIA_BYTES", str(256 * 1024 * 1024))
        )
        try:
            self.max_bytes = int(raw_max_bytes)
        except (TypeError, ValueError) as exc:
            raise ValueError("scanner max_bytes must be a positive integer no larger than 2 GiB") from exc
        self.runner = runner if runner is not None else subprocess.run
        if (
            not self.executable
            or self.timeout < 1
            or self.max_bytes < 1
            or self.max_bytes > 2 * 1024 * 1024 * 1024
            or not self.database_dir
            or any(ord(character) < 32 or ord(character) == 127 for character in self.executable)
            or any(ord(character) < 32 or ord(character) == 127 for character in self.database_dir)
        ):
            raise ValueError("scanner executable, database directory and positive timeout are required")

    def scan(self, path):
        target = Path(path)
        if target.is_symlink() or not target.is_file():
            raise MediaScanError("Media scan target must be a regular non-symlink file")
        try:
            result = self.runner(
                [
                    self.executable,
                    "--database=" + self.database_dir,
                    "--no-summary",
                    "--infected",
                    "--stdout",
                    "--alert-exceeds-max=yes",
                    "--max-filesize=" + str(self.max_bytes),
                    "--max-scansize=" + str(self.max_bytes),
                    "--max-scantime=" + str(self.timeout * 1000),
                    str(target),
                ],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise MediaScanError("Malware scanner timed out") from exc
        except OSError as exc:
            raise MediaScanError("Malware scanner could not be started") from exc

        returncode = getattr(result, "returncode", None)
        if returncode == 0:
            return {"status": "clean", "engine": "clamav"}
        if returncode == 1:
            output = (getattr(result, "stdout", "") or "") + (getattr(result, "stderr", "") or "")
            if "Heuristics.Limits.Exceeded" in output:
                raise MediaScanError("Malware scan was incomplete because a scanner limit was exceeded")
            raise MediaScanError("Malware scanner detected an infected artifact")
        raise MediaScanError("Malware scanner failed; artifact was not staged")

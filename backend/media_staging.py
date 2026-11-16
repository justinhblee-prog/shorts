"""Allowlisted HTTPS renderer artifact download into the YouTube media staging area."""
import hashlib
import http.client
import ipaddress
import os
import socket
import ssl
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from media_scanner import ClamAVScanner, MediaScanError


class MediaStagingError(RuntimeError):
    pass


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to a prevalidated public IP while retaining hostname TLS verification."""
    def __init__(self, hostname, ip, timeout):
        super().__init__(hostname, port=443, timeout=timeout, context=ssl.create_default_context())
        self._pinned_ip = ip

    def connect(self):
        raw = socket.create_connection((self._pinned_ip, 443), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


class MediaStager:
    def __init__(self, media_dir=None, allowed_hosts=None, max_bytes=None,
                 resolver=None, fetcher=None, timeout=45, scanner=None,
                 scan_enabled=None):
        self.media_dir = Path(media_dir or os.getenv("NEXUS_MEDIA_DIR", "data/media")).resolve()
        configured = allowed_hosts if allowed_hosts is not None else os.getenv("RENDER_ARTIFACT_HOSTS", "")
        self.allowed_hosts = {x.strip().lower().rstrip(".") for x in configured.split(",") if x.strip()}
        self.max_bytes = int(max_bytes or os.getenv("NEXUS_MAX_MEDIA_BYTES", str(256 * 1024 * 1024)))
        self.resolver = resolver or self._resolve
        self.fetcher = fetcher or self._fetch
        self.timeout = timeout
        if scan_enabled is None:
            raw_scan_setting = os.getenv("NEXUS_MEDIA_SCAN_ENABLED", "false").strip().lower()
            scan_enabled = (
                raw_scan_setting in {"1", "true", "yes", "on"}
                or raw_scan_setting not in {"0", "false", "no", "off", ""}
            )
        elif isinstance(scan_enabled, str):
            raw_scan_setting = scan_enabled.strip().lower()
            scan_enabled = (
                raw_scan_setting in {"1", "true", "yes", "on"}
                or raw_scan_setting not in {"0", "false", "no", "off", ""}
            )
        self.scan_enabled = bool(scan_enabled)
        # Construct the optional scanner lazily during staging so malformed
        # scan settings are reported by preflight and do not prevent API startup.
        self.scanner = scanner

    @staticmethod
    def _resolve(host):
        try:
            records = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            return list({item[4][0] for item in records})
        except OSError as exc:
            raise MediaStagingError("Artifact hostname could not be resolved") from exc

    @staticmethod
    def _fetch(host, ip, path, timeout):
        connection = _PinnedHTTPSConnection(host, ip, timeout)
        try:
            connection.request("GET", path, headers={"Host": host, "Accept": "video/mp4,application/octet-stream"})
            response = connection.getresponse()
            headers = {k.lower(): v for k, v in response.getheaders()}
            if response.status != 200:
                connection.close()
                return response.status, headers, []
            def chunks():
                try:
                    while True:
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        yield block
                except OSError as exc:
                    raise MediaStagingError("Renderer artifact stream was interrupted") from exc
                finally:
                    connection.close()
            return response.status, headers, chunks()
        except OSError as exc:
            connection.close()
            raise MediaStagingError("Renderer artifact download failed") from exc

    def staged_path(self, job_id):
        filename = hashlib.sha256(str(job_id).encode("utf-8")).hexdigest() + ".mp4"
        return self.media_dir / filename

    @staticmethod
    def fingerprint(path):
        """Return a streaming SHA-256/size fingerprint for a regular, non-symlink file."""
        candidate = Path(path)
        if candidate.is_symlink() or not candidate.is_file():
            raise MediaStagingError("Staged media must be a regular file, not a symlink")
        digest = hashlib.sha256()
        total = 0
        try:
            with candidate.open("rb") as stream:
                while True:
                    block = stream.read(1024 * 1024)
                    if not block:
                        break
                    total += len(block)
                    digest.update(block)
        except OSError as exc:
            raise MediaStagingError("Staged media could not be fingerprinted") from exc
        return {"media_path": candidate.name, "size_bytes": total,
                "sha256": digest.hexdigest(), "content_type": "video/mp4"}

    def cleanup_uploaded(self, job_id, upload_store):
        """Delete only this job's staged file, and only after durable upload confirmation."""
        upload = upload_store.get(job_id)
        if upload is None or upload.get("status") != "uploaded" or not upload.get("video_id"):
            raise MediaStagingError("Media can be removed only after a confirmed YouTube upload")
        target = self.staged_path(job_id)
        if target.is_symlink():
            raise MediaStagingError("Refusing to remove a symlink from the media staging area")
        try:
            if target.parent.resolve() != self.media_dir:
                raise MediaStagingError("Staged media path escaped the media directory")
            target.unlink(missing_ok=True)
        except OSError as exc:
            raise MediaStagingError("Staged media could not be removed") from exc
        return {"job_id": str(job_id), "removed": not target.exists(),
                "reason": "confirmed_upload", "video_id": upload["video_id"]}

    def prune_temporary_files(self, older_than_seconds=86400, now=None):
        """Remove abandoned atomic-write .part files only after a conservative age threshold."""
        if older_than_seconds < 3600:
            raise ValueError("Temporary media retention must be at least one hour")
        import time
        cutoff = (now if now is not None else time.time()) - older_than_seconds
        removed = []
        if not self.media_dir.exists():
            return {"removed": [], "count": 0}
        for candidate in self.media_dir.glob(".nexus-*.part"):
            try:
                if candidate.is_file() and candidate.stat().st_mtime <= cutoff:
                    candidate.unlink()
                    removed.append(candidate.name)
            except FileNotFoundError:
                continue
            except OSError:
                continue
        return {"removed": removed, "count": len(removed)}

    def stage(self, job_id, artifact_url):
        parsed = urlsplit(artifact_url or "")
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme != "https" or not host or parsed.username or parsed.password:
            raise MediaStagingError("Artifact URL must be HTTPS without embedded credentials")
        if parsed.port not in (None, 443) or parsed.fragment:
            raise MediaStagingError("Artifact URL uses an unsupported port or fragment")
        if host not in self.allowed_hosts:
            raise MediaStagingError("Artifact hostname is not in RENDER_ARTIFACT_HOSTS")
        ips = self.resolver(host)
        if not ips:
            raise MediaStagingError("Artifact hostname resolved to no addresses")
        parsed_ips = []
        for raw_ip in ips:
            try:
                ip = ipaddress.ip_address(raw_ip)
            except ValueError as exc:
                raise MediaStagingError("Artifact hostname returned an invalid IP address") from exc
            if not ip.is_global:
                raise MediaStagingError("Artifact hostname resolves to a non-public IP address")
            parsed_ips.append(str(ip))
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        status, headers, chunks = self.fetcher(host, parsed_ips[0], path, self.timeout)
        if status != 200:
            raise MediaStagingError("Artifact server must return HTTP 200; redirects are not followed")
        content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type not in ("video/mp4", "application/octet-stream"):
            raise MediaStagingError("Artifact response is not an MP4 media type")
        declared = headers.get("content-length")
        if declared:
            try:
                if int(declared) > self.max_bytes:
                    raise MediaStagingError("Artifact exceeds NEXUS_MAX_MEDIA_BYTES")
            except ValueError as exc:
                raise MediaStagingError("Artifact has an invalid Content-Length") from exc
        self.media_dir.mkdir(parents=True, exist_ok=True)
        filename = hashlib.sha256(str(job_id).encode("utf-8")).hexdigest() + ".mp4"
        destination = (self.media_dir / filename).resolve()
        destination.relative_to(self.media_dir)
        temporary = None
        total = 0
        prefix = b""
        digest = hashlib.sha256()
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=self.media_dir,
                                             prefix=".nexus-", suffix=".part", delete=False) as out:
                temporary = Path(out.name)
                for chunk in chunks:
                    if not isinstance(chunk, (bytes, bytearray)):
                        raise MediaStagingError("Artifact stream returned non-binary data")
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > self.max_bytes:
                        raise MediaStagingError("Artifact exceeds NEXUS_MAX_MEDIA_BYTES")
                    if len(prefix) < 12:
                        prefix += bytes(chunk[:12-len(prefix)])
                    digest.update(chunk)
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            if total < 12 or prefix[4:8] != b"ftyp":
                raise MediaStagingError("Downloaded artifact does not contain an MP4 file signature")
            scan_status = "disabled"
            if self.scan_enabled:
                scanner = self.scanner
                if scanner is None:
                    try:
                        scanner = ClamAVScanner(max_bytes=self.max_bytes)
                    except Exception as exc:
                        raise MediaStagingError("Malware scanner configuration is invalid") from exc
                try:
                    scan_result = scanner.scan(temporary)
                except MediaScanError as exc:
                    raise MediaStagingError(str(exc)) from exc
                except Exception as exc:
                    raise MediaStagingError("Malware scanner failed; artifact was not staged") from exc
                if not isinstance(scan_result, dict) or scan_result.get("status") != "clean":
                    raise MediaStagingError("Malware scanner did not explicitly confirm a clean artifact")
                scan_status = "clean"
            os.replace(str(temporary), str(destination))
            return {
                "media_path": filename,
                "size_bytes": total,
                "sha256": digest.hexdigest(),
                "content_type": "video/mp4",
                "malware_scan": scan_status,
            }
        except Exception:
            if temporary is not None:
                try: temporary.unlink(missing_ok=True)
                except OSError: pass
            raise

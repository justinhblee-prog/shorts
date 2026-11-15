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
                 resolver=None, fetcher=None, timeout=45):
        self.media_dir = Path(media_dir or os.getenv("NEXUS_MEDIA_DIR", "data/media")).resolve()
        configured = allowed_hosts if allowed_hosts is not None else os.getenv("RENDER_ARTIFACT_HOSTS", "")
        self.allowed_hosts = {x.strip().lower().rstrip(".") for x in configured.split(",") if x.strip()}
        self.max_bytes = int(max_bytes or os.getenv("NEXUS_MAX_MEDIA_BYTES", str(256 * 1024 * 1024)))
        self.resolver = resolver or self._resolve
        self.fetcher = fetcher or self._fetch
        self.timeout = timeout

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
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            if total < 12 or prefix[4:8] != b"ftyp":
                raise MediaStagingError("Downloaded artifact does not contain an MP4 file signature")
            os.replace(str(temporary), str(destination))
            return {"media_path": filename, "size_bytes": total, "content_type": "video/mp4"}
        except Exception:
            if temporary is not None:
                try: temporary.unlink(missing_ok=True)
                except OSError: pass
            raise

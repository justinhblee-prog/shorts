"""Strict allowlist parsing for browser CORS origins."""
from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlsplit


class CorsOriginConfigurationError(ValueError):
    """Raised when a configured browser origin is not a safe absolute origin."""


def parse_cors_origins(raw: str | None = None) -> list[str]:
    """Return normalized HTTP(S) origins; reject paths, opaque and insecure remote origins."""
    if raw is None:
        raw = os.getenv("NEXUS_CORS_ORIGINS", "")
    origins: list[str] = []
    seen: set[str] = set()
    for item in raw.split(","):
        candidate = item.strip()
        if not candidate:
            continue
        try:
            parsed = urlsplit(candidate)
            scheme = parsed.scheme.lower()
            host = parsed.hostname
            port = parsed.port
        except ValueError as exc:
            raise CorsOriginConfigurationError("NEXUS_CORS_ORIGINS contains an invalid origin") from exc
        if (scheme not in {"http", "https"} or not host or parsed.username is not None
                or parsed.password is not None or parsed.path not in {"", "/"}
                or parsed.query or parsed.fragment or "*" in candidate
                or host.lower() == "null"):
            raise CorsOriginConfigurationError(
                "CORS entries must be exact HTTP(S) origins without paths, credentials, wildcards or opaque hosts"
            )
        try:
            address = ipaddress.ip_address(host)
            is_loopback = address.is_loopback
        except ValueError:
            is_loopback = host.lower() == "localhost"
        if scheme != "https" and not is_loopback:
            raise CorsOriginConfigurationError("Non-local browser origins must use HTTPS")
        normalized_host = host.lower()
        if ":" in normalized_host and not normalized_host.startswith("["):
            normalized_host = f"[{normalized_host}]"
        if port is not None and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
            normalized_host = f"{normalized_host}:{port}"
        normalized = f"{scheme}://{normalized_host}"
        if normalized not in seen:
            seen.add(normalized)
            origins.append(normalized)
    return origins

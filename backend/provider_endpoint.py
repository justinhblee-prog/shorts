"""Validation shared by provider adapters and configuration preflight."""
from urllib.parse import urlsplit


def provider_endpoint_error(value):
    """Return a safe reason when a credential-bearing provider URL is unsafe."""
    if not isinstance(value, str) or not value.strip():
        return "provider URL is missing"
    candidate = value.strip()
    if any(character.isspace() or ord(character) < 33 for character in candidate):
        return "provider URL contains whitespace or control characters"
    try:
        parsed = urlsplit(candidate)
        # Accessing .port validates malformed and out-of-range port syntax.
        parsed.port
    except ValueError:
        return "provider URL is malformed"
    if parsed.scheme.lower() != "https":
        return "provider URL must use HTTPS"
    if not parsed.hostname:
        return "provider URL must include a hostname"
    if parsed.username is not None or parsed.password is not None:
        return "provider URL must not contain embedded credentials"
    if parsed.fragment:
        return "provider URL must not contain a fragment"
    if "\\" in parsed.netloc or any(
        character.isspace() or ord(character) < 33 for character in parsed.netloc
    ):
        return "provider URL contains invalid hostname characters"
    return None

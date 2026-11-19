"""Shared redaction for diagnostics persisted or emitted by development workers."""
import re


def redact_sensitive_text(value, limit=2000):
    """Remove common credential forms before diagnostics leave a trusted process."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")
    text = (value or "").strip()
    text = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer [REDACTED]", text)
    text = re.sub(
        r"(?i)([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTHORIZATION|COOKIE|SESSION|API[_-]?KEY|ENCRYPTION[_-]?KEY|"
        r"PRIVATE[_-]?KEY|SIGNING[_-]?KEY|ACCESS[_-]?KEY|SERVICE[_-]?ROLE[_-]?KEY|"
        r"DATABASE[_-]?URL|DB[_-]?URL|REDIS[_-]?URL|POSTGRES[_-]?URL|MYSQL[_-]?URL|"
        r"MONGODB[_-]?URI|MONGO[_-]?URL|SUPABASE[_-]?URL|SERVICE[_-]?ACCOUNT|"
        r"CONNECTION[_-]?STRING)[A-Z0-9_]*)"
        r"\s*[=:]\s*[\s\S]*",
        r"\1=[REDACTED]", text,
    )
    text = re.sub(
        r"(?i)\b(https?|postgres(?:ql)?|redis)://[^\s/@:]+(?::[^\s/@]*)?@[^\s,;]+",
        r"\1://[REDACTED]@[REDACTED]", text,
    )
    text = re.sub(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})\b",
                  "[REDACTED]", text)
    return text[-limit:]

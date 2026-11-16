"""Strict parsing and cross-field validation for scheduler process settings."""
import re


def _integer_setting(env, name, default, minimum, maximum):
    raw = env.get(name, str(default))
    if not isinstance(raw, str) or re.fullmatch(r"[0-9]+", raw.strip()) is None:
        raise ValueError(f"{name} must be a decimal integer")
    value = int(raw.strip())
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def load_scheduler_config(env):
    """Return (poll_interval_seconds, leader_lease_seconds) after validation."""
    poll = _integer_setting(env, "NEXUS_SCHEDULER_POLL_SECONDS", 30, 5, 300)
    lease = _integer_setting(env, "NEXUS_SCHEDULER_LEASE_SECONDS", 90, 15, 3600)
    if poll > lease // 3:
        raise ValueError(
            "NEXUS_SCHEDULER_POLL_SECONDS must not exceed one-third "
            "of NEXUS_SCHEDULER_LEASE_SECONDS"
        )
    return poll, lease

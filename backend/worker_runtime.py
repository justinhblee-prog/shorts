"""Pure worker runtime configuration helpers."""


def heartbeat_interval(lease_seconds, configured_seconds=10):
    """Keep pause/lost-lease detection responsive within the active lease."""
    return max(5, min(int(configured_seconds), max(5, int(lease_seconds) // 3)))

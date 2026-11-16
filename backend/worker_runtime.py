"""Pure worker runtime configuration helpers."""


import re


def _strict_env_integer(value, name, minimum, maximum):
    """Parse an unsigned decimal environment value without Python coercions."""
    if not isinstance(value, str) or re.fullmatch(r"[0-9]+", value) is None:
        raise ValueError(f"{name} must be a decimal integer")
    parsed = int(value)
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def parse_worker_runtime_config(lease_seconds="300", idle_seconds="3",
                                heartbeat_seconds="10"):
    """Validate worker environment settings and keep heartbeats inside the lease."""
    lease = _strict_env_integer(lease_seconds, "NEXUS_LEASE_SECONDS", 30, 3600)
    idle = _strict_env_integer(idle_seconds, "NEXUS_IDLE_SECONDS", 1, 300)
    configured_heartbeat = _strict_env_integer(
        heartbeat_seconds, "NEXUS_HEARTBEAT_SECONDS", 5, 3600
    )
    heartbeat = min(configured_heartbeat, lease // 3)
    return lease, idle, heartbeat


def heartbeat_interval(lease_seconds, configured_seconds=10):
    """Keep pause/lost-lease detection responsive within the active lease."""
    return max(5, min(int(configured_seconds), max(5, int(lease_seconds) // 3)))



def request_worker_shutdown(queue, stopping, active_job_id, lost_lease_event, signum,
                            worker_id=None, generation_token=None):
    """Request local stop only; the worker loop persists pauses outside signal context.

    Python signal handlers run on the main thread and may interrupt queue.claim()
    while it owns a SQLite write transaction. Performing another DB write here
    can block on the transaction that cannot resume until this handler returns.
    run_once() observes these events and persists the pause after the transaction
    unwinds, or after provider execution has stopped.
    """
    stopping.set()
    if lost_lease_event is not None:
        lost_lease_event.set()

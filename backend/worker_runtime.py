"""Pure worker runtime configuration helpers."""


def heartbeat_interval(lease_seconds, configured_seconds=10):
    """Keep pause/lost-lease detection responsive within the active lease."""
    return max(5, min(int(configured_seconds), max(5, int(lease_seconds) // 3)))



def request_worker_shutdown(queue, stopping, active_job_id, lost_lease_event, signum):
    """Fence active production work on process termination; always request local stop."""
    stopping.set()
    if lost_lease_event is not None:
        lost_lease_event.set()
    if active_job_id:
        try:
            queue.pause(
                f"Worker received signal {signum} during production; provider outcome may be ambiguous",
                active_job_id,
            )
        except Exception:
            # Local stop is still signalled. The durable queue/lease check remains
            # the final safety boundary if the database is temporarily unavailable.
            pass

"""Fail-closed integrity checks for human-approved production artifacts."""
import json


def approval_snapshot_matches_current_artifacts(connection, job_id, snapshot):
    """Return (matches, reason) for the exact ordered artifact set approved by a human.

    The comparison includes stage, artifact type, URL, and parsed metadata. Added,
    removed, reordered, malformed, or modified artifacts invalidate the approval.
    """
    try:
        approved = json.loads(snapshot) if isinstance(snapshot, str) else snapshot
        if not isinstance(approved, list) or not approved:
            return False, "Approval artifact snapshot is missing or invalid"
        rows = connection.execute(
            """SELECT stage,artifact_type,artifact_url,metadata_json
               FROM production_artifacts WHERE job_id=? ORDER BY created_at,id""",
            (job_id,),
        ).fetchall()
        current = []
        for row in rows:
            metadata = json.loads(row["metadata_json"])
            current.append({
                "stage": row["stage"],
                "artifact_type": row["artifact_type"],
                "artifact_url": row["artifact_url"],
                "metadata": metadata,
            })
        if not current:
            return False, "Current production artifacts are missing"
        canonical = lambda value: json.dumps(
            value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        )
        if canonical(approved) != canonical(current):
            return False, "Production artifacts changed after human approval; return to review"
        return True, None
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        return False, "Approval or current artifact snapshot is malformed"

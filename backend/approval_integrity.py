"""Approval-to-artifact integrity checks shared by platform publishers."""
import json


def approval_snapshot_matches_current_artifacts(connection, job_id, snapshot_json):
    """Return (matches, reason) for the exact artifact set reviewed by a human.

    The comparison covers stage, type, URL and parsed metadata, including ordering.
    A missing, malformed, added, removed or modified artifact invalidates approval.
    """
    try:
        approved = json.loads(snapshot_json) if isinstance(snapshot_json, str) else snapshot_json
        if not isinstance(approved, list) or not approved:
            return False, "Approval artifact snapshot is missing or invalid"
        current_rows = connection.execute(
            """SELECT stage,artifact_type,artifact_url,metadata_json
               FROM production_artifacts WHERE job_id=? ORDER BY created_at,id""",
            (job_id,),
        ).fetchall()
        current = []
        for row in current_rows:
            metadata = json.loads(row["metadata_json"])
            if not isinstance(metadata, (dict, list, str, int, float, bool)) and metadata is not None:
                return False, "Current artifact metadata is invalid"
            current.append({
                "stage": row["stage"],
                "artifact_type": row["artifact_type"],
                "artifact_url": row["artifact_url"],
                "metadata": metadata,
            })
        if not current:
            return False, "Current production artifacts are missing"
        canonical = lambda value: json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        if canonical(approved) != canonical(current):
            return False, "Production artifacts changed after human approval; return to review"
        return True, None
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        return False, "Approval or current artifact snapshot is malformed"

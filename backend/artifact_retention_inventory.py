"""Workspace-scoped read-only retention inventory.

This module performs SELECT-only inventory queries. It never reads file paths,
writes database rows, changes queue state, creates tombstones or deletes files.
Legal-hold, integrity/storage and backup state remain unknown until authoritative
providers are configured, so inventory results fail closed by construction.
"""
from __future__ import annotations

import json


class RetentionInventoryError(RuntimeError):
    """The read-only inventory could not be completed safely."""


_ACTIVE_JOB_STATUSES = {"queued", "running", "failed_retriable"}
_TERMINAL_JOB_STATUSES = {"failed_terminal", "cancelled", "completed"}
_TERMINAL_REVIEW_STATUSES = {"approved", "rejected", "revision_requested"}


def _query_only(connection):
    connection.execute("PRAGMA query_only=ON")


class RetentionInventory:
    def __init__(self, asset_store, artifact_store, snapshot_store, workspace_store):
        self.assets = asset_store
        self.artifacts = artifact_store
        self.snapshots = snapshot_store
        self.workspaces = workspace_store

    @staticmethod
    def _job_reference_state(job_status, review_status):
        if not isinstance(job_status, str):
            return False, None
        if job_status in _ACTIVE_JOB_STATUSES:
            return True, True
        if job_status == "review_pending":
            if review_status is None:
                return True, True
            if isinstance(review_status, str) and review_status in _TERMINAL_REVIEW_STATUSES:
                return True, False
            return False, None
        if job_status in _TERMINAL_JOB_STATUSES:
            return True, False
        return False, None

    def list_workspace(self, workspace_id, principal_id, policy, *, now, limit=100):
        """Return bounded workspace candidates and fail-closed assessments.

        `limit` is applied independently to original assets and render
        artifacts (maximum 400 combined). Caller authorization is checked before
        any inventory query. The evaluator is passed only explicit state
        collected from the immutable records; unavailable hold, storage,
        integrity and backup providers are represented as unknown/false.
        """
        if not isinstance(workspace_id, str) or not workspace_id:
            raise ValueError("workspace_id is required")
        if not isinstance(principal_id, str) or not principal_id:
            raise ValueError("principal_id is required")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        self.workspaces.require_membership(workspace_id, principal_id)

        try:
            with self.snapshots._db() as db:
                _query_only(db)
                snapshot_rows = db.execute("""
                    SELECT s.id,s.render_job_id,s.payload_json,j.status AS job_status,
                           r.decision AS review_status
                    FROM timeline_edl_snapshots s
                    LEFT JOIN pipeline_jobs j
                      ON j.id=s.render_job_id AND j.workspace_id=s.workspace_id
                    LEFT JOIN timeline_render_reviews r
                      ON r.snapshot_id=s.id AND r.workspace_id=s.workspace_id
                    WHERE s.workspace_id=?
                    ORDER BY s.created_at ASC,s.id ASC LIMIT ?
                """, (workspace_id, limit * 10 + 1)).fetchall()
        except Exception as exc:
            raise RetentionInventoryError("snapshot reference inventory failed") from exc

        asset_references = {}
        snapshot_truncated = len(snapshot_rows) > limit * 10
        snapshot_inventory_complete = not snapshot_truncated
        snapshot_rows = snapshot_rows[:limit * 10]
        for row in snapshot_rows:
            job_known, job_active = self._job_reference_state(
                row["job_status"], row["review_status"]
            )
            if not job_known:
                snapshot_inventory_complete = False
            try:
                payload = json.loads(row["payload_json"])
                if not isinstance(payload, dict):
                    raise ValueError("invalid snapshot payload")
                clips = payload.get("clips")
                audio_tracks = payload.get("audio_tracks", [])
                if not isinstance(clips, list) or not isinstance(audio_tracks, list):
                    raise ValueError("invalid snapshot asset lists")
                referenced = []
                for clip in clips:
                    if not isinstance(clip, dict):
                        raise ValueError("invalid clip record")
                    clip_type = clip.get("type")
                    if clip_type == "video":
                        asset_id = clip.get("asset_id")
                        if not isinstance(asset_id, str) or not asset_id:
                            raise ValueError("invalid video asset reference")
                        referenced.append(asset_id)
                    elif clip_type != "title":
                        raise ValueError("invalid clip type")
                for track in audio_tracks:
                    if not isinstance(track, dict):
                        raise ValueError("invalid audio track record")
                    asset_id = track.get("asset_id")
                    if not isinstance(asset_id, str) or not asset_id:
                        raise ValueError("invalid audio asset reference")
                    referenced.append(asset_id)
            except (TypeError, ValueError, json.JSONDecodeError):
                snapshot_inventory_complete = False
                continue
            for asset_id in referenced:
                state = asset_references.setdefault(asset_id, {"snapshots": 0, "active": 0})
                state["snapshots"] += 1
                if job_active:
                    state["active"] += 1

        candidates = []
        try:
            with self.assets.db() as db:
                _query_only(db)
                rows = db.execute("""
                    SELECT id,status,scan_status,created_at,retention_until,byte_size
                    FROM workspace_media_assets
                    WHERE workspace_id=?
                    ORDER BY created_at ASC,id ASC LIMIT ?
                """, (workspace_id, limit + 1)).fetchall()
            assets_truncated = len(rows) > limit
            rows = rows[:limit]
            for row in rows:
                refs = asset_references.get(row["id"], {"snapshots": 0, "active": 0})
                candidate = {
                    "id": row["id"],
                    "data_class": "workspace_asset",
                    "created_at": row["created_at"],
                    "asset_status": row["status"],
                    "scan_status": row["scan_status"],
                    "reference_check_complete": snapshot_inventory_complete,
                    "active_reference_count": refs["active"] if snapshot_inventory_complete else None,
                    "snapshot_reference_count": refs["snapshots"] if snapshot_inventory_complete else None,
                    "legal_hold": None,
                    "integrity_verified": False,
                    "storage_state_known": False,
                    "backup_state_known": False,
                }
                evaluation = evaluate_retention_candidate(candidate, policy, now=now)
                candidates.append({
                    "candidate": candidate,
                    "retention_until_metadata": row["retention_until"],
                    "byte_size": row["byte_size"],
                    "evaluation": evaluation,
                })
        except Exception as exc:
            if isinstance(exc, RetentionInventoryError):
                raise
            raise RetentionInventoryError("workspace asset inventory failed") from exc

        try:
            with self.artifacts.queue.db() as db:
                _query_only(db)
                rows = db.execute("""
                    SELECT a.artifact_id,a.job_id,a.snapshot_id,a.created_at,a.byte_size,
                           j.status AS job_status,r.decision AS review_status
                    FROM render_artifacts a
                    LEFT JOIN pipeline_jobs j
                      ON j.id=a.job_id AND j.workspace_id=a.workspace_id
                    LEFT JOIN timeline_render_reviews r
                      ON r.snapshot_id=a.snapshot_id AND r.workspace_id=a.workspace_id
                    WHERE a.workspace_id=?
                    ORDER BY a.created_at ASC,a.artifact_id ASC LIMIT ?
                """, (workspace_id, limit + 1)).fetchall()
            artifacts_truncated = len(rows) > limit
            rows = rows[:limit]
            for row in rows:
                job_known, job_active = self._job_reference_state(
                    row["job_status"], row["review_status"]
                )
                review_status = row["review_status"] or "pending"
                candidate = {
                    "id": row["artifact_id"],
                    "data_class": "render_artifact",
                    "created_at": row["created_at"],
                    "review_status": review_status,
                    "reference_check_complete": job_known,
                    "active_reference_count": 1 if job_active else 0 if job_known else None,
                    # The immutable EDL snapshot remains linked to the artifact's render job.
                    "snapshot_reference_count": 1,
                    "legal_hold": None,
                    "integrity_verified": False,
                    "storage_state_known": False,
                    "backup_state_known": False,
                }
                evaluation = evaluate_retention_candidate(candidate, policy, now=now)
                candidates.append({
                    "candidate": candidate,
                    "job_status": row["job_status"],
                    "byte_size": row["byte_size"],
                    "evaluation": evaluation,
                })
        except Exception as exc:
            if isinstance(exc, RetentionInventoryError):
                raise
            raise RetentionInventoryError("render artifact inventory failed") from exc

        reason_counts = {}
        eligible_count = 0
        for item in candidates:
            result = item["evaluation"]
            if result["eligible_for_review"]:
                eligible_count += 1
            for reason in result["reason_codes"]:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
        return {
            "workspace_id": workspace_id,
            "candidate_count": len(candidates),
            "eligible_for_review_count": eligible_count,
            "blocked_count": len(candidates) - eligible_count,
            "reason_counts": dict(sorted(reason_counts.items())),
            "candidates": candidates,
            "truncated": assets_truncated or artifacts_truncated or snapshot_truncated,
            "snapshot_reference_inventory_complete": snapshot_inventory_complete,
            "read_only": True,
            "destructive_action_performed": False,
        }


from artifact_retention import evaluate_retention_candidate

"""TikTok Content Posting API private-only publisher.

This adapter always requests SELF_ONLY visibility. It requires a fresh human
approval plus a separate explicit operator consent to send the video to TikTok.
It never attempts public posting or automatically retries uncertain uploads.
"""
import json
import os
import sqlite3
import threading
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from policy_engine import POLICY_VERSION
from tiktok_disclosure import build_tiktok_disclosure, TikTokDisclosureError


API_ROOT = "https://open.tiktokapis.com"
CHUNK_SIZE = 64 * 1024 * 1024
MAX_VIDEO_BYTES = 4 * 1024 * 1024 * 1024


class TikTokPublishError(RuntimeError):
    pass


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Signed TikTok upload URLs must never redirect media to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _now():
    return datetime.now(timezone.utc).isoformat()


class TikTokPublishStore:
    def __init__(self, db_path="data/nexus.sqlite3"):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS tiktok_publications(
              job_id TEXT PRIMARY KEY, publish_id TEXT, status TEXT NOT NULL,
              privacy_level TEXT NOT NULL DEFAULT 'SELF_ONLY',
              title TEXT NOT NULL, is_aigc INTEGER NOT NULL,
              creator_username TEXT, creator_nickname TEXT,
              video_id TEXT, fail_reason TEXT, error TEXT,
              brand_content_toggle INTEGER NOT NULL DEFAULT 0,
              brand_organic_toggle INTEGER NOT NULL DEFAULT 0,
              operator_id TEXT NOT NULL, consented_at TEXT NOT NULL,
              updated_at TEXT NOT NULL, attempt_id TEXT,
              policy_version TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tiktok_publication_events(
              id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
              attempt_id TEXT, event_type TEXT NOT NULL, outcome TEXT,
              publish_id TEXT, video_id TEXT, operator_id TEXT NOT NULL,
              note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
              policy_version TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_tiktok_publication_events_job
              ON tiktok_publication_events(job_id,id);
            CREATE TRIGGER IF NOT EXISTS tiktok_publication_events_no_update
              BEFORE UPDATE ON tiktok_publication_events
              BEGIN SELECT RAISE(ABORT,'TikTok publication audit events are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS tiktok_publication_events_no_delete
              BEFORE DELETE ON tiktok_publication_events
              BEGIN SELECT RAISE(ABORT,'TikTok publication audit events are immutable'); END;
            """)

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.db_path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=30000")
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def begin(self, job_id, title, is_aigc, operator_id, attempt_id, brand_content_toggle, brand_organic_toggle):
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT * FROM tiktok_publications WHERE job_id=?", (job_id,)
            ).fetchone()
            if row and row["status"] in (
                "initializing", "uploading", "reconciliation_required",
                "processing", "send_to_inbox", "publish_complete"
            ):
                if row["status"] == "publish_complete":
                    return dict(row)
                raise TikTokPublishError(
                    "A previous TikTok publish attempt is unresolved or already active; "
                    "refresh its status before any new attempt"
                )
            c.execute("""
              INSERT INTO tiktok_publications
                (job_id,status,privacy_level,title,is_aigc,brand_content_toggle,
                 brand_organic_toggle,operator_id,consented_at,updated_at,attempt_id,policy_version)
              VALUES(?,'initializing','SELF_ONLY',?,?,?,?,?,?,?,?,?)
              ON CONFLICT(job_id) DO UPDATE SET
                publish_id=NULL,status='initializing',privacy_level='SELF_ONLY',
                title=excluded.title,is_aigc=excluded.is_aigc,
                brand_content_toggle=excluded.brand_content_toggle,
                brand_organic_toggle=excluded.brand_organic_toggle,
                creator_username=NULL,creator_nickname=NULL,video_id=NULL,
                fail_reason=NULL,error=NULL,operator_id=excluded.operator_id,
                consented_at=excluded.consented_at,updated_at=excluded.updated_at,
                attempt_id=excluded.attempt_id,policy_version=excluded.policy_version
            """, (job_id, title, int(is_aigc), int(brand_content_toggle),
                  int(brand_organic_toggle), operator_id, _now(), _now(),
                  attempt_id, POLICY_VERSION))
            c.execute("""
              INSERT INTO tiktok_publication_events
                (job_id,attempt_id,event_type,outcome,operator_id,note,
                 created_at,policy_version)
              VALUES(?,?, 'operator_consent_recorded','accepted',?,?,?,?)
            """, (job_id, attempt_id, operator_id,
                  "Explicit consent to send this approved video to TikTok; SELF_ONLY only",
                  _now(), POLICY_VERSION))
        return self.get(job_id)

    def set_initialized(self, job_id, attempt_id, publish_id, creator):
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT attempt_id,status FROM tiktok_publications WHERE job_id=?",
                (job_id,)
            ).fetchone()
            if not row or row["attempt_id"] != attempt_id or row["status"] != "initializing":
                raise TikTokPublishError("TikTok attempt changed during initialization")
            c.execute("""
              UPDATE tiktok_publications SET publish_id=?,status='uploading',
                creator_username=?,creator_nickname=?,updated_at=?
              WHERE job_id=? AND attempt_id=?
            """, (publish_id, creator.get("creator_username"),
                  creator.get("creator_nickname"), _now(), job_id, attempt_id))
            c.execute("""
              INSERT INTO tiktok_publication_events
                (job_id,attempt_id,event_type,outcome,publish_id,operator_id,
                 note,created_at,policy_version)
              SELECT job_id,attempt_id,'publish_initialized','accepted',publish_id,
                     operator_id,'SELF_ONLY Direct Post initialized',?,policy_version
              FROM tiktok_publications WHERE job_id=?
            """, (_now(), job_id))

    def mark_status(self, job_id, attempt_id, status, video_ids=None, fail_reason=None):
        allowed = {
            "PROCESSING_UPLOAD": "processing",
            "PUBLISH_COMPLETE": "publish_complete",
            "SEND_TO_USER_INBOX": "send_to_inbox",
            "FAILED": "failed",
        }
        normalized = allowed.get(status)
        if normalized is None and status in ("PROCESSING_UPLOAD", "PROCESSING_DOWNLOAD"):
            normalized = "processing"
        if normalized is None:
            raise TikTokPublishError("TikTok returned an unsupported publication status")
        video_id = (video_ids or [None])[0]
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT * FROM tiktok_publications WHERE job_id=?", (job_id,)
            ).fetchone()
            if not row or row["attempt_id"] != attempt_id:
                raise TikTokPublishError("TikTok status belongs to an unknown or superseded attempt")
            c.execute("""
              UPDATE tiktok_publications SET status=?,video_id=COALESCE(?,video_id),
                fail_reason=?,updated_at=? WHERE job_id=?
            """, (normalized, video_id, fail_reason, _now(), job_id))
            c.execute("""
              INSERT INTO tiktok_publication_events
                (job_id,attempt_id,event_type,outcome,publish_id,video_id,
                 operator_id,note,created_at,policy_version)
              VALUES(?,?,?,?,?,?,?,?,?,?)
            """, (job_id, attempt_id, "status_refreshed", status,
                  row["publish_id"], video_id, row["operator_id"],
                  fail_reason or "", _now(), row["policy_version"]))
        return self.get(job_id)

    def mark_uncertain(self, job_id, attempt_id, message):
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT * FROM tiktok_publications WHERE job_id=?", (job_id,)
            ).fetchone()
            if row and row["attempt_id"] == attempt_id:
                c.execute("""
                  UPDATE tiktok_publications SET status='reconciliation_required',
                    error=?,updated_at=? WHERE job_id=?
                """, (message[:1000], _now(), job_id))
                c.execute("""
                  INSERT INTO tiktok_publication_events
                    (job_id,attempt_id,event_type,outcome,publish_id,operator_id,
                     note,created_at,policy_version)
                  VALUES(?,?,'remote_outcome_uncertain','unknown',?,?,?,?,?)
                """, (job_id, attempt_id, row["publish_id"], row["operator_id"],
                      message[:1000], _now(), row["policy_version"]))

    def mark_failed_before_remote(self, job_id, attempt_id, message):
        with self.db() as c:
            c.execute("""
              UPDATE tiktok_publications SET status='failed',error=?,updated_at=?
              WHERE job_id=? AND attempt_id=? AND status='initializing'
            """, (message[:1000], _now(), job_id, attempt_id))

    def due_status_job_ids(self, limit=5, min_age_seconds=60):
        cutoff = datetime.now(timezone.utc).timestamp() - max(0, int(min_age_seconds))
        cutoff_iso = datetime.fromtimestamp(cutoff, timezone.utc).isoformat()
        with self.db() as c:
            rows = c.execute("""
              SELECT job_id FROM tiktok_publications
              WHERE publish_id IS NOT NULL
                AND status IN ('uploading','processing','reconciliation_required')
                AND updated_at<=?
              ORDER BY updated_at ASC LIMIT ?
            """, (cutoff_iso, max(1, min(int(limit), 20)))).fetchall()
            return [row["job_id"] for row in rows]

    def record_status_poll_error(self, job_id, attempt_id, message):
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT * FROM tiktok_publications WHERE job_id=?", (job_id,)
            ).fetchone()
            if not row or row["attempt_id"] != attempt_id:
                return False
            stamp = _now()
            c.execute(
                "UPDATE tiktok_publications SET updated_at=? WHERE job_id=?",
                (stamp, job_id),
            )
            c.execute("""
              INSERT INTO tiktok_publication_events
                (job_id,attempt_id,event_type,outcome,publish_id,operator_id,
                 note,created_at,policy_version)
              VALUES(?,?,'status_poll_failed','retry_scheduled',?,?,?,?,?)
            """, (job_id, attempt_id, row["publish_id"], row["operator_id"],
                  message[:1000], stamp, row["policy_version"]))
            return True

    def get(self, job_id):
        with self.db() as c:
            row = c.execute(
                "SELECT * FROM tiktok_publications WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["is_aigc"] = bool(result["is_aigc"])
            result["events"] = [dict(x) for x in c.execute(
                "SELECT * FROM tiktok_publication_events WHERE job_id=? ORDER BY id",
                (job_id,)
            ).fetchall()]
            return result


class TikTokPublisher:
    def __init__(self, store, access_token=None, transport=None, token_provider=None):
        self.store = store
        self.access_token = access_token
        self.transport = transport or self._request
        self.token_provider = token_provider

    @staticmethod
    def _request(url, headers, body, timeout, method="POST"):
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            opener = urllib.request.build_opener(_NoRedirectHandler())
            with opener.open(req, timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(2000)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise TikTokPublishError("TikTok network request failed: " + type(exc).__name__) from exc

    def _token(self):
        token = self.access_token or os.getenv("TIKTOK_ACCESS_TOKEN")
        if not token and self.token_provider:
            try:
                token = self.token_provider()
            except Exception as exc:
                raise TikTokPublishError(
                    "TikTok OAuth token is unavailable: " + type(exc).__name__
                ) from exc
        if not token:
            raise TikTokPublishError(
                "TikTok account is not connected; complete OAuth or configure TIKTOK_ACCESS_TOKEN"
            )
        return token

    def creator_info(self):
        response = self._call(
            API_ROOT + "/v2/post/publish/creator_info/query/"
        )
        data = response.get("data") or {}
        options = data.get("privacy_level_options")
        if not isinstance(options, list) or not options:
            raise TikTokPublishError("TikTok creator privacy options are unavailable")
        return {
            "creator_username": data.get("creator_username"),
            "creator_nickname": data.get("creator_nickname"),
            "privacy_level_options": options,
            "comment_disabled": data.get("comment_disabled"),
            "duet_disabled": data.get("duet_disabled"),
            "stitch_disabled": data.get("stitch_disabled"),
            "max_video_post_duration_sec": data.get("max_video_post_duration_sec"),
            "product_privacy_mode": "SELF_ONLY",
            "public_publishing_enabled": False,
        }

    def _call(self, url, payload=None, method="POST", binary=False, extra_headers=None, timeout=90):
        body = payload if binary else json.dumps(payload or {}).encode("utf-8")
        headers = {"Accept": "application/json"}
        if not binary:
            headers["Authorization"] = "Bearer " + self._token()
            headers["Content-Type"] = "application/json; charset=UTF-8"
        if extra_headers:
            headers.update(extra_headers)
        status, raw = self.transport(url, headers, body, timeout, method)
        try:
            data = json.loads(raw.decode("utf-8")) if not binary else {}
        except (ValueError, UnicodeDecodeError) as exc:
            raise TikTokPublishError("TikTok returned an invalid response") from exc
        if not binary and not isinstance(data, dict):
            raise TikTokPublishError("TikTok returned an unexpected response shape")
        error = data.get("error") if isinstance(data, dict) else None
        if isinstance(error, dict):
            error_code = error.get("code")
        elif isinstance(error, str):
            error_code = error.strip() or None
        else:
            error_code = None
        if status < 200 or status >= 300:
            raise TikTokPublishError(
                "TikTok HTTP " + str(status) + ": " +
                str(error_code or "request_failed")
            )
        if binary:
            if status not in (201, 206):
                raise TikTokPublishError("TikTok media chunk returned unexpected HTTP " + str(status))
            return {"http_status": status}
        if error_code not in (None, "ok"):
            raise TikTokPublishError("TikTok API error: " + str(error_code))
        return data

    @staticmethod
    def _media(media_path):
        if not isinstance(media_path, str) or not media_path.strip():
            raise TikTokPublishError("A staged media path is required")
        root = Path(os.getenv("NEXUS_MEDIA_DIR", "data/media")).resolve()
        candidate = Path(media_path)
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, ValueError):
            raise TikTokPublishError(
                "Media path must resolve to an existing file inside NEXUS_MEDIA_DIR"
            )
        if not resolved.is_file():
            raise TikTokPublishError("Staged media path is not a regular file")
        types = {
            ".mp4": "video/mp4", ".mov": "video/quicktime",
            ".webm": "video/webm",
        }
        mime = types.get(resolved.suffix.lower())
        if not mime:
            raise TikTokPublishError("TikTok supports MP4, MOV and WebM media files")
        size = resolved.stat().st_size
        if size <= 0 or size > MAX_VIDEO_BYTES:
            raise TikTokPublishError("TikTok video must be between 1 byte and 4 GB")
        return resolved, mime, size

    @staticmethod
    def _validate_upload_url(upload_url):
        try:
            parsed = urlparse(upload_url or "")
            host = (parsed.hostname or "").lower()
            port = parsed.port
        except (TypeError, ValueError):
            raise TikTokPublishError("TikTok returned an untrusted upload URL")
        if (
            parsed.scheme != "https"
            or host not in ("open-upload.tiktokapis.com", "upload.us.tiktokapis.com")
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 443)
            or parsed.fragment
        ):
            raise TikTokPublishError("TikTok returned an untrusted upload URL")
        return upload_url

    def _upload_chunks(self, upload_url, media_path, mime, size):
        chunk_size = min(CHUNK_SIZE, size)
        if size > CHUNK_SIZE:
            chunk_count = size // chunk_size
        else:
            chunk_count = 1
        if chunk_count < 1 or chunk_count > 1000:
            raise TikTokPublishError("TikTok chunk count is outside the supported range")
        with open(media_path, "rb") as media:
            offset = 0
            for index in range(chunk_count):
                remaining_chunks = chunk_count - index
                remaining_bytes = size - offset
                current_size = (
                    remaining_bytes if remaining_chunks == 1
                    else chunk_size
                )
                chunk = media.read(current_size)
                if len(chunk) != current_size:
                    raise TikTokPublishError("Media file changed during TikTok upload")
                end = offset + current_size - 1
                result = self._call(
                    upload_url, payload=chunk, method="PUT", binary=True,
                    extra_headers={
                        "Content-Type": mime,
                        "Content-Length": str(current_size),
                        "Content-Range": f"bytes {offset}-{end}/{size}",
                    }
                )
                expected = 201 if index == chunk_count - 1 else 206
                if result["http_status"] != expected:
                    raise TikTokPublishError(
                        "TikTok chunk sequence returned an unexpected completion status"
                    )
                offset += current_size
            if offset != size or media.read(1):
                raise TikTokPublishError("TikTok upload byte count did not match the source file")

    def publish_private_approved(
        self, job_id, media_path, review_store, title, operator_id,
        explicit_consent=False, brand_content_toggle=False, brand_organic_toggle=False,
    ):
        if explicit_consent is not True:
            raise TikTokPublishError(
                "Explicit operator consent is required before sending a video to TikTok"
            )
        if not isinstance(operator_id, str) or not operator_id.strip():
            raise TikTokPublishError("operator_id is required")
        if type(brand_content_toggle) is not bool or type(brand_organic_toggle) is not bool:
            raise TikTokPublishError("Explicit brand-content and own-business declarations are required")
        if not isinstance(title, str) or not title.strip() or len(title.encode("utf-16-le")) // 2 > 2200:
            raise TikTokPublishError("TikTok caption must contain 1 to 2200 UTF-16 code units")
        history = review_store.history(job_id)
        if not history or history[-1]["decision"] != "approved":
            raise TikTokPublishError("The latest human review decision must be approved")
        snapshot = history[-1].get("artifact_snapshot") or []
        approved_script = next((
            item for item in snapshot if isinstance(item, dict)
            and item.get("stage") == "script" and item.get("artifact_type") == "text"
        ), None)
        approved_policy = (
            (approved_script.get("metadata") or {}).get("policy_preflight")
            if isinstance(approved_script, dict)
            and isinstance(approved_script.get("metadata"), dict) else None
        )
        if not isinstance(approved_policy, dict) or approved_policy.get("policy_version") != POLICY_VERSION:
            raise TikTokPublishError("Current TikTok policy evidence is missing or stale; return to review")
        if approved_policy.get("status") == "blocked" or approved_policy.get("approval_blockers"):
            raise TikTokPublishError("TikTok policy evidence contains unresolved blockers")
        if "tiktok" not in (approved_policy.get("platforms") or []):
            raise TikTokPublishError("TikTok was not selected in the approved platform policy evidence")
        synthetic_status = approved_policy.get("synthetic_media_status", "unknown")
        try:
            disclosure = build_tiktok_disclosure(synthetic_status)
        except TikTokDisclosureError as exc:
            raise TikTokPublishError(str(exc)) from exc
        if disclosure["is_aigc"] and (
            (approved_policy.get("platform_disclosures") or {}).get(
                "tiktok_ai_generated_content"
            ) is not True
        ):
            raise TikTokPublishError("TikTok AI-generated disclosure acknowledgement is missing")
        if (brand_content_toggle or brand_organic_toggle) and (
            (approved_policy.get("evidence") or {}).get(
                "commercial_relationship_disclosed"
            ) is not True
        ):
            raise TikTokPublishError(
                "Approved commercial relationship disclosure evidence is required for branded content"
            )
        resolved, mime, size = self._media(media_path)
        existing = self.store.get(job_id)
        if existing and existing["status"] == "publish_complete":
            return existing
        attempt_id = uuid.uuid4().hex
        self.store.begin(job_id, title, disclosure["is_aigc"], operator_id.strip(), attempt_id,
                         brand_content_toggle, brand_organic_toggle)
        remote_started = False
        try:
            creator_data = self.creator_info()
            if "SELF_ONLY" not in creator_data["privacy_level_options"]:
                raise TikTokPublishError(
                    "TikTok creator settings do not currently offer SELF_ONLY privacy"
                )
            remote_started = True
            chunk_size = min(CHUNK_SIZE, size)
            chunk_count = max(1, size // chunk_size)
            initialized = self._call(
                API_ROOT + "/v2/post/publish/video/init/",
                payload={
                    "post_info": {
                        "title": title,
                        "privacy_level": "SELF_ONLY",
                        "is_aigc": disclosure["is_aigc"],
                        "brand_content_toggle": brand_content_toggle,
                        "brand_organic_toggle": brand_organic_toggle,
                    },
                    "source_info": {
                        "source": "FILE_UPLOAD",
                        "video_size": size,
                        "chunk_size": chunk_size,
                        "total_chunk_count": chunk_count,
                    },
                },
            )
            data = initialized.get("data") or {}
            publish_id = data.get("publish_id")
            upload_url = self._validate_upload_url(data.get("upload_url"))
            if not publish_id or len(publish_id) > 64 or not upload_url:
                raise TikTokPublishError("TikTok initialization response is incomplete")
            self.store.set_initialized(job_id, attempt_id, publish_id, creator_data)
            self._upload_chunks(upload_url, resolved, mime, size)
            return self.store.get(job_id)
        except Exception as exc:
            detail = type(exc).__name__ + ": " + str(exc)
            if remote_started:
                self.store.mark_uncertain(job_id, attempt_id, detail)
                raise TikTokPublishError(
                    "TikTok request outcome is uncertain. Refresh status before retrying; "
                    "duplicate publishing is blocked."
                ) from exc
            self.store.mark_failed_before_remote(job_id, attempt_id, detail)
            if isinstance(exc, TikTokPublishError):
                raise
            raise TikTokPublishError("TikTok publish failed before initialization") from exc

    def refresh_status(self, job_id):
        record = self.store.get(job_id)
        if record is None:
            raise TikTokPublishError("TikTok publication record not found")
        if not record.get("publish_id"):
            raise TikTokPublishError("TikTok publish ID is not available for status lookup")
        response = self._call(
            API_ROOT + "/v2/post/publish/status/fetch/",
            payload={"publish_id": record["publish_id"]},
            timeout=20,
        )
        data = response.get("data") or {}
        status = data.get("status")
        if not status:
            raise TikTokPublishError("TikTok status response did not include a status")
        return self.store.mark_status(
            job_id, record["attempt_id"], status,
            data.get("publicaly_available_post_id") or [],
            data.get("fail_reason"),
        )

    def refresh_due_statuses(self, limit=5, min_age_seconds=60):
        if not (self.access_token or os.getenv("TIKTOK_ACCESS_TOKEN") or self.token_provider):
            return {"skipped": True, "checked": 0, "updated": 0, "errors": []}
        job_ids = self.store.due_status_job_ids(limit, min_age_seconds)
        updated = []
        errors = []
        for job_id in job_ids:
            record = self.store.get(job_id)
            if record is None:
                continue
            try:
                result = self.refresh_status(job_id)
                updated.append({"job_id": job_id, "status": result["status"]})
            except TikTokPublishError as exc:
                self.store.record_status_poll_error(
                    job_id, record["attempt_id"], str(exc)
                )
                errors.append({"job_id": job_id, "error": str(exc)})
        return {
            "skipped": False, "checked": len(job_ids),
            "updated": len(updated), "results": updated, "errors": errors,
        }

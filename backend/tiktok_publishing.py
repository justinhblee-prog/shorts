"""TikTok Content Posting API Direct Post adapter.

Uploads are private-only, require current human approval and explicit creator
consent, and are never retried automatically after an ambiguous remote outcome.
"""
import json
import os
import sqlite3
import uuid
import threading
import hashlib
import secrets
from urllib.parse import urlencode
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

from policy_engine import POLICY_VERSION


API_BASE = "https://open.tiktokapis.com/v2"
UPLOAD_CHUNK_BYTES = 10 * 1024 * 1024
MAX_VIDEO_BYTES = 256 * 1024 * 1024


class TikTokPublishError(RuntimeError):
    pass


class TikTokPublishUncertainError(TikTokPublishError):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def _safe_api_error(response):
    try:
        body = response.json()
    except Exception:
        body = {}
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        code = error.get("code")
        message = error.get("message")
    else:
        code = error
        message = body.get("error_description") if isinstance(body, dict) else None
    log_id = body.get("log_id") if isinstance(body, dict) else None
    suffix = f" · log_id={str(log_id)[:80]}" if log_id else ""
    return f"TikTok API error ({code or response.status_code}): {str(message or 'request failed')[:500]}{suffix}"


class TikTokOAuthError(TikTokPublishError):
    pass


class TikTokOAuthStore:
    """Single-active-creator OAuth store with Fernet-encrypted tokens at rest."""

    def __init__(self, db_path="data/nexus.sqlite3", session=None):
        self.db_path = str(db_path)
        self.session = session or requests.Session()
        self._refresh_lock = threading.Lock()
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as connection:
            connection.executescript("""
            CREATE TABLE IF NOT EXISTS tiktok_oauth_states(
              state_hash TEXT PRIMARY KEY, operator_id TEXT NOT NULL,
              expires_at REAL NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tiktok_oauth_tokens(
              id INTEGER PRIMARY KEY CHECK(id=1), open_id TEXT NOT NULL,
              display_name TEXT, access_token_cipher TEXT NOT NULL,
              refresh_token_cipher TEXT NOT NULL, scopes TEXT NOT NULL,
              access_expires_at REAL NOT NULL, refresh_expires_at REAL NOT NULL,
              updated_at TEXT NOT NULL
            );
            """)

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _config():
        values = {
            "client_key": os.getenv("TIKTOK_CLIENT_KEY", "").strip(),
            "client_secret": os.getenv("TIKTOK_CLIENT_SECRET", "").strip(),
            "redirect_uri": os.getenv("TIKTOK_REDIRECT_URI", "").strip(),
            "encryption_key": os.getenv("TIKTOK_TOKEN_ENCRYPTION_KEY", "").strip(),
        }
        missing = [key for key, value in values.items() if not value]
        if missing:
            raise TikTokOAuthError("Missing TikTok OAuth configuration: " + ", ".join(missing))
        return values

    @classmethod
    def _fernet(cls):
        config = cls._config()
        try:
            from cryptography.fernet import Fernet
            return Fernet(config["encryption_key"].encode("ascii"))
        except Exception as exc:
            raise TikTokOAuthError("TIKTOK_TOKEN_ENCRYPTION_KEY must be a valid Fernet key") from exc

    def create_authorization(self, operator_id):
        operator_id = str(operator_id or "").strip()
        if not operator_id or len(operator_id) > 128:
            raise TikTokOAuthError("A valid operator ID is required")
        config = self._config()
        state = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc).timestamp()
        with self.db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM tiktok_oauth_states WHERE expires_at<=?", (now,))
            connection.execute(
                "INSERT INTO tiktok_oauth_states(state_hash,operator_id,expires_at,created_at) VALUES(?,?,?,?)",
                (hashlib.sha256(state.encode()).hexdigest(), operator_id, now + 600, _now()),
            )
        params = {
            "client_key": config["client_key"],
            "response_type": "code",
            "scope": "user.info.basic,video.publish",
            "redirect_uri": config["redirect_uri"],
            "state": state,
        }
        return {
            "authorization_url": "https://www.tiktok.com/v2/auth/authorize/?" + urlencode(params),
            "state_expires_in_seconds": 600,
            "scopes": ["user.info.basic", "video.publish"],
        }

    def _consume_state(self, state):
        if not isinstance(state, str) or len(state) < 32 or len(state) > 256:
            raise TikTokOAuthError("OAuth state is invalid")
        digest = hashlib.sha256(state.encode()).hexdigest()
        now = datetime.now(timezone.utc).timestamp()
        with self.db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM tiktok_oauth_states WHERE state_hash=?", (digest,)
            ).fetchone()
            connection.execute("DELETE FROM tiktok_oauth_states WHERE state_hash=?", (digest,))
            if row is None or float(row["expires_at"]) <= now:
                raise TikTokOAuthError("OAuth state is expired or has already been used")
            return row["operator_id"]

    def _token_request(self, payload):
        config = self._config()
        body = {
            "client_key": config["client_key"],
            "client_secret": config["client_secret"],
            **payload,
        }
        try:
            response = self.session.post(
                "https://open.tiktokapis.com/v2/oauth/token/",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data=body, timeout=(10, 30),
            )
        except requests.RequestException as exc:
            raise TikTokOAuthError("TikTok OAuth network request failed: " + type(exc).__name__) from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise TikTokOAuthError(_safe_api_error(response))
        try:
            result = response.json()
        except ValueError as exc:
            raise TikTokOAuthError("TikTok OAuth returned invalid JSON") from exc
        error = result.get("error") if isinstance(result, dict) else None
        if isinstance(error, dict):
            error_code = error.get("code")
            error_message = error.get("message")
        else:
            error_code = error
            error_message = result.get("error_description") if isinstance(result, dict) else None
        if error_code not in (None, "", "ok"):
            log_id = result.get("log_id") if isinstance(result, dict) else None
            suffix = f" · log_id={str(log_id)[:80]}" if log_id else ""
            raise TikTokOAuthError(
                f"TikTok OAuth error ({error_code}): {str(error_message or '')[:500]}{suffix}"
            )
        data = result.get("data") if isinstance(result, dict) else None
        if not isinstance(data, dict):
            data = result
        return data

    def _save_tokens(self, data):
        access = data.get("access_token")
        refresh = data.get("refresh_token")
        open_id = data.get("open_id")
        if not all(isinstance(value, str) and value.strip()
                   for value in (access, refresh, open_id)):
            raise TikTokOAuthError("TikTok OAuth response is missing access, refresh or open_id")
        try:
            access_ttl = int(data["expires_in"])
            refresh_ttl = int(data["refresh_expires_in"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TikTokOAuthError("TikTok OAuth expiry fields are invalid") from exc
        if access_ttl <= 0 or refresh_ttl <= 0:
            raise TikTokOAuthError("TikTok OAuth tokens are already expired")
        cipher = self._fernet()
        access_cipher = cipher.encrypt(access.encode()).decode("ascii")
        refresh_cipher = cipher.encrypt(refresh.encode()).decode("ascii")
        now = datetime.now(timezone.utc).timestamp()
        scopes = data.get("scope") or ""
        scope_set = {scope.strip() for scope in scopes.split(",") if scope.strip()}
        if "video.publish" not in scope_set:
            raise TikTokOAuthError("TikTok account did not grant the required video.publish scope")
        with self.db() as connection:
            connection.execute("""
              INSERT INTO tiktok_oauth_tokens
                (id,open_id,display_name,access_token_cipher,refresh_token_cipher,
                 scopes,access_expires_at,refresh_expires_at,updated_at)
              VALUES(1,?,?,?,?,?,?,?,?)
              ON CONFLICT(id) DO UPDATE SET open_id=excluded.open_id,
                display_name=excluded.display_name,
                access_token_cipher=excluded.access_token_cipher,
                refresh_token_cipher=excluded.refresh_token_cipher,
                scopes=excluded.scopes,access_expires_at=excluded.access_expires_at,
                refresh_expires_at=excluded.refresh_expires_at,updated_at=excluded.updated_at
            """, (open_id, data.get("display_name"), access_cipher, refresh_cipher,
                  scopes, now + access_ttl, now + refresh_ttl, _now()))
        return self.status()

    def connect(self, code, state):
        if not isinstance(code, str) or not code.strip() or len(code) > 2048:
            raise TikTokOAuthError("OAuth authorization code is invalid")
        self._consume_state(state)
        config = self._config()
        data = self._token_request({
            "code": code.strip(), "grant_type": "authorization_code",
            "redirect_uri": config["redirect_uri"],
        })
        return self._save_tokens(data)

    def _refresh(self):
        with self._refresh_lock:
            with self.db() as connection:
                row = connection.execute(
                    "SELECT * FROM tiktok_oauth_tokens WHERE id=1"
                ).fetchone()
            if row is None:
                raise TikTokOAuthError("TikTok creator account is not connected")
            now = datetime.now(timezone.utc).timestamp()
            if float(row["access_expires_at"]) > now + 300:
                return None
            if float(row["refresh_expires_at"]) <= now:
                raise TikTokOAuthError("TikTok refresh token expired; reconnect the creator account")
            cipher = self._fernet()
            try:
                refresh = cipher.decrypt(row["refresh_token_cipher"].encode()).decode()
            except Exception as exc:
                raise TikTokOAuthError("Stored TikTok refresh token cannot be decrypted") from exc
            data = self._token_request({"grant_type": "refresh_token", "refresh_token": refresh})
            data.setdefault("open_id", row["open_id"])
            if "refresh_expires_in" not in data:
                data["refresh_expires_in"] = max(
                    1, int(float(row["refresh_expires_at"]) - now)
                )
            if "scope" not in data:
                data["scope"] = row["scopes"]
            self._save_tokens(data)
            return True

    def get_access_token(self):
        with self.db() as connection:
            row = connection.execute(
                "SELECT * FROM tiktok_oauth_tokens WHERE id=1"
            ).fetchone()
        if row is None:
            fallback = os.getenv("TIKTOK_ACCESS_TOKEN", "").strip()
            if fallback:
                return fallback
            raise TikTokOAuthError("TikTok creator account is not connected")
        now = datetime.now(timezone.utc).timestamp()
        if float(row["access_expires_at"]) <= now + 300:
            self._refresh()
            with self.db() as connection:
                row = connection.execute(
                    "SELECT * FROM tiktok_oauth_tokens WHERE id=1"
                ).fetchone()
        try:
            return self._fernet().decrypt(row["access_token_cipher"].encode()).decode()
        except Exception as exc:
            raise TikTokOAuthError("Stored TikTok access token cannot be decrypted") from exc

    def status(self):
        with self.db() as connection:
            row = connection.execute(
                "SELECT * FROM tiktok_oauth_tokens WHERE id=1"
            ).fetchone()
        if row is None:
            return {"connected": False}
        now = datetime.now(timezone.utc).timestamp()
        return {
            "connected": True, "open_id": row["open_id"],
            "display_name": row["display_name"], "scopes": [scope.strip() for scope in row["scopes"].split(",") if scope.strip()],
            "access_token_expires_in": max(0, int(row["access_expires_at"] - now)),
            "refresh_token_expires_in": max(0, int(row["refresh_expires_at"] - now)),
            "updated_at": row["updated_at"],
        }


class TikTokPublishStore:
    def __init__(self, db_path="data/nexus.sqlite3"):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as connection:
            connection.executescript("""
            CREATE TABLE IF NOT EXISTS tiktok_publications(
              job_id TEXT PRIMARY KEY, publish_id TEXT, status TEXT NOT NULL,
              privacy_level TEXT NOT NULL DEFAULT 'SELF_ONLY',
              title TEXT NOT NULL, is_aigc INTEGER NOT NULL,
              error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              attempt_id TEXT, policy_version TEXT, remote_status TEXT
            );
            CREATE TABLE IF NOT EXISTS tiktok_publication_events(
              id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
              attempt_id TEXT, event_type TEXT NOT NULL, outcome TEXT,
              operator_id TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL, policy_version TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_tiktok_events_job
              ON tiktok_publication_events(job_id,id);
            CREATE TRIGGER IF NOT EXISTS tiktok_events_no_update
              BEFORE UPDATE ON tiktok_publication_events
              BEGIN SELECT RAISE(ABORT,'TikTok publication events are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS tiktok_events_no_delete
              BEFORE DELETE ON tiktok_publication_events
              BEGIN SELECT RAISE(ABORT,'TikTok publication events are immutable'); END;
            """)

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def begin(self, job_id, title, is_aigc, policy_version, operator_id):
        with self.db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM tiktok_publications WHERE job_id=?", (job_id,)
            ).fetchone()
            if row and row["status"] in ("published", "processing", "uploading",
                                         "reconciliation_required"):
                raise TikTokPublishError(
                    "TikTok publication already exists or has an uncertain outcome; "
                    "automatic retry is blocked to prevent duplicate posts"
                )
            attempt_id = uuid.uuid4().hex
            now = _now()
            connection.execute("""
              INSERT INTO tiktok_publications
                (job_id,status,privacy_level,title,is_aigc,created_at,updated_at,
                 attempt_id,policy_version)
              VALUES(?,'initializing','SELF_ONLY',?,?,?,?,?,?)
              ON CONFLICT(job_id) DO UPDATE SET status='initializing',
                privacy_level='SELF_ONLY',title=excluded.title,
                is_aigc=excluded.is_aigc,error=NULL,updated_at=excluded.updated_at,
                attempt_id=excluded.attempt_id,policy_version=excluded.policy_version,
                publish_id=NULL,remote_status=NULL
            """, (job_id, title, int(is_aigc), now, now, attempt_id, policy_version))
            connection.execute("""
              INSERT INTO tiktok_publication_events
                (job_id,attempt_id,event_type,outcome,operator_id,note,created_at,policy_version)
              VALUES(?,?,'publish_attempt_started','started',?,
                     'Creator consent and human approval verified; private visibility selected',?,?)
            """, (job_id, attempt_id, operator_id, now, policy_version))
            return dict(connection.execute(
                "SELECT * FROM tiktok_publications WHERE job_id=?", (job_id,)
            ).fetchone())

    def update(self, job_id, attempt_id, status, publish_id=None, remote_status=None,
               error=None, event_type=None, note=""):
        allowed = {"initializing", "uploading", "processing", "published",
                   "failed", "reconciliation_required"}
        if status not in allowed:
            raise TikTokPublishError("Unsupported TikTok publication state")
        with self.db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM tiktok_publications WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None or row["attempt_id"] != attempt_id:
                raise TikTokPublishError("TikTok publication attempt changed; operator reconciliation required")
            connection.execute("""
              UPDATE tiktok_publications SET status=?,publish_id=COALESCE(?,publish_id),
                remote_status=COALESCE(?,remote_status),error=?,updated_at=?
              WHERE job_id=? AND attempt_id=?
            """, (status, publish_id, remote_status, error, _now(), job_id, attempt_id))
            if event_type:
                connection.execute("""
                  INSERT INTO tiktok_publication_events
                    (job_id,attempt_id,event_type,outcome,operator_id,note,created_at,policy_version)
                  VALUES(?,?,?,?,'system:tiktok_worker',?,?,?)
                """, (job_id, attempt_id, event_type, status, str(note)[:2000],
                      _now(), row["policy_version"]))

    def reconcile(self, job_id, outcome, operator_id, note, publish_id=None):
        operator_id = str(operator_id or "").strip()
        note = str(note or "").strip()
        if not operator_id or len(operator_id) > 128 or not note or len(note) > 2000:
            raise TikTokPublishError("A valid operator ID and reconciliation note are required")
        if outcome not in ("published", "not_published"):
            raise TikTokPublishError("Outcome must be published or not_published")
        if outcome == "published" and (not isinstance(publish_id, str) or not publish_id.strip()):
            raise TikTokPublishError("A confirmed TikTok publish ID is required")
        with self.db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM tiktok_publications WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None or row["status"] != "reconciliation_required":
                raise TikTokPublishError("Only uncertain TikTok publications can be reconciled")
            if outcome == "published":
                status, video_id = "published", publish_id.strip()
            else:
                status, video_id = "failed", None
            now = _now()
            connection.execute("""
              UPDATE tiktok_publications SET status=?,publish_id=COALESCE(?,publish_id),
                error=NULL,updated_at=? WHERE job_id=?
            """, (status, video_id, now, job_id))
            connection.execute("""
              INSERT INTO tiktok_publication_events
                (job_id,attempt_id,event_type,outcome,operator_id,note,created_at,policy_version)
              VALUES(?,?, 'operator_reconciled', ?,?,?,?,?)
            """, (job_id, row["attempt_id"], status, operator_id, note, now,
                  row["policy_version"]))
        return self.get(job_id)

    def get(self, job_id):
        with self.db() as connection:
            row = connection.execute(
                "SELECT * FROM tiktok_publications WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["is_aigc"] = bool(result["is_aigc"])
            result["events"] = [dict(item) for item in connection.execute(
                "SELECT * FROM tiktok_publication_events WHERE job_id=? ORDER BY id",
                (job_id,)
            ).fetchall()]
            return result


class TikTokPublisher:
    def __init__(self, store, session=None, token_provider=None):
        self.store = store
        self.session = session or requests.Session()
        self.token_provider = token_provider

    def _token(self):
        token = self.token_provider() if self.token_provider else os.getenv("TIKTOK_ACCESS_TOKEN", "").strip()
        if not token:
            raise TikTokPublishError("TIKTOK_ACCESS_TOKEN is required")
        return token

    def _api_post(self, path, payload):
        try:
            response = self.session.post(
                API_BASE + path,
                headers={"Authorization": "Bearer " + self._token(),
                         "Content-Type": "application/json; charset=UTF-8"},
                json=payload, timeout=(10, 60),
            )
        except requests.RequestException as exc:
            raise TikTokPublishUncertainError("TikTok API network outcome is uncertain: " + type(exc).__name__) from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise TikTokPublishError(_safe_api_error(response))
        try:
            body = response.json()
        except ValueError as exc:
            raise TikTokPublishError("TikTok API returned invalid JSON") from exc
        error = body.get("error", {}) if isinstance(body, dict) else {}
        if error.get("code") != "ok":
            raise TikTokPublishError(
                f"TikTok API error ({error.get('code')}): {str(error.get('message') or '')[:500]}"
            )
        return body

    def creator_info(self):
        return self._api_post("/post/publish/creator_info/query/", {})

    @staticmethod
    def _policy_evidence(store, review_store, job_id):
        history = review_store.history(job_id)
        if not history or history[-1].get("decision") != "approved":
            raise TikTokPublishError("The latest human review decision must be approved")
        with store.db() as connection:
            run = connection.execute(
                "SELECT status FROM production_runs WHERE job_id=?", (job_id,)
            ).fetchone()
            artifact = connection.execute("""
              SELECT metadata_json FROM production_artifacts
              WHERE job_id=? AND stage='script' AND artifact_type='text'
              ORDER BY created_at DESC,id DESC LIMIT 1
            """, (job_id,)).fetchone()
            latest = connection.execute("""
              SELECT artifact_snapshot_json FROM review_decisions
              WHERE job_id=? ORDER BY id DESC LIMIT 1
            """, (job_id,)).fetchone()
        if run is None or run["status"] != "approved" or artifact is None or latest is None:
            raise TikTokPublishError("Approved production and current policy evidence are required")
        try:
            metadata = json.loads(artifact["metadata_json"])
            policy = metadata.get("policy_preflight") or {}
            snapshot = json.loads(latest["artifact_snapshot_json"] or "[]")
        except (TypeError, ValueError, AttributeError) as exc:
            raise TikTokPublishError("Saved TikTok policy evidence is invalid") from exc
        approved_script = next((item for item in snapshot
                                if isinstance(item, dict) and item.get("stage") == "script"
                                and item.get("artifact_type") == "text"), None)
        approved_policy = ((approved_script.get("metadata") or {}).get("policy_preflight")
                           if isinstance(approved_script, dict)
                           and isinstance(approved_script.get("metadata"), dict) else None)
        if (not isinstance(policy, dict) or policy.get("policy_version") != POLICY_VERSION
                or not isinstance(approved_policy, dict)
                or approved_policy.get("policy_version") != POLICY_VERSION
                or policy.get("status") == "blocked" or policy.get("approval_blockers")):
            raise TikTokPublishError(
                "TikTok policy evidence is blocked, stale or not included in the latest approval"
            )
        if "tiktok" not in (policy.get("platforms") or []):
            raise TikTokPublishError("TikTok was not included in the approved target platforms")
        classification = policy.get("synthetic_media_status")
        mapping = {
            "none": False, "ai_assisted_nonrealistic": False,
            "ai_generated": True, "realistic_alteration": True,
        }
        if classification not in mapping:
            raise TikTokPublishError("TikTok AI-generated status is unknown; return to policy review")
        is_aigc = mapping[classification]
        disclosures = policy.get("platform_disclosures") or {}
        if is_aigc and disclosures.get("tiktok_ai_generated_content") is not True:
            raise TikTokPublishError("TikTok AI-generated disclosure acknowledgement is missing")
        return policy, is_aigc

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
            raise TikTokPublishError("Media path must be an existing file inside NEXUS_MEDIA_DIR")
        if not resolved.is_file() or resolved.is_symlink():
            raise TikTokPublishError("Staged media must be a regular non-symlink file")
        mime = {".mp4": "video/mp4", ".mov": "video/quicktime",
                ".webm": "video/webm"}.get(resolved.suffix.lower())
        if not mime:
            raise TikTokPublishError("TikTok supports MP4, QuickTime or WebM video files")
        size = resolved.stat().st_size
        if size <= 0 or size > MAX_VIDEO_BYTES:
            raise TikTokPublishError("TikTok video must be between 1 byte and 256 MiB")
        return resolved, mime, size

    @staticmethod
    def _upload_url_allowed(upload_url):
        if not isinstance(upload_url, str) or not upload_url or len(upload_url) > 256:
            raise TikTokPublishError("TikTok returned an invalid or oversized upload URL")
        parsed = urlparse(upload_url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not (host == "tiktokapis.com"
                or host.endswith(".tiktokapis.com")):
            raise TikTokPublishError("TikTok returned an untrusted media upload URL")
        return upload_url

    def publish_approved(self, job_id, media_path, review_store, title,
                         creator_consented, caption_confirmed, operator_id,
                         brand_content_toggle, brand_organic_toggle):
        if creator_consented is not True:
            raise TikTokPublishError("Explicit creator consent to upload is required")
        if not isinstance(brand_content_toggle, bool) or not isinstance(brand_organic_toggle, bool):
            raise TikTokPublishError("Paid partnership and own-brand promotion declarations must be explicit booleans")
        if brand_content_toggle and brand_organic_toggle:
            raise TikTokPublishError("Paid partnership and own-brand promotion declarations cannot both be true")
        if caption_confirmed is not True:
            raise TikTokPublishError("Creator must confirm the editable caption before upload")
        operator_id = str(operator_id or "").strip()
        if not operator_id or len(operator_id) > 128:
            raise TikTokPublishError("A valid operator ID is required")
        if (not isinstance(title, str) or not title.strip()
                or len(title.encode("utf-16-le")) // 2 > 2200):
            raise TikTokPublishError("TikTok caption must contain 1 to 2200 UTF-16 code units")
        resolved, mime, size = self._media(media_path)
        policy, is_aigc = self._policy_evidence(self.store, review_store, job_id)
        attempt = self.store.begin(job_id, title, is_aigc, policy["policy_version"], operator_id)
        remote_started = False
        try:
            creator = self.creator_info().get("data") or {}
            privacy_options = creator.get("privacy_level_options") or []
            if "SELF_ONLY" not in privacy_options:
                raise TikTokPublishError("TikTok creator account does not offer SELF_ONLY privacy")
            chunk_size = size if size < UPLOAD_CHUNK_BYTES else UPLOAD_CHUNK_BYTES
            total_chunks = max(1, size // chunk_size)
            if total_chunks > 1000:
                raise TikTokPublishError("TikTok upload exceeds the 1000-chunk limit")
            try:
                body = self._api_post("/post/publish/video/init/", {
                    "post_info": {
                        "title": title, "privacy_level": "SELF_ONLY",
                        "disable_duet": True, "disable_comment": True, "disable_stitch": True,
                        "brand_content_toggle": brand_content_toggle,
                        "brand_organic_toggle": brand_organic_toggle,
                        "is_aigc": is_aigc,
                    },
                    "source_info": {
                        "source": "FILE_UPLOAD", "video_size": size,
                        "chunk_size": chunk_size, "total_chunk_count": total_chunks,
                    },
                })
            except TikTokPublishUncertainError:
                remote_started = True
                raise
            data = body.get("data") or {}
            publish_id = data.get("publish_id")
            if isinstance(publish_id, str) and publish_id and len(publish_id) <= 64:
                remote_started = True
                self.store.update(job_id, attempt["attempt_id"], "uploading",
                                  publish_id=publish_id, event_type="upload_initialized",
                                  note="Direct Post initialized with SELF_ONLY privacy and is_aigc declaration")
            upload_url = self._upload_url_allowed(data.get("upload_url"))
            if not publish_id or len(publish_id) > 64 or not upload_url:
                raise TikTokPublishError("TikTok did not return a valid publish ID and upload URL")
            with resolved.open("rb") as media:
                offset = 0
                while offset < size:
                    remaining = size - offset
                    # TikTok requires each chunk to be >=5 MiB (except a whole
                    # file below 5 MiB). The final chunk absorbs the remainder.
                    read_size = remaining if (total_chunks == 1 or offset // chunk_size == total_chunks - 1) else chunk_size
                    chunk = media.read(read_size)
                    if not chunk:
                        raise TikTokPublishError("Unexpected end of staged video during upload")
                    end = offset + len(chunk) - 1
                    try:
                        response = self.session.put(
                            upload_url,
                            headers={"Content-Type": mime, "Content-Length": str(len(chunk)),
                                     "Content-Range": f"bytes {offset}-{end}/{size}"},
                            data=chunk, timeout=(10, 180),
                        )
                    except requests.RequestException as exc:
                        raise TikTokPublishError("TikTok media transfer outcome is uncertain: "
                                                 + type(exc).__name__) from exc
                    expected = 201 if end == size - 1 else 206
                    if response.status_code != expected:
                        raise TikTokPublishError(
                            f"TikTok media transfer returned HTTP {response.status_code}; expected {expected}"
                        )
                    offset = end + 1
            self.store.update(job_id, attempt["attempt_id"], "processing",
                              publish_id=publish_id, event_type="media_uploaded",
                              note="All media chunks accepted; awaiting TikTok processing")
            return self.store.get(job_id)
        except Exception as exc:
            detail = type(exc).__name__ + ": " + str(exc)
            if remote_started:
                self.store.update(job_id, attempt["attempt_id"], "reconciliation_required",
                                  error=detail, event_type="publish_outcome_uncertain",
                                  note="Do not retry until the creator's TikTok inbox/profile is checked")
            else:
                self.store.update(job_id, attempt["attempt_id"], "failed",
                                  error=detail, event_type="publish_preflight_failed", note=detail)
            if isinstance(exc, TikTokPublishError):
                raise
            raise TikTokPublishError("TikTok publication failed: " + type(exc).__name__) from exc

    def refresh_status(self, job_id):
        current = self.store.get(job_id)
        if current is None:
            raise TikTokPublishError("TikTok publication record not found")
        if not current.get("publish_id"):
            raise TikTokPublishError("TikTok publish ID is unavailable")
        body = self._api_post("/post/publish/status/fetch/",
                              {"publish_id": current["publish_id"]})
        data = body.get("data") or {}
        remote = data.get("status") or "UNKNOWN"
        mapping = {
            "PUBLISH_COMPLETE": "published",
            "FAILED": "failed",
            "PROCESSING_UPLOAD": "processing",
            "PROCESSING_DOWNLOAD": "processing",
            "SEND_TO_USER_INBOX": "processing",
            "INBOXED": "processing",
            "PUBLISHING": "processing",
        }
        state = mapping.get(remote, "processing")
        self.store.update(job_id, current["attempt_id"], state,
                          remote_status=remote, event_type="status_refreshed",
                          note="TikTok status fetch returned " + str(remote))
        return self.store.get(job_id)

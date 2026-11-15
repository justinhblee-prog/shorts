"""Server-side TikTok Login Kit OAuth and rotated token lifecycle."""
import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
MAX_TIKTOK_OAUTH_RESPONSE_BYTES = 256 * 1024
MAX_TIKTOK_TOKEN_CHARS = 16 * 1024
MAX_TIKTOK_OPEN_ID_CHARS = 256
MAX_TIKTOK_SCOPE_CHARS = 4096
MAX_TIKTOK_ACCESS_TTL_SECONDS = 31_536_000
MAX_TIKTOK_REFRESH_TTL_SECONDS = 315_360_000


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
REVOKE_URL = "https://open.tiktokapis.com/v2/oauth/revoke/"
AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
DEFAULT_SCOPES = "user.info.basic,video.publish,video.list"


def _now():
    return datetime.now(timezone.utc)


def _stamp(value):
    return value.astimezone(timezone.utc).isoformat()


class TikTokOAuthError(RuntimeError):
    pass


class TikTokOAuthStore:
    def __init__(self, db_path="data/nexus.sqlite3"):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS tiktok_oauth_states(
              state_hash TEXT PRIMARY KEY, expires_at TEXT NOT NULL,
              used_at TEXT, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tiktok_oauth_states_expiry
              ON tiktok_oauth_states(expires_at);
            CREATE TABLE IF NOT EXISTS tiktok_oauth_tokens(
              id INTEGER PRIMARY KEY CHECK(id=1), open_id TEXT NOT NULL,
              access_token_encrypted TEXT NOT NULL,
              refresh_token_encrypted TEXT NOT NULL,
              scope TEXT NOT NULL, token_type TEXT NOT NULL,
              access_expires_at TEXT NOT NULL,
              refresh_expires_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tiktok_oauth_refresh_lease(
              id INTEGER PRIMARY KEY CHECK(id=1), owner_id TEXT NOT NULL,
              lease_token TEXT NOT NULL, expires_at TEXT NOT NULL
            );
            """)

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=30000")
        try:
            yield c
            if c.in_transaction:
                c.commit()
        except Exception:
            if c.in_transaction:
                c.rollback()
            raise
        finally:
            c.close()

    def create_state(self, state_hash, ttl_seconds=600):
        now = _now()
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("DELETE FROM tiktok_oauth_states WHERE expires_at<? OR used_at IS NOT NULL",
                      (_stamp(now),))
            c.execute(
                "INSERT INTO tiktok_oauth_states(state_hash,expires_at,created_at) VALUES(?,?,?)",
                (state_hash, _stamp(now + timedelta(seconds=ttl_seconds)), _stamp(now)),
            )

    def consume_state(self, state_hash):
        now = _stamp(_now())
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT * FROM tiktok_oauth_states WHERE state_hash=?", (state_hash,)
            ).fetchone()
            if not row or row["used_at"] or row["expires_at"] <= now:
                raise TikTokOAuthError("TikTok OAuth state is invalid, expired or already used")
            c.execute(
                "UPDATE tiktok_oauth_states SET used_at=? WHERE state_hash=? AND used_at IS NULL",
                (now, state_hash),
            )
            return True

    def save_tokens(self, values):
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("""
              INSERT INTO tiktok_oauth_tokens
                (id,open_id,access_token_encrypted,refresh_token_encrypted,scope,
                 token_type,access_expires_at,refresh_expires_at,updated_at)
              VALUES(1,?,?,?,?,?,?,?,?)
              ON CONFLICT(id) DO UPDATE SET
                open_id=excluded.open_id,
                access_token_encrypted=excluded.access_token_encrypted,
                refresh_token_encrypted=excluded.refresh_token_encrypted,
                scope=excluded.scope,token_type=excluded.token_type,
                access_expires_at=excluded.access_expires_at,
                refresh_expires_at=excluded.refresh_expires_at,
                updated_at=excluded.updated_at
            """, (
                values["open_id"], values["access_token_encrypted"],
                values["refresh_token_encrypted"], values["scope"],
                values["token_type"], values["access_expires_at"],
                values["refresh_expires_at"], _stamp(_now()),
            ))

    def token_record(self):
        with self.db() as c:
            row = c.execute("SELECT * FROM tiktok_oauth_tokens WHERE id=1").fetchone()
            return dict(row) if row else None

    def clear_tokens(self):
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("DELETE FROM tiktok_oauth_tokens WHERE id=1")
            c.execute("DELETE FROM tiktok_oauth_refresh_lease WHERE id=1")

    def status(self):
        row = self.token_record()
        if not row:
            return {"connected": False, "status": "disconnected"}
        now = _stamp(_now())
        return {
            "connected": row["refresh_expires_at"] > now,
            "status": "connected" if row["refresh_expires_at"] > now else "reauthorization_required",
            "open_id": row["open_id"],
            "scope": row["scope"],
            "access_expires_at": row["access_expires_at"],
            "refresh_expires_at": row["refresh_expires_at"],
            "updated_at": row["updated_at"],
        }

    def acquire_refresh_lease(self, owner_id, lease_seconds=60):
        now = _now()
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT * FROM tiktok_oauth_refresh_lease WHERE id=1").fetchone()
            if row and row["expires_at"] > _stamp(now) and row["owner_id"] != owner_id:
                return None
            token = str(uuid.uuid4())
            c.execute("""
              INSERT INTO tiktok_oauth_refresh_lease(id,owner_id,lease_token,expires_at)
              VALUES(1,?,?,?)
              ON CONFLICT(id) DO UPDATE SET owner_id=excluded.owner_id,
                lease_token=excluded.lease_token,expires_at=excluded.expires_at
            """, (owner_id, token, _stamp(now + timedelta(seconds=lease_seconds))))
            return token

    def release_refresh_lease(self, owner_id, lease_token):
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            cur = c.execute(
                "DELETE FROM tiktok_oauth_refresh_lease WHERE id=1 AND owner_id=? AND lease_token=?",
                (owner_id, lease_token),
            )
            return bool(cur.rowcount)


class TikTokOAuthManager:
    def __init__(self, store, client_key=None, client_secret=None,
                 redirect_uri=None, encryption_key=None, transport=None):
        self.store = store
        self.client_key = client_key or os.getenv("TIKTOK_CLIENT_KEY")
        self.client_secret = client_secret or os.getenv("TIKTOK_CLIENT_SECRET")
        self.redirect_uri = redirect_uri or os.getenv("TIKTOK_REDIRECT_URI")
        key = encryption_key or os.getenv("TIKTOK_TOKEN_ENCRYPTION_KEY")
        self._cipher_invalid = False
        try:
            self.cipher = Fernet(key.encode() if isinstance(key, str) else key) if key else None
        except (ValueError, TypeError):
            self.cipher = None
            self._cipher_invalid = True
        self.transport = transport or self._request
        self._owner_id = "oauth-" + uuid.uuid4().hex
        self._local_lock = threading.Lock()

    @staticmethod
    def _request(url, headers, body, timeout):
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            opener = urllib.request.build_opener(_NoRedirectHandler())
            with opener.open(req, timeout=timeout) as response:
                raw = response.read(MAX_TIKTOK_OAUTH_RESPONSE_BYTES + 1)
                if len(raw) > MAX_TIKTOK_OAUTH_RESPONSE_BYTES:
                    raise TikTokOAuthError("TikTok OAuth response exceeded the 256 KiB limit")
                return response.status, raw
        except urllib.error.HTTPError as exc:
            # Never follow credential-bearing OAuth redirects. Error bodies are
            # bounded and only safe machine-readable identifiers may be surfaced.
            return exc.code, exc.read(4000)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise TikTokOAuthError("TikTok OAuth network request failed: " + type(exc).__name__) from exc

    def _require_config(self):
        if not self.client_key or not self.client_secret or not self.redirect_uri:
            raise TikTokOAuthError(
                "TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET and TIKTOK_REDIRECT_URI are required"
            )
        parsed = urllib.parse.urlparse(self.redirect_uri)
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise TikTokOAuthError("TikTok web OAuth redirect URI must be an absolute HTTPS URL without query or fragment")
        if self.cipher is None:
            raise TikTokOAuthError(
                "TIKTOK_TOKEN_ENCRYPTION_KEY must be a valid Fernet key for encrypted token storage"
            )

    def start_authorization(self, scopes=DEFAULT_SCOPES):
        self._require_config()
        state = secrets.token_urlsafe(32)
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        self.store.create_state(state_hash)
        query = urllib.parse.urlencode({
            "client_key": self.client_key,
            "response_type": "code",
            "scope": scopes,
            "redirect_uri": self.redirect_uri,
            "state": state,
        })
        return {"authorization_url": AUTHORIZE_URL + "?" + query, "state": state, "expires_in": 600}

    def _post_token(self, payload):
        body = urllib.parse.urlencode(payload).encode("utf-8")
        status, raw = self.transport(
            TOKEN_URL,
            {"Content-Type": "application/x-www-form-urlencoded",
             "Accept": "application/json", "Cache-Control": "no-cache"},
            body, 30,
        )
        if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
            raise TikTokOAuthError("TikTok OAuth returned an invalid HTTP status")
        if not isinstance(raw, (bytes, bytearray)):
            raise TikTokOAuthError("TikTok OAuth response must be binary JSON")
        if len(raw) > MAX_TIKTOK_OAUTH_RESPONSE_BYTES:
            raise TikTokOAuthError("TikTok OAuth response exceeded the 256 KiB limit")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise TikTokOAuthError("TikTok OAuth returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise TikTokOAuthError("TikTok OAuth returned an unexpected response shape")
        if status < 200 or status >= 300 or data.get("error"):
            raw_code = data.get("error")
            code = raw_code if isinstance(raw_code, str) and re.fullmatch(
                r"[A-Za-z0-9_.-]{1,128}", raw_code
            ) else "request_failed"
            log_id = data.get("log_id")
            safe_log_id = (
                log_id if isinstance(log_id, str)
                and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", log_id)
                else None
            )
            raise TikTokOAuthError(
                "TikTok OAuth " + code +
                ((" (log_id " + safe_log_id + ")") if safe_log_id else "")
            )
        return data

    def _save_token_response(self, data):
        if not isinstance(data, dict):
            raise TikTokOAuthError("TikTok OAuth token response has an invalid shape")

        def bounded_opaque_string(name, maximum):
            value = data.get(name)
            if (
                not isinstance(value, str)
                or not value
                or len(value) > maximum
                or value != value.strip()
                or any(ord(char) < 33 or ord(char) > 126 for char in value)
            ):
                raise TikTokOAuthError(
                    "TikTok OAuth token response has an invalid " + name
                )
            return value

        access_token = bounded_opaque_string("access_token", MAX_TIKTOK_TOKEN_CHARS)
        refresh_token = bounded_opaque_string("refresh_token", MAX_TIKTOK_TOKEN_CHARS)
        open_id = bounded_opaque_string("open_id", MAX_TIKTOK_OPEN_ID_CHARS)

        scope = data.get("scope", "")
        if (
            not isinstance(scope, str)
            or len(scope) > MAX_TIKTOK_SCOPE_CHARS
            or any(ord(char) < 32 or ord(char) == 127 for char in scope)
        ):
            raise TikTokOAuthError("TikTok OAuth token response has an invalid scope")

        token_type = data.get("token_type", "Bearer")
        if not isinstance(token_type, str) or token_type.lower() != "bearer":
            raise TikTokOAuthError("TikTok OAuth token response has an unsupported token type")

        def bounded_expiry(name, maximum):
            value = data.get(name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 1
                or value > maximum
            ):
                raise TikTokOAuthError(
                    "TikTok OAuth token response has invalid " + name
                )
            return value

        access_seconds = bounded_expiry(
            "expires_in", MAX_TIKTOK_ACCESS_TTL_SECONDS
        )
        refresh_seconds = bounded_expiry(
            "refresh_expires_in", MAX_TIKTOK_REFRESH_TTL_SECONDS
        )

        now = _now()
        values = {
            "open_id": open_id,
            "access_token_encrypted": self.cipher.encrypt(access_token.encode("ascii")).decode(),
            "refresh_token_encrypted": self.cipher.encrypt(refresh_token.encode("ascii")).decode(),
            "scope": scope,
            "token_type": "Bearer",
            "access_expires_at": _stamp(now + timedelta(seconds=access_seconds)),
            "refresh_expires_at": _stamp(now + timedelta(seconds=refresh_seconds)),
        }
        self.store.save_tokens(values)
        return values

    def exchange_code(self, code, state):
        self._require_config()
        if not isinstance(code, str) or not code.strip():
            raise TikTokOAuthError("TikTok authorization code is required")
        if not isinstance(state, str) or not state:
            raise TikTokOAuthError("TikTok OAuth state is required")
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        self.store.consume_state(state_hash)
        data = self._post_token({
            "client_key": self.client_key,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
        })
        saved = self._save_token_response(data)
        return {
            "connected": True, "open_id": saved["open_id"],
            "scope": saved["scope"], "access_expires_at": saved["access_expires_at"],
            "refresh_expires_at": saved["refresh_expires_at"],
        }

    def get_access_token(self, required_scope="video.publish"):
        if required_scope not in {"video.publish", "video.list"}:
            raise TikTokOAuthError("Unsupported TikTok OAuth scope requirement")
        if self.cipher is None:
            raise TikTokOAuthError("TIKTOK_TOKEN_ENCRYPTION_KEY must be a valid Fernet key")
        with self._local_lock:
            row = self.store.token_record()
            if not row:
                return None
            if required_scope not in {
                scope.strip() for scope in str(row.get("scope") or "").split(",")
            }:
                raise TikTokOAuthError(
                    "TikTok account authorization is missing the required " + required_scope + " scope"
                )
            now = _now()
            access_expiry = datetime.fromisoformat(row["access_expires_at"])
            if access_expiry > now + timedelta(minutes=10):
                try:
                    return self.cipher.decrypt(row["access_token_encrypted"].encode()).decode()
                except InvalidToken as exc:
                    raise TikTokOAuthError("Stored TikTok access token cannot be decrypted") from exc
            refresh_expiry = datetime.fromisoformat(row["refresh_expires_at"])
            if refresh_expiry <= now + timedelta(minutes=1):
                raise TikTokOAuthError("TikTok refresh token expired; reconnect the TikTok account")
            lease = self.store.acquire_refresh_lease(self._owner_id, lease_seconds=60)
            if lease is None:
                # Another API/worker process is refreshing the rotated token.
                for _ in range(20):
                    time.sleep(0.25)
                    row = self.store.token_record()
                    if row and datetime.fromisoformat(row["access_expires_at"]) > _now() + timedelta(minutes=1):
                        if required_scope not in {scope.strip() for scope in str(row.get("scope") or "").split(",")}:
                            raise TikTokOAuthError("TikTok account authorization is missing the required " + required_scope + " scope")
                        try:
                            return self.cipher.decrypt(row["access_token_encrypted"].encode()).decode()
                        except InvalidToken as exc:
                            raise TikTokOAuthError("Stored TikTok access token cannot be decrypted") from exc
                raise TikTokOAuthError("TikTok token refresh is already in progress; retry shortly")
            try:
                if not self.client_key or not self.client_secret:
                    raise TikTokOAuthError("TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET are required to refresh tokens")
                # Re-read after taking the distributed lease; another process may
                # have completed a refresh immediately before this lease was acquired.
                row = self.store.token_record()
                if required_scope not in {scope.strip() for scope in str(row.get("scope") or "").split(",")}:
                    raise TikTokOAuthError("TikTok account authorization is missing the required " + required_scope + " scope")
                if datetime.fromisoformat(row["access_expires_at"]) > _now() + timedelta(minutes=10):
                    return self.cipher.decrypt(row["access_token_encrypted"].encode()).decode()
                refresh_token = self.cipher.decrypt(row["refresh_token_encrypted"].encode()).decode()
                data = self._post_token({
                    "client_key": self.client_key,
                    "client_secret": self.client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                })
                self._save_token_response(data)
                if required_scope not in {scope.strip() for scope in str(data.get("scope") or "").split(",")}:
                    raise TikTokOAuthError("Refreshed TikTok token is missing the required " + required_scope + " scope")
                return data["access_token"]
            except InvalidToken as exc:
                raise TikTokOAuthError("Stored TikTok refresh token cannot be decrypted") from exc
            finally:
                self.store.release_refresh_lease(self._owner_id, lease)

    def disconnect(self):
        if not self.client_key or not self.client_secret:
            raise TikTokOAuthError("TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET are required to revoke TikTok access")
        if self.cipher is None:
            raise TikTokOAuthError("TIKTOK_TOKEN_ENCRYPTION_KEY must be a valid Fernet key to revoke TikTok access")
        row = self.store.token_record()
        if not row:
            return {"connected": False, "status": "disconnected"}
        access_token = self.get_access_token()
        body = urllib.parse.urlencode({
            "client_key": self.client_key,
            "client_secret": self.client_secret,
            "token": access_token,
        }).encode("utf-8")
        status, raw = self.transport(
            REVOKE_URL,
            {"Content-Type": "application/x-www-form-urlencoded",
             "Accept": "application/json", "Cache-Control": "no-cache"},
            body, 30,
        )
        data = {}
        if raw:
            try:
                data = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                raise TikTokOAuthError("TikTok revoke endpoint returned invalid JSON") from exc
        if status < 200 or status >= 300 or data.get("error"):
            code = data.get("error") or "http_" + str(status)
            raise TikTokOAuthError("TikTok token revocation failed: " + str(code))
        self.store.clear_tokens()
        return {"connected": False, "status": "disconnected"}

    def status(self):
        result = self.store.status()
        if result.get("connected") and "video.publish" not in {
            scope.strip() for scope in str(result.get("scope") or "").split(",")
        }:
            result.update({
                "connected": False,
                "status": "required_scope_missing",
                "reauthorization_required": True,
            })
        elif result.get("connected") and self.cipher is None:
            result.update({
                "connected": False,
                "status": "encryption_key_invalid" if self._cipher_invalid else "encryption_key_missing",
                "reauthorization_required": True,
            })
        elif result.get("connected") and (
            not self.client_key or not self.client_secret
        ):
            result.update({
                "connected": False,
                "status": "oauth_client_config_missing",
                "reauthorization_required": True,
            })
        return result

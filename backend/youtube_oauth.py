"""Secure server-side Google/YouTube OAuth connection and refresh-token storage."""
import hashlib
import json
import os
import secrets
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_READ_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
ANALYTICS_READ_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
REQUIRED_SCOPES = (UPLOAD_SCOPE, YOUTUBE_READ_SCOPE)
REQUESTED_SCOPES = (UPLOAD_SCOPE, YOUTUBE_READ_SCOPE, ANALYTICS_READ_SCOPE)


def _now():
    return datetime.now(timezone.utc)


def _stamp(value):
    return value.astimezone(timezone.utc).isoformat()


class YouTubeOAuthError(RuntimeError):
    pass


class YouTubeOAuthStore:
    def __init__(self, db_path="data/nexus.sqlite3"):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as connection:
            connection.executescript("""
            CREATE TABLE IF NOT EXISTS youtube_oauth_states(
              state_hash TEXT PRIMARY KEY, expires_at TEXT NOT NULL,
              used_at TEXT, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_youtube_oauth_states_expiry
              ON youtube_oauth_states(expires_at);
            CREATE TABLE IF NOT EXISTS youtube_oauth_tokens(
              id INTEGER PRIMARY KEY CHECK(id=1),
              refresh_token_encrypted TEXT NOT NULL,
              scope TEXT NOT NULL,
              token_type TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              channel_id TEXT,
              channel_title TEXT,
              last_verified_at TEXT,
              data_api_verified INTEGER NOT NULL DEFAULT 0,
              analytics_api_verified INTEGER NOT NULL DEFAULT 0,
              last_error TEXT
            );
            """)
            columns = {
                row["name"] for row in connection.execute(
                    "PRAGMA table_info(youtube_oauth_tokens)"
                ).fetchall()
            }
            migrations = {
                "channel_id": "TEXT",
                "channel_title": "TEXT",
                "last_verified_at": "TEXT",
                "data_api_verified": "INTEGER NOT NULL DEFAULT 0",
                "analytics_api_verified": "INTEGER NOT NULL DEFAULT 0",
                "last_error": "TEXT",
            }
            for name, declaration in migrations.items():
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE youtube_oauth_tokens ADD COLUMN {name} {declaration}"
                    )

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            yield connection
            if connection.in_transaction:
                connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def create_state(self, state_hash, ttl_seconds=600):
        now = _now()
        with self.db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM youtube_oauth_states WHERE expires_at<? OR used_at IS NOT NULL",
                (_stamp(now),),
            )
            connection.execute(
                "INSERT INTO youtube_oauth_states(state_hash,expires_at,created_at) VALUES(?,?,?)",
                (state_hash, _stamp(now + timedelta(seconds=ttl_seconds)), _stamp(now)),
            )

    def consume_state(self, state_hash):
        now = _stamp(_now())
        with self.db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM youtube_oauth_states WHERE state_hash=?",
                (state_hash,),
            ).fetchone()
            if not row or row["used_at"] or row["expires_at"] <= now:
                raise YouTubeOAuthError(
                    "YouTube OAuth state is invalid, expired or already used"
                )
            updated = connection.execute(
                "UPDATE youtube_oauth_states SET used_at=? WHERE state_hash=? AND used_at IS NULL",
                (now, state_hash),
            )
            if updated.rowcount != 1:
                raise YouTubeOAuthError("YouTube OAuth state has already been used")
        return True

    def save_token(self, encrypted_refresh_token, scope, token_type="Bearer"):
        with self.db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("""
                INSERT INTO youtube_oauth_tokens
                  (id,refresh_token_encrypted,scope,token_type,updated_at)
                VALUES(1,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                  refresh_token_encrypted=excluded.refresh_token_encrypted,
                  scope=excluded.scope,token_type=excluded.token_type,
                  updated_at=excluded.updated_at,channel_id=NULL,channel_title=NULL,
                  last_verified_at=NULL,data_api_verified=0,
                  analytics_api_verified=0,last_error=NULL
            """, (encrypted_refresh_token, scope, token_type, _stamp(_now())))

    def token_record(self):
        with self.db() as connection:
            row = connection.execute(
                "SELECT * FROM youtube_oauth_tokens WHERE id=1"
            ).fetchone()
        return dict(row) if row else None

    def record_verification(self, channel_id=None, channel_title=None,
                            data_api_verified=False, analytics_api_verified=False,
                            error=None):
        with self.db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("""
                UPDATE youtube_oauth_tokens SET
                  channel_id=?,channel_title=?,last_verified_at=?,
                  data_api_verified=?,analytics_api_verified=?,last_error=?
                WHERE id=1
            """, (
                channel_id, channel_title, _stamp(_now()),
                int(bool(data_api_verified)), int(bool(analytics_api_verified)),
                str(error)[:128] if error else None,
            ))

    def clear_token(self):
        with self.db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM youtube_oauth_tokens WHERE id=1")


class YouTubeOAuthManager:
    def __init__(self, store, client_id=None, client_secret=None,
                 redirect_uri=None, encryption_key=None, transport=None):
        self.store = store
        self.client_id = client_id or os.getenv("YOUTUBE_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("YOUTUBE_CLIENT_SECRET")
        self.redirect_uri = redirect_uri or os.getenv("YOUTUBE_REDIRECT_URI")
        key = encryption_key or os.getenv("YOUTUBE_TOKEN_ENCRYPTION_KEY")
        self.cipher = None
        self._cipher_invalid = False
        try:
            self.cipher = Fernet(key.encode() if isinstance(key, str) else key) if key else None
        except (ValueError, TypeError):
            self._cipher_invalid = True
        self.transport = transport or self._request

    @staticmethod
    def _request(url, headers, body, timeout):
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(4000)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise YouTubeOAuthError(
                "Google OAuth network request failed: " + type(exc).__name__
            ) from exc

    def _require_config(self):
        if not self.client_id or not self.client_secret or not self.redirect_uri:
            raise YouTubeOAuthError(
                "YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET and YOUTUBE_REDIRECT_URI are required"
            )
        parsed = urllib.parse.urlparse(self.redirect_uri)
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise YouTubeOAuthError(
                "YOUTUBE_REDIRECT_URI must be an absolute HTTPS URL without query or fragment"
            )
        if self.cipher is None:
            raise YouTubeOAuthError(
                "YOUTUBE_TOKEN_ENCRYPTION_KEY must be a valid Fernet key for encrypted token storage"
            )

    def start_authorization(self):
        self._require_config()
        state = secrets.token_urlsafe(32)
        self.store.create_state(hashlib.sha256(state.encode()).hexdigest(), ttl_seconds=600)
        query = urllib.parse.urlencode({
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(REQUESTED_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        })
        return {
            "authorization_url": AUTHORIZE_URL + "?" + query,
            "state": state,
            "expires_in": 600,
            "requested_scopes": list(REQUESTED_SCOPES),
        }

    def _exchange(self, code):
        body = urllib.parse.urlencode({
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
        }).encode("utf-8")
        status, raw = self.transport(
            TOKEN_URL,
            {"Content-Type": "application/x-www-form-urlencoded",
             "Accept": "application/json", "Cache-Control": "no-cache"},
            body, 30,
        )
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise YouTubeOAuthError("Google OAuth returned invalid JSON") from exc
        if status < 200 or status >= 300 or data.get("error"):
            code_name = str(data.get("error") or "http_" + str(status))
            raise YouTubeOAuthError("Google OAuth token exchange rejected: " + code_name)
        return data

    def exchange_code(self, code, state):
        self._require_config()
        if not isinstance(code, str) or not code.strip():
            raise YouTubeOAuthError("YouTube authorization code is required")
        if not isinstance(state, str) or not state:
            raise YouTubeOAuthError("YouTube OAuth state is required")
        self.store.consume_state(hashlib.sha256(state.encode()).hexdigest())
        data = self._exchange(code)
        refresh = data.get("refresh_token")
        access = data.get("access_token")
        if not isinstance(refresh, str) or not refresh or not isinstance(access, str) or not access:
            raise YouTubeOAuthError(
                "Google OAuth did not return a refresh token; reconnect with offline access and consent"
            )
        scopes = set(str(data.get("scope") or "").split())
        missing = [scope for scope in REQUIRED_SCOPES if scope not in scopes]
        if missing:
            raise YouTubeOAuthError(
                "Google OAuth is missing required YouTube scopes: " +
                ", ".join(scope.rsplit("/", 1)[-1] for scope in missing)
            )
        encrypted = self.cipher.encrypt(refresh.encode("utf-8")).decode("ascii")
        self.store.save_token(encrypted, " ".join(sorted(scopes)),
                              str(data.get("token_type") or "Bearer"))
        return {
            "connected": True,
            "scope": " ".join(sorted(scopes)),
            "updated_at": self.store.token_record()["updated_at"],
            "refresh_token_stored": True,
        }

    def get_refresh_token(self):
        row = self.store.token_record()
        if row:
            if self.cipher is None:
                raise YouTubeOAuthError(
                    "YOUTUBE_TOKEN_ENCRYPTION_KEY is required to decrypt the stored refresh token"
                )
            scopes = set(str(row.get("scope") or "").split())
            missing = [
                scope.rsplit("/", 1)[-1]
                for scope in REQUIRED_SCOPES if scope not in scopes
            ]
            if missing:
                raise YouTubeOAuthError(
                    "Stored YouTube OAuth token is missing required scopes: "
                    + ", ".join(missing)
                )
            try:
                return self.cipher.decrypt(
                    row["refresh_token_encrypted"].encode("ascii")
                ).decode("utf-8")
            except InvalidToken as exc:
                raise YouTubeOAuthError(
                    "Stored YouTube refresh token cannot be decrypted"
                ) from exc
        return os.getenv("YOUTUBE_REFRESH_TOKEN") or None

    def status(self):
        row = self.store.token_record()
        if row:
            if self.cipher is None:
                return {"connected": False, "status": "encryption_key_unavailable"}
            try:
                self.cipher.decrypt(row["refresh_token_encrypted"].encode("ascii"))
            except InvalidToken:
                return {"connected": False, "status": "stored_token_unreadable"}
            scopes = set(str(row["scope"]).split())
            missing = [scope.rsplit("/", 1)[-1] for scope in REQUIRED_SCOPES if scope not in scopes]
            return {
                "connected": not missing,
                "status": "authorized_token_stored" if not missing else "reauthorization_required",
                "scopes": sorted(scope.rsplit("/", 1)[-1] for scope in scopes),
                "live_connectivity_verified": False,
                "missing_scopes": missing,
                "updated_at": row["updated_at"],
                "mode": "encrypted_oauth",
                "static_fallback_configured": bool(os.getenv("YOUTUBE_REFRESH_TOKEN")),
                "channel_id": row.get("channel_id"),
                "channel_title": row.get("channel_title"),
                "last_verified_at": row.get("last_verified_at"),
                "data_api_verified": bool(row.get("data_api_verified")),
                "analytics_api_verified": bool(row.get("analytics_api_verified")),
                "last_error": row.get("last_error"),
            }
        if os.getenv("YOUTUBE_REFRESH_TOKEN"):
            return {
                "connected": True, "status": "static_env",
                "mode": "environment_refresh_token",
                "scope_verification": "not_available",
                "live_connectivity_verified": False,
                "static_fallback_configured": True,
            }
        return {
            "connected": False, "status": "disconnected", "mode": "none",
            "static_fallback_configured": False,
            "live_connectivity_verified": False,
        }

    def disconnect(self):
        self.store.clear_token()
        return {"connected": False, "status": "disconnected"}



class YouTubeConnectionVerifier:
    """Perform explicit live Data API and Analytics API checks after OAuth."""

    def __init__(self, oauth_manager, credentials_factory=None,
                 service_factory=None, request_factory=None, today=None):
        self.oauth_manager = oauth_manager
        self.credentials_factory = credentials_factory
        self.service_factory = service_factory
        self.request_factory = request_factory
        self.today = today or date.today

    def _factories(self):
        credentials_factory = self.credentials_factory
        service_factory = self.service_factory
        request_factory = self.request_factory
        if credentials_factory is None:
            from google.oauth2.credentials import Credentials
            credentials_factory = Credentials
        if service_factory is None:
            from googleapiclient.discovery import build
            service_factory = build
        if request_factory is None:
            from google.auth.transport.requests import Request
            request_factory = Request
        return credentials_factory, service_factory, request_factory

    def verify(self):
        row = self.oauth_manager.store.token_record()
        if row is None and not os.getenv("YOUTUBE_REFRESH_TOKEN"):
            raise YouTubeOAuthError("YouTube OAuth account is not connected")
        refresh = self.oauth_manager.get_refresh_token()
        credentials_factory, service_factory, request_factory = self._factories()
        channel_id = None
        channel_title = None
        data_verified = False
        analytics_verified = False
        error = None
        try:
            credentials = credentials_factory(
                token=None,
                refresh_token=refresh,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self.oauth_manager.client_id,
                client_secret=self.oauth_manager.client_secret,
                scopes=list(REQUESTED_SCOPES),
            )
            credentials.refresh(request_factory())
            youtube = service_factory(
                "youtube", "v3", credentials=credentials, cache_discovery=False
            )
            channel_response = youtube.channels().list(
                part="id,snippet", mine=True, maxResults=1
            ).execute()
            channels = channel_response.get("items") or []
            if not channels:
                error = "channel_not_found"
                raise YouTubeOAuthError("No YouTube channel is available for this account")
            channel = channels[0]
            channel_id = channel.get("id")
            channel_title = (channel.get("snippet") or {}).get("title")
            data_verified = bool(channel_id)
            if not data_verified:
                error = "channel_id_missing"
                raise YouTubeOAuthError("YouTube Data API did not return a channel ID")
        except YouTubeOAuthError:
            self.oauth_manager.store.record_verification(
                channel_id, channel_title, data_verified, False, error or "oauth_or_data_api_error"
            )
            raise
        except Exception as exc:
            error = type(exc).__name__
            self.oauth_manager.store.record_verification(
                channel_id, channel_title, False, False, error
            )
            return {
                "connected": True, "data_api_verified": False,
                "analytics_api_verified": False, "live_connectivity_verified": False,
                "error": error,
            }

        analytics_error = None
        try:
            analytics = service_factory(
                "youtubeAnalytics", "v2", credentials=credentials,
                cache_discovery=False,
            )
            end = self.today() - timedelta(days=2)
            start = end - timedelta(days=27)
            analytics.reports().query(
                ids="channel==MINE",
                startDate=start.isoformat(),
                endDate=end.isoformat(),
                metrics="views",
                maxResults=1,
            ).execute()
            analytics_verified = True
        except Exception as exc:
            analytics_error = type(exc).__name__
            error = analytics_error
        self.oauth_manager.store.record_verification(
            channel_id, channel_title, data_verified, analytics_verified, error
        )
        return {
            "connected": True,
            "channel_id": channel_id,
            "channel_title": channel_title,
            "data_api_verified": data_verified,
            "analytics_api_verified": analytics_verified,
            "live_connectivity_verified": data_verified and analytics_verified,
            "analytics_error": analytics_error,
            "verified_at": self.oauth_manager.store.token_record().get("last_verified_at"),
        }

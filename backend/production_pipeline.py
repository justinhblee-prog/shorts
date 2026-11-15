"""Provider-agnostic short-video production pipeline.

External providers must return real artifact references. This module never fabricates
scripts, audio, videos, durations, or provider success.
"""
import json
import os
import sqlite3
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class ProviderError(RuntimeError):
    def __init__(self, stage, message, retryable=True):
        super().__init__(message)
        self.stage = stage
        self.retryable = retryable


class ProductionLeaseConflict(RuntimeError):
    """Raised when a stale worker attempts to mutate production state."""


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class JsonProvider:
    """Small JSON-over-HTTPS adapter; provider-specific payload mapping stays explicit."""
    def __init__(self, url, token=None, timeout=90, transport=None):
        self.url = (url or "").strip()
        self.token = token
        self.timeout = timeout
        self.transport = transport or self._request

    @staticmethod
    def _request(url, headers, body, timeout):
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read(1000).decode("utf-8", "replace")
            raise ProviderError("provider", f"Provider HTTP {exc.code}: {detail}",
                                retryable=exc.code >= 500 or exc.code == 429)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderError("provider", f"Provider connection failed: {type(exc).__name__}")

    def post(self, stage, payload):
        if not self.url:
            raise ProviderError(stage, f"{stage} provider URL is not configured", retryable=False)
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            status, raw = self.transport(
                self.url, headers, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                self.timeout)
            if status < 200 or status >= 300:
                raise ProviderError(stage, f"{stage} provider returned HTTP {status}",
                                    retryable=status >= 500 or status == 429)
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Provider response must be a JSON object")
            return data
        except ProviderError as exc:
            if exc.stage == "provider":
                raise ProviderError(stage, str(exc), exc.retryable) from exc
            raise
        except (ValueError, UnicodeDecodeError, TypeError) as exc:
            raise ProviderError(stage, f"Invalid {stage} provider response: {exc}", False) from exc


class ProductionStore:
    def __init__(self, db_path="data/nexus.sqlite3"):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS production_runs(
              job_id TEXT PRIMARY KEY, brand TEXT NOT NULL, region TEXT NOT NULL,
              language TEXT NOT NULL, topic TEXT NOT NULL, status TEXT NOT NULL,
              current_stage TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS production_artifacts(
              id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES production_runs(job_id),
              stage TEXT NOT NULL, artifact_type TEXT NOT NULL, artifact_url TEXT,
              metadata_json TEXT NOT NULL, created_at TEXT NOT NULL,
              UNIQUE(job_id, stage));
            """)
    
    @contextmanager
    def db(self):
        c = sqlite3.connect(self.db_path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=30000")
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def create(self, job_id, brief):
        with self.db() as c:
            c.execute("""INSERT OR IGNORE INTO production_runs
              (job_id,brand,region,language,topic,status,current_stage,created_at,updated_at)
              VALUES(?,?,?,?,?,'queued','queued',?,?)""",
              (job_id, brief["brand"], brief["region"], brief["language"],
               brief["topic"], utc_now(), utc_now()))

    @staticmethod
    def _assert_worker_lease(c, job_id, worker_id, lease_token):
        if not worker_id or not lease_token:
            raise ProductionLeaseConflict("Worker ID and fencing token are required")
        row = c.execute("""SELECT status,worker_id,lease_token,lease_expires_at
            FROM pipeline_jobs WHERE id=?""", (job_id,)).fetchone()
        now = utc_now()
        if (row is None or row["status"] != "running"
                or row["worker_id"] != worker_id
                or row["lease_token"] != lease_token
                or not row["lease_expires_at"]
                or row["lease_expires_at"] <= now):
            raise ProductionLeaseConflict(
                "Worker lease expired or was replaced; stale production write rejected"
            )

    def stage(self, job_id, stage, status="running", error=None,
              worker_id=None, lease_token=None):
        with self.db() as c:
            if worker_id is not None or lease_token is not None:
                c.execute("BEGIN IMMEDIATE")
                self._assert_worker_lease(c, job_id, worker_id, lease_token)
            if stage == "script" and status == "running":
                # A fresh attempt invalidates every artifact from the previous attempt.
                # Keep this in the same transaction as the fenced stage transition.
                c.execute("DELETE FROM production_artifacts WHERE job_id=?", (job_id,))
            c.execute("""UPDATE production_runs SET current_stage=?,status=?,error=?,updated_at=?
                         WHERE job_id=?""", (stage, status, error, utc_now(), job_id))
            if c.total_changes == 0:
                raise KeyError(job_id)

    def artifact(self, job_id, stage, artifact_type, url, metadata,
                 worker_id=None, lease_token=None):
        if artifact_type in ("audio", "video") and (
            not isinstance(url, str) or not url.startswith(("https://", "http://"))
        ):
            raise ValueError(f"{stage} provider must return an HTTP(S) artifact URL")
        if url is not None and not isinstance(url, str):
            raise ValueError("artifact URL must be a string or null")
        with self.db() as c:
            if worker_id is not None or lease_token is not None:
                c.execute("BEGIN IMMEDIATE")
                self._assert_worker_lease(c, job_id, worker_id, lease_token)
            c.execute("""INSERT INTO production_artifacts
              (id,job_id,stage,artifact_type,artifact_url,metadata_json,created_at)
              VALUES(?,?,?,?,?,?,?)
              ON CONFLICT(job_id,stage) DO UPDATE SET
                artifact_type=excluded.artifact_type,
                artifact_url=excluded.artifact_url,
                metadata_json=excluded.metadata_json,
                created_at=excluded.created_at""",
              (str(uuid.uuid4()), job_id, stage, artifact_type, url,
               json.dumps(metadata, ensure_ascii=False), utc_now()))


    def reconcile_missing_runs(self, queue, job_ids=None, limit=200):
        """Restore production rows if a process crashed between queue enqueue and record creation."""
        if Path(queue.db_path).resolve() != Path(self.db_path).resolve():
            raise ValueError("ProductionStore and JobQueue must share the same SQLite database")
        restored = []
        invalid = []
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            params = []
            where = """j.job_type='short_video_production'
                AND j.status IN ('queued','failed_retriable','running')
                AND r.job_id IS NULL"""
            if job_ids is not None:
                ids = [str(value) for value in job_ids]
                if not ids:
                    return {"restored": 0, "job_ids": [], "invalid": []}
                where += " AND j.id IN (" + ",".join("?" for _ in ids) + ")"
                params.extend(ids)
            params.append(max(1, min(int(limit), 500)))
            rows = c.execute("""SELECT j.id,j.payload_json FROM pipeline_jobs j
                LEFT JOIN production_runs r ON r.job_id=j.id
                WHERE """ + where + " ORDER BY j.created_at LIMIT ?", params).fetchall()
            for row in rows:
                try:
                    brief = ProductionPipeline.validate_brief(json.loads(row["payload_json"]))
                except (TypeError, ValueError, json.JSONDecodeError):
                    invalid.append(row["id"])
                    continue
                timestamp = utc_now()
                c.execute("""INSERT OR IGNORE INTO production_runs
                    (job_id,brand,region,language,topic,status,current_stage,created_at,updated_at)
                    VALUES(?,?,?,?,?,'queued','queued',?,?)""",
                    (row["id"], brief["brand"], brief["region"], brief["language"],
                     brief["topic"], timestamp, timestamp))
                if c.rowcount:
                    restored.append(row["id"])
        return {"restored": len(restored), "job_ids": restored, "invalid": invalid}

    def reconcile_review_pending(self, queue, limit=100):
        """Atomically repair only queue jobs durably completed into review_pending."""
        if Path(queue.db_path).resolve() != Path(self.db_path).resolve():
            raise ValueError("ProductionStore and JobQueue must share the same SQLite database")
        repaired = []
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            rows = c.execute("""SELECT r.job_id FROM production_runs r
                JOIN pipeline_jobs j ON j.id=r.job_id
                WHERE r.status='rendered'
                  AND j.job_type='short_video_production'
                  AND j.status='review_pending'
                ORDER BY r.updated_at LIMIT ?""",
                (max(1, min(int(limit), 500)),)).fetchall()
            for row in rows:
                job_id = row["job_id"]
                c.execute("""UPDATE production_runs
                    SET status='review_pending',current_stage='review_pending',
                        error=NULL,updated_at=?
                    WHERE job_id=? AND status='rendered'
                      AND EXISTS (
                        SELECT 1 FROM pipeline_jobs j
                        WHERE j.id=production_runs.job_id
                          AND j.job_type='short_video_production'
                          AND j.status='review_pending'
                      )""", (utc_now(), job_id))
                if c.rowcount:
                    repaired.append(job_id)
        return {"reconciled": len(repaired), "job_ids": repaired}

    def get(self, job_id):
        with self.db() as c:
            run = c.execute("SELECT * FROM production_runs WHERE job_id=?", (job_id,)).fetchone()
            if run is None:
                return None
            artifacts = c.execute(
                "SELECT * FROM production_artifacts WHERE job_id=? ORDER BY created_at",
                (job_id,)).fetchall()
            result = dict(run)
            result["artifacts"] = [
                {**dict(a), "metadata": json.loads(a["metadata_json"])}
                for a in artifacts
            ]
            return result


class ProductionPipeline:
    """Executes script -> voice -> render using configured real provider endpoints."""
    def __init__(self, store, script_provider=None, voice_provider=None, render_provider=None):
        self.store = store
        self.script = script_provider or JsonProvider(
            os.getenv("SCRIPT_PROVIDER_URL"), os.getenv("SCRIPT_PROVIDER_TOKEN"))
        self.voice = voice_provider or JsonProvider(
            os.getenv("VOICE_PROVIDER_URL"), os.getenv("VOICE_PROVIDER_TOKEN"))
        self.render = render_provider or JsonProvider(
            os.getenv("RENDER_PROVIDER_URL"), os.getenv("RENDER_PROVIDER_TOKEN"))

    @staticmethod
    def validate_brief(brief):
        if not isinstance(brief, dict):
            raise ValueError("production brief must be an object")
        required = ("brand", "region", "language", "topic")
        for key in required:
            if not isinstance(brief.get(key), str) or not brief[key].strip():
                raise ValueError(f"{key} is required")
        if len(brief["topic"]) > 500:
            raise ValueError("topic must be 500 characters or fewer")
        return {key: brief[key].strip() for key in required}

    def execute(self, job_id, brief, worker_id=None, lease_token=None):
        brief = self.validate_brief(brief)
        if (worker_id is None) != (lease_token is None):
            raise ValueError("worker_id and lease_token must be supplied together")
        lease = {"worker_id": worker_id, "lease_token": lease_token}
        try:
            self.store.stage(job_id, "script", **lease)
            script = self.script.post("script", {
                "task": "create_short_video_script",
                "brand": brief["brand"], "region": brief["region"],
                "language": brief["language"], "topic": brief["topic"],
                "format": "vertical_short", "require_fact_check": True
            })
            script_text = script.get("script")
            if not isinstance(script_text, str) or not script_text.strip():
                raise ProviderError("script", "Script provider returned no script text", False)
            self.store.artifact(job_id, "script", "text", script.get("artifact_url"),
                                {"script": script_text, "provider": script.get("provider")},
                                **lease)

            self.store.stage(job_id, "voice_generation", **lease)
            voice = self.voice.post("voice_generation", {
                "script": script_text, "language": brief["language"],
                "brand": brief["brand"], "format": "narration"
            })
            audio_url = voice.get("audio_url")
            if not isinstance(audio_url, str) or not audio_url.startswith(("https://", "http://")):
                raise ProviderError("voice_generation", "Voice provider returned no valid audio_url", False)
            self.store.artifact(job_id, "voice_generation", "audio", audio_url,
                                {k: v for k, v in voice.items() if k != "audio_url"},
                                **lease)

            self.store.stage(job_id, "rendering", **lease)
            rendered = self.render.post("rendering", {
                "script": script_text, "audio_url": audio_url,
                "brand": brief["brand"], "region": brief["region"],
                "language": brief["language"], "aspect_ratio": "9:16",
                "subtitles": True
            })
            video_url = rendered.get("video_url")
            if not isinstance(video_url, str) or not video_url.startswith(("https://", "http://")):
                raise ProviderError("rendering", "Renderer returned no valid video_url", False)
            self.store.artifact(job_id, "rendering", "video", video_url,
                                {k: v for k, v in rendered.items() if k != "video_url"},
                                **lease)
            self.store.stage(job_id, "rendered", "rendered", **lease)
            return self.store.get(job_id)
        except ProductionLeaseConflict:
            # A stale worker must not mark a newer worker's run as failed.
            raise
        except ProviderError as exc:
            self.store.stage(job_id, exc.stage,
                             "failed_retriable" if exc.retryable else "failed_terminal",
                             str(exc), **lease)
            raise
        except Exception as exc:
            self.store.stage(job_id, "pipeline", "failed_terminal", str(exc), **lease)
            raise


def submit_production(queue, store, brief):
    """Create a durable queue job and its production record; no provider call occurs here."""
    clean = ProductionPipeline.validate_brief(brief)
    job = queue.enqueue("short_video_production", clean,
                        channel_name=clean["brand"],
                        idempotency_key=brief.get("idempotency_key"))
    if not store.get(job["id"]):
        store.create(job["id"], clean)
    return {"job": job, "production": store.get(job["id"])}

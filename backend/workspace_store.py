"""Durable SQLite workspace registry; authentication remains the caller's responsibility."""
import os, re, sqlite3, uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_ROLES = {"owner", "admin", "editor", "viewer"}

class WorkspaceError(Exception): pass
class WorkspaceDenied(WorkspaceError): pass
class WorkspaceNotFound(WorkspaceError): pass
class WorkspaceConflict(WorkspaceError): pass

def _now():
    return datetime.now(timezone.utc).isoformat()

def _principal(value):
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 128:
        raise ValueError("invalid principal ID")
    return value

def _wid(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("invalid opaque workspace ID")
    return value

class WorkspaceStore:
    def __init__(self, db_path=None):
        # Match every other backend store/worker so all modules share one SQLite file.
        self.db_path = str(db_path if db_path is not None else (os.getenv("NEXUS_DB_PATH") or "data/nexus.sqlite3"))
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS workspaces(
              id TEXT PRIMARY KEY, name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 120),
              status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','suspended','deleted')),
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS workspace_memberships(
              workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
              principal_id TEXT NOT NULL,
              role TEXT NOT NULL CHECK(role IN ('owner','admin','editor','viewer')),
              status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','revoked')),
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              PRIMARY KEY(workspace_id,principal_id));
            CREATE INDEX IF NOT EXISTS idx_workspace_membership_principal
              ON workspace_memberships(principal_id,status,workspace_id);
            CREATE TABLE IF NOT EXISTS workspace_audit_events(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
              actor_principal_id TEXT NOT NULL, subject_principal_id TEXT,
              event_type TEXT NOT NULL, details TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS workspace_audit_no_update BEFORE UPDATE ON workspace_audit_events
              BEGIN SELECT RAISE(ABORT,'workspace audit events are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS workspace_audit_no_delete BEFORE DELETE ON workspace_audit_events
              BEGIN SELECT RAISE(ABORT,'workspace audit events are immutable'); END;
            """)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=30000")
        try:
            yield db
        except Exception:
            if db.in_transaction: db.rollback()
            raise
        finally:
            db.close()

    def create(self, name, owner_principal_id, workspace_id=None):
        owner = _principal(owner_principal_id)
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
            raise ValueError("workspace name must contain 1 to 120 characters")
        wid, now = _wid(workspace_id or ("ws_" + uuid.uuid4().hex)), _now()
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("INSERT INTO workspaces VALUES(?,?, 'active',?,?)", (wid,name.strip(),now,now))
                db.execute("""INSERT INTO workspace_memberships
                  VALUES(?,?, 'owner','active',?,?)""", (wid,owner,now,now))
                db.execute("""INSERT INTO workspace_audit_events
                  (workspace_id,actor_principal_id,subject_principal_id,event_type,details,created_at)
                  VALUES(?,?,?,'workspace.created','{}',?)""", (wid,owner,owner,now))
                db.commit()
            except sqlite3.IntegrityError as exc:
                db.rollback()
                raise WorkspaceConflict("workspace already exists or violates registry constraints") from exc
        return self.require_membership(wid, owner)

    def require_membership(self, workspace_id, principal_id, minimum_roles=None):
        wid, principal = _wid(workspace_id), _principal(principal_id)
        with self.db() as db:
            row = db.execute("""SELECT w.id,w.name,w.status,m.role,m.status AS membership_status
              FROM workspaces w JOIN workspace_memberships m ON m.workspace_id=w.id
              WHERE w.id=? AND m.principal_id=?""", (wid,principal)).fetchone()
        if row is None or row["status"] != "active" or row["membership_status"] != "active":
            raise WorkspaceDenied("active workspace membership is required")
        if minimum_roles is not None and row["role"] not in set(minimum_roles):
            raise WorkspaceDenied("workspace role does not permit this action")
        return dict(row)

    def add_member(self, workspace_id, actor_principal_id, subject_principal_id, role="editor"):
        wid, actor, subject = _wid(workspace_id), _principal(actor_principal_id), _principal(subject_principal_id)
        if role not in {"admin","editor","viewer"}:
            raise ValueError("new members may be admin, editor or viewer")
        now = _now()
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("""SELECT role FROM workspace_memberships
              WHERE workspace_id=? AND principal_id=? AND status='active'""", (wid,actor)).fetchone()
            if current is None or current["role"] not in {"owner","admin"}:
                db.rollback()
                raise WorkspaceDenied("workspace admin membership is required")
            if db.execute("SELECT 1 FROM workspaces WHERE id=? AND status='active'",(wid,)).fetchone() is None:
                db.rollback()
                raise WorkspaceNotFound("workspace not found")
            old = db.execute("SELECT status FROM workspace_memberships WHERE workspace_id=? AND principal_id=?",(wid,subject)).fetchone()
            if old and old["status"] == "active":
                db.rollback()
                raise WorkspaceConflict("principal is already an active member")
            if old:
                db.execute("""UPDATE workspace_memberships SET role=?,status='active',updated_at=?
                  WHERE workspace_id=? AND principal_id=?""",(role,now,wid,subject))
            else:
                db.execute("""INSERT INTO workspace_memberships
                  VALUES(?,?,?,'active',?,?)""",(wid,subject,role,now,now))
            db.execute("""INSERT INTO workspace_audit_events
              (workspace_id,actor_principal_id,subject_principal_id,event_type,details,created_at)
              VALUES(?,?,?,'member.added',?,?)""",(wid,actor,subject,'{"role":"'+role+'"}',now))
            db.commit()
        return {"workspace_id":wid,"principal_id":subject,"role":role,"status":"active"}

    def revoke_member(self, workspace_id, actor_principal_id, subject_principal_id):
        wid, actor, subject = _wid(workspace_id), _principal(actor_principal_id), _principal(subject_principal_id)
        now = _now()
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("""SELECT principal_id,role FROM workspace_memberships
              WHERE workspace_id=? AND status='active'""",(wid,)).fetchall()
            actor_role = next((r["role"] for r in rows if r["principal_id"] == actor),None)
            target = next((r for r in rows if r["principal_id"] == subject),None)
            if actor_role not in {"owner","admin"}:
                db.rollback()
                raise WorkspaceDenied("workspace admin membership is required")
            if target is None:
                db.rollback()
                raise WorkspaceNotFound("active membership not found")
            if target["role"] == "owner":
                if actor_role != "owner":
                    db.rollback()
                    raise WorkspaceDenied("only an owner may revoke another owner")
                if sum(r["role"] == "owner" for r in rows) <= 1:
                    db.rollback()
                    raise WorkspaceConflict("the last owner cannot be removed")
            db.execute("""UPDATE workspace_memberships SET status='revoked',updated_at=?
              WHERE workspace_id=? AND principal_id=?""",(now,wid,subject))
            db.execute("""INSERT INTO workspace_audit_events
              (workspace_id,actor_principal_id,subject_principal_id,event_type,details,created_at)
              VALUES(?,?,?,'member.revoked','{}',?)""",(wid,actor,subject,now))
            db.commit()
        return {"workspace_id":wid,"principal_id":subject,"status":"revoked"}

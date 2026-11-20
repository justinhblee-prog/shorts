"""Auditable revenue and cost ledger. Values are recorded inputs, never inferred from views."""
import json, sqlite3, uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class LedgerStore:
    SOURCES={"youtube_analytics","affiliate_network","sponsor_invoice","payment_processor",
             "cloud_provider","ai_provider","voice_provider","render_provider","operator_receipt"}
    TYPES={"youtube_ads","affiliate","sponsor","production_cost","platform_fee","other_cost"}
    def __init__(self,db_path="data/nexus.sqlite3"):
        self.db_path=str(db_path); Path(self.db_path).parent.mkdir(parents=True,exist_ok=True)
        with self.db() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS financial_ledger(
              id TEXT PRIMARY KEY, job_id TEXT, workspace_id TEXT, brand TEXT NOT NULL, region TEXT NOT NULL,
              entry_type TEXT NOT NULL, amount REAL NOT NULL CHECK(amount>=0),
              currency TEXT NOT NULL, source_type TEXT NOT NULL, source_reference TEXT NOT NULL,
              occurred_at TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL, UNIQUE(source_type,source_reference,entry_type)
            );
            CREATE INDEX IF NOT EXISTS idx_ledger_brand_date ON financial_ledger(brand,occurred_at);
            CREATE INDEX IF NOT EXISTS idx_ledger_job ON financial_ledger(job_id);
            """)
            columns={row["name"] for row in c.execute("PRAGMA table_info(financial_ledger)")}
            if "workspace_id" not in columns:
                c.execute("ALTER TABLE financial_ledger ADD COLUMN workspace_id TEXT")
            c.execute("CREATE INDEX IF NOT EXISTS idx_ledger_workspace_date ON financial_ledger(workspace_id,occurred_at)")
    @contextmanager
    def db(self):
        c=sqlite3.connect(self.db_path,timeout=30); c.row_factory=sqlite3.Row
        c.execute("PRAGMA busy_timeout=30000")
        try: yield c; c.commit()
        except Exception: c.rollback(); raise
        finally: c.close()
    def record(self,data,workspace_id=None):
        typ=data["entry_type"]; src=data["source_type"]
        if typ not in self.TYPES: raise ValueError("Unsupported ledger entry_type")
        if src not in self.SOURCES: raise ValueError("Unsupported source_type")
        amount=float(data["amount"])
        if amount<0: raise ValueError("amount must be non-negative")
        currency=data["currency"].upper()
        if len(currency)!=3: raise ValueError("currency must be ISO 4217 code")
        ref=data["source_reference"].strip()
        if not ref: raise ValueError("source_reference is required for audit and idempotency")
        when=data["occurred_at"]
        datetime.fromisoformat(when.replace("Z","+00:00"))
        now=datetime.now(timezone.utc).isoformat()
        rowid=str(uuid.uuid4())
        if workspace_id is not None and (
                not isinstance(workspace_id,str) or not workspace_id.strip()
                or len(workspace_id)>128):
            raise ValueError("workspace_id must be a non-empty string of at most 128 characters")
        with self.db() as c:
            job_id=data.get("job_id")
            if job_id:
                parent=c.execute("SELECT workspace_id FROM production_runs WHERE job_id=?",(job_id,)).fetchone()
                if parent is None or parent["workspace_id"] != workspace_id:
                    raise ValueError("financial entry job is outside the selected workspace")
            c.execute("""INSERT OR IGNORE INTO financial_ledger
              (id,job_id,workspace_id,brand,region,entry_type,amount,currency,source_type,
               source_reference,occurred_at,note,created_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (rowid,job_id,workspace_id,data["brand"],data["region"],typ,amount,
               currency,src,ref,when,data.get("note","")[:2000],now))
            row=c.execute("""SELECT * FROM financial_ledger WHERE
              source_type=? AND source_reference=? AND entry_type=?""",
              (src,ref,typ)).fetchone()
            if row["workspace_id"] != workspace_id:
                raise ValueError("financial source reference already belongs to another workspace")
            return dict(row)
    def report(self,brand=None,from_date=None,to_date=None,currency="USD",workspace_id=None):
        clauses=["currency=?","workspace_id IS ?"]; args=[currency.upper(),workspace_id]
        if brand: clauses.append("brand=?"); args.append(brand)
        if from_date: clauses.append("occurred_at>=?"); args.append(from_date)
        if to_date: clauses.append("occurred_at<=?"); args.append(to_date)
        where=" AND ".join(clauses)
        with self.db() as c:
            rows=c.execute("SELECT * FROM financial_ledger WHERE "+where+" ORDER BY occurred_at",
                           args).fetchall()
        totals={}
        for row in rows:
            item=dict(row); key=item["entry_type"]
            totals[key]=round(totals.get(key,0)+item["amount"],2)
        revenue=sum(totals.get(k,0) for k in ("youtube_ads","affiliate","sponsor"))
        costs=sum(v for k,v in totals.items() if k.endswith("_cost") or k=="platform_fee")
        return {"currency":currency.upper(),"entries":[dict(r) for r in rows],
                "totals_by_type":totals,"revenue":round(revenue,2),
                "costs":round(costs,2),"net":round(revenue-costs,2),
                "roi_percent":round((revenue-costs)/costs*100,2) if costs else None,
                "revenue_is_recorded_input":True}

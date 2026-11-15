"""Evidence-bound performance summaries; recommendations are heuristics, not predictions."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class PerformanceAnalyzer:
    def __init__(self,db_path="data/nexus.sqlite3"):
        self.db_path=str(db_path)
    @contextmanager
    def db(self):
        c=sqlite3.connect(self.db_path,timeout=30); c.row_factory=sqlite3.Row
        c.execute("PRAGMA busy_timeout=30000")
        try: yield c
        finally: c.close()
    def analyze(self,brand=None):
        with self.db() as c:
            where="WHERE r.status IN ('uploaded','approved')"
            args=[]
            if brand: where+=" AND r.brand=?"; args.append(brand)
            videos=c.execute("""
              SELECT r.job_id,r.brand,r.region,r.topic,u.video_id,
                     s.view_count,s.like_count,s.comment_count,s.collected_at
              FROM production_runs r
              JOIN youtube_uploads u ON u.job_id=r.job_id AND u.status='uploaded'
              LEFT JOIN youtube_video_snapshots s ON s.video_id=u.video_id
            """+where+" ORDER BY r.brand,r.job_id,s.collected_at",args).fetchall()
            ledger=c.execute("SELECT brand,entry_type,currency,SUM(amount) amount,COUNT(*) n "
                             "FROM financial_ledger GROUP BY brand,entry_type,currency").fetchall()
        groups={}
        for row in videos:
            key=row["job_id"]
            groups.setdefault(key,{"job_id":key,"brand":row["brand"],"region":row["region"],
                "topic":row["topic"],"video_id":row["video_id"],"snapshots":[]})
            if row["collected_at"] is not None:
                groups[key]["snapshots"].append({
                    "views":row["view_count"],"likes":row["like_count"],
                    "comments":row["comment_count"],"collected_at":row["collected_at"]})
        by_brand={}
        for v in groups.values():
            b=by_brand.setdefault(v["brand"],{"brand":v["brand"],"videos":0,
                "measured_videos":0,"view_delta":0,"like_delta":0,"comment_delta":0,
                "recommendations":[]})
            b["videos"]+=1
            snaps=v["snapshots"]
            if len(snaps)>=2:
                first,last=snaps[0],snaps[-1]
                if first["views"] is not None and last["views"] is not None:
                    b["view_delta"]+=last["views"]-first["views"]
                    b["measured_videos"]+=1
                for field in ("likes","comments"):
                    if first[field] is not None and last[field] is not None:
                        b[field[:-1]+"_delta"]+=last[field]-first[field]
            else:
                b["recommendations"].append({
                    "type":"measurement_gap","basis":"fewer_than_two_counter_snapshots",
                    "action":"Collect another YouTube Data API snapshot before judging growth",
                    "job_id":v["job_id"]})
        for b in by_brand.values():
            if b["measured_videos"]==0:
                b["recommendations"].append({
                    "type":"insufficient_evidence","basis":"no_comparable_view_snapshots",
                    "action":"Do not rank this brand's performance until comparable snapshots exist"})
            elif b["view_delta"]<0:
                b["recommendations"].append({
                    "type":"review_topic_and_packaging","basis":"negative_observed_view_delta",
                    "action":"Review topic selection, title and opening hook; test one change at a time"})
            elif b["view_delta"]>0:
                b["recommendations"].append({
                    "type":"retain_and_test","basis":"positive_observed_view_delta",
                    "action":"Preserve the current format while testing one controlled variation"})
            b["view_delta_is_snapshot_difference"]=True
        financial={}
        for row in ledger:
            b=financial.setdefault(row["brand"],{"currency":row["currency"],"revenue":0,
                                                  "costs":0,"net":0,"entries":0})
            if b["currency"]!=row["currency"]:
                b["currency"]="MIXED"
                continue
            amount=float(row["amount"]); b["entries"]+=row["n"]
            if row["entry_type"] in ("youtube_ads","affiliate","sponsor"): b["revenue"]+=amount
            else: b["costs"]+=amount
            b["net"]=round(b["revenue"]-b["costs"],2)
        return {"method":"rule_based_source_evidence_only","brands":list(by_brand.values()),
                "financial":financial,
                "limitations":["View deltas are differences between stored snapshots, not real-time velocity.",
                "Recommendations are operational heuristics, not causal claims or forecasts.",
                "Financial totals include only manually/source-integrated ledger entries.",
                "Mixed currencies are not combined."]}

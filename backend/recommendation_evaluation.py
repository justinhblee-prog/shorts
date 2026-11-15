"""Auditable recommendation exposure and chronological holdout evaluation.

Only recommendations returned by the API and subsequently selected for production
are eligible outcomes. This is an observational, selection-biased evaluation, not
a causal estimate or a counterfactual test of unseen recommendations.
"""
import hashlib
import json
import math
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


def _rank(values):
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        average = ((index + 1) + end) / 2.0
        for position in range(index, end):
            ranks[ordered[position][0]] = average
        index = end
    return ranks


def _spearman(left, right):
    if len(left) != len(right) or len(left) < 2:
        return None
    x, y = _rank(left), _rank(right)
    mx, my = sum(x) / len(x), sum(y) / len(y)
    dx = [value - mx for value in x]
    dy = [value - my for value in y]
    denom = math.sqrt(sum(value * value for value in dx) *
                      sum(value * value for value in dy))
    if denom == 0:
        return None
    return round(sum(a * b for a, b in zip(dx, dy)) / denom, 4)


class RecommendationEvaluationStore:
    def __init__(self, db_path="data/nexus.sqlite3"):
        self.db_path = str(db_path)
        with self.db() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS recommendation_runs(
              id TEXT PRIMARY KEY, region TEXT, generated_at TEXT NOT NULL,
              candidate_count INTEGER NOT NULL, scoring_method TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS recommendation_candidates(
              id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES recommendation_runs(id),
              trend_id TEXT NOT NULL, trend_title TEXT NOT NULL, trend_region TEXT,
              brand_slug TEXT NOT NULL, brand_name TEXT NOT NULL,
              recommendation_rank INTEGER NOT NULL, recommendation_score REAL NOT NULL,
              score_breakdown_json TEXT NOT NULL, cohort_context_json TEXT NOT NULL,
              selected_job_id TEXT UNIQUE, selected_at TEXT,
              created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_recommendation_candidate_lookup
              ON recommendation_candidates(trend_id,brand_slug,created_at);
            CREATE INDEX IF NOT EXISTS idx_recommendation_candidate_selected
              ON recommendation_candidates(selected_job_id,selected_at);
            """)
            columns = {row["name"] for row in c.execute(
                "PRAGMA table_info(recommendation_runs)"
            ).fetchall()}
            if "signature" not in columns:
                c.execute("ALTER TABLE recommendation_runs ADD COLUMN signature TEXT NOT NULL DEFAULT ''")

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

    def record_run(self, region, items, generated_at=None):
        timestamp = generated_at or _now()
        run_id = str(uuid.uuid4())
        rows = []
        for rank, item in enumerate(items or [], start=1):
            trend = item.get("trend") or {}
            best = item.get("best_brand") or {}
            trend_id = str(trend.get("id") or "")
            brand_slug = str(best.get("brand") or "")
            brand_name = str(best.get("brand_name") or "")
            if not trend_id or not brand_slug or not brand_name:
                continue
            rows.append((
                str(uuid.uuid4()), run_id, trend_id,
                str(trend.get("title") or "")[:500],
                str(trend.get("region") or ""),
                brand_slug, brand_name, rank,
                float(item.get("recommendation_score") or 0),
                json.dumps(item.get("score_breakdown") or {}, ensure_ascii=False,
                           sort_keys=True),
                json.dumps(best.get("comparable_cohort_performance") or {},
                           ensure_ascii=False, sort_keys=True),
                timestamp,
            ))
        signature_payload = [
            [row[2], row[5], row[7], row[8], row[9], row[10]]
            for row in rows
        ]
        signature = hashlib.sha256(json.dumps(
            signature_payload, ensure_ascii=False, sort_keys=True
        ).encode("utf-8")).hexdigest()
        generated = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=timezone.utc)
        cutoff = (generated - timedelta(seconds=60)).isoformat()
        retention_cutoff = (generated - timedelta(days=180)).isoformat()
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            previous = c.execute("""SELECT id,candidate_count FROM recommendation_runs
                WHERE region IS ? AND signature=? AND generated_at>=?
                ORDER BY generated_at DESC LIMIT 1""",
                (region, signature, cutoff)).fetchone()
            if previous:
                return {
                    "run_id": previous["id"],
                    "recorded_candidates": int(previous["candidate_count"]),
                    "deduplicated": True,
                }
            c.execute("""INSERT INTO recommendation_runs
              (id,region,generated_at,candidate_count,scoring_method,signature)
              VALUES(?,?,?,?,?,?)""",
              (run_id, region, timestamp, len(rows), "editorial_v1", signature))
            c.executemany("""INSERT INTO recommendation_candidates
              (id,run_id,trend_id,trend_title,trend_region,brand_slug,brand_name,
               recommendation_rank,recommendation_score,score_breakdown_json,
               cohort_context_json,created_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
            # Retain selected records indefinitely for longitudinal evaluation;
            # prune only stale, unselected snapshots and their empty run headers.
            c.execute("""DELETE FROM recommendation_candidates
                WHERE selected_job_id IS NULL AND created_at<?""",
                (retention_cutoff,))
            c.execute("""DELETE FROM recommendation_runs
                WHERE generated_at<? AND NOT EXISTS (
                  SELECT 1 FROM recommendation_candidates c
                  WHERE c.run_id=recommendation_runs.id
                )""", (retention_cutoff,))
        return {
            "run_id": run_id, "recorded_candidates": len(rows),
            "deduplicated": False,
        }

    def link_production(self, trend_id, brand_slug, job_id, selected_at=None):
        timestamp = selected_at or _now()
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("""SELECT id FROM recommendation_candidates
                WHERE trend_id=? AND brand_slug=? AND selected_job_id IS NULL
                ORDER BY created_at DESC LIMIT 1""",
                (str(trend_id), str(brand_slug))).fetchone()
            if row is None:
                return {"linked": False, "reason": "no_matching_recommendation_exposure"}
            changed = c.execute("""UPDATE recommendation_candidates
                SET selected_job_id=?,selected_at=?
                WHERE id=? AND selected_job_id IS NULL""",
                (str(job_id), timestamp, row["id"])).rowcount
            return {"linked": bool(changed), "candidate_id": row["id"] if changed else None}

    def evaluate(self, performance):
        measured = {
            str(item.get("job_id")): item for item in performance.get("videos", [])
            if item.get("measurement_status") == "measured"
            and isinstance(item.get("views_per_hour"), (int, float))
            and item.get("views_per_hour") >= 0
        }
        with self.db() as c:
            rows = c.execute("""SELECT c.run_id,r.generated_at AS run_generated_at,
                c.selected_job_id,c.selected_at,c.created_at,
                c.recommendation_rank,c.recommendation_score,c.trend_id,c.brand_slug
                FROM recommendation_candidates c
                JOIN recommendation_runs r ON r.id=c.run_id
                WHERE c.selected_job_id IS NOT NULL
                ORDER BY r.generated_at,c.recommendation_rank,c.selected_job_id""").fetchall()
        # One outcome per production job. A unique constraint also prevents
        # accidentally attaching one job to multiple candidate exposures.
        observations = []
        seen = set()
        for row in rows:
            job_id = row["selected_job_id"]
            if job_id in seen or job_id not in measured:
                continue
            seen.add(job_id)
            observations.append({
                "job_id": job_id,
                "run_id": row["run_id"],
                "run_generated_at": row["run_generated_at"],
                "observed_at": row["selected_at"] or row["created_at"],
                "recommendation_rank": int(row["recommendation_rank"]),
                "recommendation_score": float(row["recommendation_score"]),
                "views_per_hour": float(measured[job_id]["views_per_hour"]),
                "brand": row["brand_slug"],
                "trend_id": row["trend_id"],
            })
        total_selected = len(rows)
        total_measured = len(observations)
        # Compare candidates within the same recommendation exposure. Raw scores
        # from different API runs are not directly comparable because freshness,
        # candidate sets and collection times differ.
        grouped = {}
        for item in observations:
            grouped.setdefault(item["run_id"], []).append(item)
        run_diagnostics = []
        for run_id, items in grouped.items():
            if len(items) < 3:
                continue
            score_rho = _spearman(
                [item["recommendation_score"] for item in items],
                [item["views_per_hour"] for item in items],
            )
            rank_rho = _spearman(
                [-item["recommendation_rank"] for item in items],
                [item["views_per_hour"] for item in items],
            )
            if score_rho is None or rank_rho is None:
                continue
            run_diagnostics.append({
                "run_id": run_id,
                "generated_at": items[0]["run_generated_at"],
                "selected_measured_count": len(items),
                "score_views_spearman": score_rho,
                "rank_views_spearman": rank_rho,
            })
        run_diagnostics.sort(key=lambda item: item["generated_at"])
        within_run = {
            "status": "insufficient_run_coverage",
            "method": "within_exposure_run_spearman_chronological_holdout",
            "eligible_run_count": len(run_diagnostics),
            "minimum_selected_measured_per_run": 3,
            "pre_holdout_run_count": 0,
            "holdout_run_count": 0,
            "holdout_median_score_views_spearman": None,
            "holdout_median_rank_views_spearman": None,
            "holdout_positive_score_association_share": None,
            "score_adjustment_enabled": False,
            "reason": (
                "At least five recommendation exposure runs with three or more "
                "selected and measured candidates each are required."
            ),
        }
        if len(run_diagnostics) >= 5:
            run_split = max(2, int(math.ceil(len(run_diagnostics) * 0.30)))
            run_split = min(run_split, len(run_diagnostics) - 2)
            run_holdout = run_diagnostics[-run_split:]
            score_values = [item["score_views_spearman"] for item in run_holdout]
            rank_values = [item["rank_views_spearman"] for item in run_holdout]
            within_run.update({
                "status": "holdout_available",
                "pre_holdout_run_count": len(run_diagnostics) - run_split,
                "holdout_run_count": run_split,
                "holdout_start": run_holdout[0]["generated_at"],
                "holdout_end": run_holdout[-1]["generated_at"],
                "holdout_median_score_views_spearman": round(
                    __import__("statistics").median(score_values), 4
                ),
                "holdout_median_rank_views_spearman": round(
                    __import__("statistics").median(rank_values), 4
                ),
                "holdout_positive_score_association_share": round(
                    sum(value > 0 for value in score_values) / len(score_values), 4
                ),
                "reason": (
                    "Within-run holdout compares selected measured candidates only. "
                    "It remains observational and selection-biased; no score change is enabled."
                ),
            })
        result = {
            "status": "insufficient_data",
            "method": "chronological_70_30_holdout_spearman",
            "selected_production_count": total_selected,
            "measured_outcome_count": total_measured,
            "unmeasured_selected_count": max(0, total_selected - total_measured),
            "pre_holdout_count": 0,
            "holdout_count": 0,
            "holdout_score_views_spearman": None,
            "holdout_rank_views_spearman": None,
            "ranking_score_adjustment_enabled": False,
            "within_run_validation": within_run,
            "minimum_total_observations": 10,
            "pooled_metric_boundary": (
                "The pooled chronological Spearman metric mixes different exposure runs "
                "and is a coarse diagnostic only; within-run validation is the preferred "
                "comparison because candidates share one captured ranking context."
            ),
            "warning": (
                "Observational only: outcomes exist only for recommendations selected "
                "for production. selection bias and unobserved candidates prevent "
                "causal or market-wide conclusions."
            ),
        }
        if total_measured < 10:
            result["reason"] = "At least 10 distinct selected and measured production outcomes are required."
            return result
        split = max(5, int(math.ceil(total_measured * 0.30)))
        split = min(split, total_measured - 5)
        pre_holdout = observations[:-split]
        holdout = observations[-split:]
        result.update({
            "status": "holdout_available",
            "pre_holdout_count": len(pre_holdout),
            "holdout_count": len(holdout),
            "holdout_start": holdout[0]["observed_at"],
            "holdout_end": holdout[-1]["observed_at"],
            "holdout_score_views_spearman": _spearman(
                [item["recommendation_score"] for item in holdout],
                [item["views_per_hour"] for item in holdout],
            ),
            "holdout_rank_views_spearman": _spearman(
                [-item["recommendation_rank"] for item in holdout],
                [item["views_per_hour"] for item in holdout],
            ),
            "holdout_scope": "Selected recommendations with measured snapshot-derived views/hour only.",
            "ranking_score_adjustment_enabled": False,
        })
        if result["holdout_score_views_spearman"] is None:
            result["status"] = "holdout_inconclusive"
            result["reason"] = "Holdout score or outcome values have no rank variance."
        else:
            result["reason"] = (
                "This is a first chronological holdout diagnostic, not sufficient evidence "
                "to enable score changes. Repeat across later periods and evaluate "
                "coverage, stability and selection bias."
            )
        return result

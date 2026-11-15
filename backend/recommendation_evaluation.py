"""Auditable recommendation exposure and chronological holdout evaluation.

Only recommendations returned by the API and subsequently selected for production
are eligible outcomes. This is an observational, selection-biased evaluation, not
a causal estimate or a counterfactual test of unseen recommendations.
"""
import hashlib
import json
import math
import sqlite3
import statistics
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
            candidate_columns = {row["name"] for row in c.execute(
                "PRAGMA table_info(recommendation_candidates)"
            ).fetchall()}
            for name, definition in (
                ("decision", "TEXT"),
                ("decision_reason", "TEXT"),
                ("reviewer_id", "TEXT"),
                ("decided_at", "TEXT"),
            ):
                if name not in candidate_columns:
                    c.execute(
                        f"ALTER TABLE recommendation_candidates ADD COLUMN {name} {definition}"
                    )
            c.executescript("""
            CREATE TABLE IF NOT EXISTS recommendation_feedback_events(
              id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL
                REFERENCES recommendation_candidates(id),
              decision TEXT NOT NULL, reviewer_id TEXT NOT NULL,
              reason TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_recommendation_feedback_candidate
              ON recommendation_feedback_events(candidate_id,created_at);
            CREATE TRIGGER IF NOT EXISTS recommendation_feedback_events_no_update
              BEFORE UPDATE ON recommendation_feedback_events
              BEGIN SELECT RAISE(ABORT,'Recommendation feedback events are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS recommendation_feedback_events_no_delete
              BEFORE DELETE ON recommendation_feedback_events
              BEGIN SELECT RAISE(ABORT,'Recommendation feedback events are immutable'); END;
            """)
            c.executescript("""
            CREATE TABLE IF NOT EXISTS recommendation_evaluation_snapshots(
              id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
              evaluation_version TEXT NOT NULL, input_fingerprint TEXT NOT NULL,
              status TEXT NOT NULL, selected_count INTEGER NOT NULL,
              measured_count INTEGER NOT NULL, holdout_run_count INTEGER NOT NULL,
              holdout_score_spearman REAL, holdout_rank_spearman REAL,
              result_json TEXT NOT NULL,
              UNIQUE(evaluation_version,input_fingerprint)
            );
            CREATE INDEX IF NOT EXISTS idx_recommendation_evaluation_created
              ON recommendation_evaluation_snapshots(created_at DESC);
            CREATE TRIGGER IF NOT EXISTS recommendation_evaluation_snapshots_no_update
              BEFORE UPDATE ON recommendation_evaluation_snapshots
              BEGIN SELECT RAISE(ABORT,'Recommendation evaluation snapshots are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS recommendation_evaluation_snapshots_no_delete
              BEFORE DELETE ON recommendation_evaluation_snapshots
              BEGIN SELECT RAISE(ABORT,'Recommendation evaluation snapshots are immutable'); END;
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

    def record_run(self, region, items, generated_at=None):
        timestamp = generated_at or _now()
        run_id = str(uuid.uuid4())
        rows = []
        for rank, item in enumerate(items or [], start=1):
            trend = item.get("trend") or {}
            best = item.get("best_brand") or {}
            candidates = item.get("brand_candidates") or ([best] if best else [])
            trend_id = str(trend.get("id") or "")
            if not trend_id:
                continue
            for candidate in candidates:
                brand_slug = str(candidate.get("brand") or "")
                brand_name = str(candidate.get("brand_name") or "")
                if not brand_slug or not brand_name:
                    continue
                rows.append((
                    str(uuid.uuid4()), run_id, trend_id,
                    str(trend.get("title") or "")[:500],
                    str(trend.get("region") or ""),
                    brand_slug, brand_name, rank,
                    float(item.get("recommendation_score") or 0),
                    json.dumps(item.get("score_breakdown") or {}, ensure_ascii=False,
                               sort_keys=True),
                    json.dumps(candidate.get("comparable_cohort_performance") or {},
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
                candidate_rows = c.execute("""
                    SELECT id,trend_id,brand_slug FROM recommendation_candidates
                    WHERE run_id=? ORDER BY recommendation_rank,brand_slug
                """, (previous["id"],)).fetchall()
                return {
                    "run_id": previous["id"],
                    "recorded_candidates": int(previous["candidate_count"]),
                    "candidate_ids": [
                        {"candidate_id": row["id"], "trend_id": row["trend_id"],
                         "brand_slug": row["brand_slug"]}
                        for row in candidate_rows
                    ],
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
            c.execute("""DELETE FROM recommendation_candidates
                WHERE selected_job_id IS NULL AND decision IS NULL AND created_at<?""",
                (retention_cutoff,))
            c.execute("""DELETE FROM recommendation_runs
                WHERE generated_at<? AND NOT EXISTS (
                  SELECT 1 FROM recommendation_candidates c
                  WHERE c.run_id=recommendation_runs.id
                )""", (retention_cutoff,))
        return {
            "run_id": run_id, "recorded_candidates": len(rows),
            "candidate_ids": [
                {"candidate_id": row[0], "trend_id": row[2], "brand_slug": row[5]}
                for row in rows
            ],
            "deduplicated": False,
        }

    def link_production(self, trend_id, brand_slug, job_id, selected_at=None,
                        candidate_id=None):
        timestamp = selected_at or _now()
        if not candidate_id:
            return {"linked": False, "reason": "explicit_recommendation_candidate_id_required"}
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("""SELECT id FROM recommendation_candidates
                WHERE id=? AND trend_id=? AND brand_slug=? AND selected_job_id IS NULL""",
                (str(candidate_id), str(trend_id), str(brand_slug))).fetchone()
            if row is None:
                return {"linked": False, "reason": "exposed_recommendation_candidate_not_found"}
            changed = c.execute("""UPDATE recommendation_candidates
                SET selected_job_id=?,selected_at=?,decision='selected',
                    decision_reason=NULL,reviewer_id='operator',decided_at=?
                WHERE id=? AND selected_job_id IS NULL""",
                (str(job_id), timestamp, timestamp, row["id"])).rowcount
            if changed:
                c.execute("""INSERT INTO recommendation_feedback_events
                    (id,candidate_id,decision,reviewer_id,reason,created_at)
                    VALUES(?,?,'selected','operator','Production draft created from recommendation',?)""",
                    (str(uuid.uuid4()), row["id"], timestamp))
            return {"linked": bool(changed), "candidate_id": row["id"] if changed else None}

    def record_skip(self, trend_id, brand_slug, reviewer_id, reason="", decided_at=None,
                    candidate_id=None):
        timestamp = decided_at or _now()
        reviewer = str(reviewer_id or "").strip()
        if not reviewer:
            raise ValueError("reviewer_id is required")
        if not candidate_id:
            return {"recorded": False, "reason": "explicit_recommendation_candidate_id_required"}
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("""SELECT id,decision FROM recommendation_candidates
                WHERE id=? AND trend_id=? AND brand_slug=? AND selected_job_id IS NULL""",
                (str(candidate_id), str(trend_id), str(brand_slug))).fetchone()
            if row is None:
                return {"recorded": False, "reason": "no_matching_recommendation_exposure"}
            if row["decision"] == "skipped":
                return {"recorded": False, "reason": "already_skipped"}
            c.execute("""UPDATE recommendation_candidates
                SET decision='skipped',decision_reason=?,reviewer_id=?,decided_at=?
                WHERE id=? AND selected_job_id IS NULL""",
                (str(reason or "")[:1000], reviewer[:128], timestamp, row["id"]))
            c.execute("""INSERT INTO recommendation_feedback_events
                (id,candidate_id,decision,reviewer_id,reason,created_at)
                VALUES(?,?,'skipped',?,?,?)""",
                (str(uuid.uuid4()), row["id"], reviewer[:128],
                 str(reason or "")[:1000], timestamp))
            return {"recorded": True, "candidate_id": row["id"]}

    def latest_decision(self, trend_id, brand_slug):
        with self.db() as c:
            row = c.execute("""SELECT decision,decision_reason,reviewer_id,decided_at
                FROM recommendation_candidates
                WHERE trend_id=? AND brand_slug=?
                ORDER BY created_at DESC LIMIT 1""",
                (str(trend_id), str(brand_slug))).fetchone()
            return dict(row) if row else None

    def evaluate(self, performance):
        performance_videos = (
            performance.get("videos", []) if isinstance(performance, dict) else []
        )
        measured = {}
        for item in performance_videos:
            if not isinstance(item, dict):
                continue
            job_id = str(item.get("job_id") or "").strip()
            views_per_hour = item.get("views_per_hour")
            if (
                not job_id
                or item.get("measurement_status") != "measured"
                or isinstance(views_per_hour, bool)
                or not isinstance(views_per_hour, (int, float))
                or not math.isfinite(views_per_hour)
                or views_per_hour < 0
            ):
                continue
            # One job is one outcome. If an upstream payload repeats it, keep
            # the first eligible observation rather than silently overwriting
            # it with an order-dependent later record.
            measured.setdefault(job_id, item)
        with self.db() as c:
            rows = c.execute("""SELECT c.run_id,r.generated_at AS run_generated_at,
                c.selected_job_id,c.selected_at,c.created_at,
                c.recommendation_rank,c.recommendation_score,c.trend_id,c.brand_slug
                FROM recommendation_candidates c
                JOIN recommendation_runs r ON r.id=c.run_id
                WHERE c.selected_job_id IS NOT NULL
                ORDER BY r.generated_at,r.id,c.recommendation_rank,c.selected_job_id""").fetchall()
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
                "outcome_brand": measured[job_id].get("brand"),
                "outcome_region": measured[job_id].get("region"),
                "publication_age_bucket": measured[job_id].get("publication_age_bucket"),
                "duration_bucket": measured[job_id].get("duration_bucket"),
                "format": measured[job_id].get("format"),
                "brand": row["brand_slug"],
                "trend_id": row["trend_id"],
            })
        total_selected = len(rows)
        total_measured = len(observations)
        # Compare candidates within the same exposure and comparable outcome cohort.
        # Raw scores from different API runs, brands, regions, ages or formats are
        # not directly comparable.
        grouped = {}
        for item in observations:
            run_id = item["run_id"]
            cohort_key = (
                item.get("outcome_brand"), item.get("outcome_region"),
                item.get("publication_age_bucket"), item.get("duration_bucket"),
                item.get("format"),
            )
            if not all(
                value and value != "unknown"
                and not (isinstance(value, str) and value.endswith("_requested"))
                for value in cohort_key
            ):
                continue
            grouped.setdefault(run_id, {}).setdefault(cohort_key, []).append(item)
        run_diagnostics = []
        eligible_cohort_count = 0
        for run_id, cohorts in grouped.items():
            cohort_score_rhos = []
            cohort_rank_rhos = []
            cohort_sample_count = 0
            for cohort_items in cohorts.values():
                if len(cohort_items) < 3:
                    continue
                score_rho = _spearman(
                    [item["recommendation_score"] for item in cohort_items],
                    [item["views_per_hour"] for item in cohort_items],
                )
                rank_rho = _spearman(
                    [-item["recommendation_rank"] for item in cohort_items],
                    [item["views_per_hour"] for item in cohort_items],
                )
                if score_rho is None or rank_rho is None:
                    continue
                cohort_score_rhos.append(score_rho)
                cohort_rank_rhos.append(rank_rho)
                cohort_sample_count += len(cohort_items)
                eligible_cohort_count += 1
            if cohort_score_rhos:
                run_diagnostics.append({
                    "run_id": run_id,
                    "generated_at": next(iter(cohorts.values()))[0]["run_generated_at"],
                    "eligible_cohort_count": len(cohort_score_rhos),
                    "selected_measured_count": cohort_sample_count,
                    "median_score_views_spearman": round(
                        statistics.median(cohort_score_rhos), 4
                    ),
                    "median_rank_views_spearman": round(
                        statistics.median(cohort_rank_rhos), 4
                    ),
                })
        run_diagnostics.sort(key=lambda item: item["generated_at"])
        within_run = {
            "status": "insufficient_run_coverage",
            "method": "within_exposure_comparable_cohort_spearman_chronological_holdout",
            "eligible_run_count": len(run_diagnostics),
            "eligible_cohort_count": eligible_cohort_count,
            "minimum_selected_measured_per_cohort": 3,
            "pre_holdout_run_count": 0,
            "holdout_run_count": 0,
            "holdout_median_score_views_spearman": None,
            "holdout_median_rank_views_spearman": None,
            "holdout_positive_score_association_share": None,
            "score_adjustment_enabled": False,
            "reason": (
                "At least five recommendation exposure runs with one comparable "
                "brand/region/publication-age/duration/format cohort containing three "
                "or more selected and measured candidates each are required."
            ),
        }
        if len(run_diagnostics) >= 5:
            run_split = max(2, int(math.ceil(len(run_diagnostics) * 0.30)))
            run_split = min(run_split, len(run_diagnostics) - 2)
            run_holdout = run_diagnostics[-run_split:]
            score_values = [
                item["median_score_views_spearman"] for item in run_holdout
            ]
            rank_values = [
                item["median_rank_views_spearman"] for item in run_holdout
            ]
            within_run.update({
                "status": "holdout_available",
                "pre_holdout_run_count": len(run_diagnostics) - run_split,
                "holdout_run_count": run_split,
                "holdout_start": run_holdout[0]["generated_at"],
                "holdout_end": run_holdout[-1]["generated_at"],
                "holdout_median_score_views_spearman": round(
                    statistics.median(score_values), 4
                ),
                "holdout_median_rank_views_spearman": round(
                    statistics.median(rank_values), 4
                ),
                "holdout_positive_score_association_share": round(
                    sum(value > 0 for value in score_values) / len(score_values), 4
                ),
                "reason": (
                    "Within-run, comparable-cohort holdout compares selected measured "
                    "candidates only. It remains observational and selection-biased; "
                    "no score change is enabled."
                ),
            })
        with self.db() as c:
            feedback_rows = c.execute(
                "SELECT decision,COUNT(*) AS count FROM recommendation_candidates "
                "WHERE decision IS NOT NULL GROUP BY decision"
            ).fetchall()
            feedback_counts = {row["decision"]: int(row["count"]) for row in feedback_rows}
            undecided_count = int(c.execute(
                "SELECT COUNT(*) FROM recommendation_candidates WHERE decision IS NULL"
            ).fetchone()[0])
        feedback_total = feedback_counts.get("selected", 0) + feedback_counts.get("skipped", 0)
        feedback_summary = {
            "selected_count": feedback_counts.get("selected", 0),
            "skipped_count": feedback_counts.get("skipped", 0),
            "undecided_count": undecided_count,
            "selection_rate": (
                round(feedback_counts.get("selected", 0) / feedback_total, 4)
                if feedback_total else None
            ),
            "interpretation": "Human selection/skip feedback only; not a platform performance metric.",
        }
        fingerprint_payload = [
            {
                "job_id": item["job_id"], "run_id": item["run_id"],
                "run_generated_at": item["run_generated_at"],
                "recommendation_rank": item["recommendation_rank"],
                "recommendation_score": item["recommendation_score"],
                "views_per_hour": item["views_per_hour"],
                "brand": item["brand"], "region": item.get("outcome_region"),
                "publication_age_bucket": item.get("publication_age_bucket"),
                "duration_bucket": item.get("duration_bucket"),
                "format": item.get("format"),
            }
            for item in observations
        ]
        input_fingerprint = hashlib.sha256(json.dumps(
            {
                "selected_count": total_selected,
                "measured_count": total_measured,
                "feedback_summary": feedback_summary,
                "observations": fingerprint_payload,
            },
            ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        result = {
            "feedback_summary": feedback_summary,
            "evaluation_version": "run_isolated_holdout_v2",
            "input_fingerprint": input_fingerprint,
            "status": "insufficient_data",
            "method": "chronological_exposure_run_70_30_holdout_spearman",
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
        run_groups = {}
        for item in observations:
            run_groups.setdefault(item["run_id"], []).append(item)
        ordered_runs = list(run_groups.items())
        if len(ordered_runs) < 5:
            result.update({
                "status": "insufficient_run_coverage",
                "reason": (
                    "At least five distinct recommendation exposure runs are required; "
                    "an exposure run is never split between training and holdout."
                ),
                "distinct_exposure_run_count": len(ordered_runs),
                "ranking_score_adjustment_enabled": False,
            })
            return result
        holdout_run_count = max(2, int(math.ceil(len(ordered_runs) * 0.30)))
        holdout_run_count = min(holdout_run_count, len(ordered_runs) - 2)
        pre_holdout_runs = ordered_runs[:-holdout_run_count]
        holdout_runs = ordered_runs[-holdout_run_count:]
        pre_holdout = [item for _, items in pre_holdout_runs for item in items]
        holdout = [item for _, items in holdout_runs for item in items]
        pre_score_rho = _spearman(
            [item["recommendation_score"] for item in pre_holdout],
            [item["views_per_hour"] for item in pre_holdout],
        )
        holdout_score_rho = _spearman(
            [item["recommendation_score"] for item in holdout],
            [item["views_per_hour"] for item in holdout],
        )
        pre_rank_rho = _spearman(
            [-item["recommendation_rank"] for item in pre_holdout],
            [item["views_per_hour"] for item in pre_holdout],
        )
        holdout_rank_rho = _spearman(
            [-item["recommendation_rank"] for item in holdout],
            [item["views_per_hour"] for item in holdout],
        )
        direction = (
            "consistent_positive" if pre_score_rho is not None and holdout_score_rho is not None
            and pre_score_rho > 0 and holdout_score_rho > 0
            else "direction_changed" if pre_score_rho is not None and holdout_score_rho is not None
            and (pre_score_rho > 0) != (holdout_score_rho > 0)
            else "inconclusive"
        )
        result.update({
            "status": "holdout_available",
            "distinct_exposure_run_count": len(ordered_runs),
            "pre_holdout_run_count": len(pre_holdout_runs),
            "holdout_run_count": len(holdout_runs),
            "pre_holdout_count": len(pre_holdout),
            "holdout_count": len(holdout),
            "pre_holdout_start": pre_holdout[0]["observed_at"],
            "pre_holdout_end": pre_holdout[-1]["observed_at"],
            "holdout_start": holdout[0]["observed_at"],
            "holdout_end": holdout[-1]["observed_at"],
            "pre_holdout_score_views_spearman": pre_score_rho,
            "holdout_score_views_spearman": holdout_score_rho,
            "pre_holdout_rank_views_spearman": pre_rank_rho,
            "holdout_rank_views_spearman": holdout_rank_rho,
            "score_association_stability": direction,
            "holdout_run_ids": [run_id for run_id, _ in holdout_runs],
            "holdout_scope": "Selected recommendations with measured snapshot-derived views/hour; complete exposure runs held out chronologically.",
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

    def record_evaluation_snapshot(self, result):
        """Persist one immutable evaluation result per distinct measured input set."""
        if not isinstance(result, dict) or not result.get("input_fingerprint"):
            raise ValueError("A fingerprinted evaluation result is required")
        version = str(result.get("evaluation_version") or "run_isolated_holdout_v2")
        fingerprint = str(result["input_fingerprint"])
        snapshot_id = str(uuid.uuid4())
        created_at = _now()
        payload = json.dumps(result, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False)
        within = result.get("within_run_validation") or {}
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            existing = c.execute("""SELECT id,created_at FROM recommendation_evaluation_snapshots
                WHERE evaluation_version=? AND input_fingerprint=?""",
                (version, fingerprint)).fetchone()
            if existing:
                return {"snapshot_id": existing["id"], "created_at": existing["created_at"],
                        "deduplicated": True, "input_fingerprint": fingerprint}
            c.execute("""INSERT INTO recommendation_evaluation_snapshots
                (id,created_at,evaluation_version,input_fingerprint,status,
                 selected_count,measured_count,holdout_run_count,
                 holdout_score_spearman,holdout_rank_spearman,result_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (snapshot_id, created_at, version, fingerprint,
                 str(result.get("status") or "unknown"),
                 int(result.get("selected_production_count") or 0),
                 int(result.get("measured_outcome_count") or 0),
                 int(result.get("holdout_run_count") or within.get("holdout_run_count") or 0),
                 result.get("holdout_score_views_spearman"),
                 result.get("holdout_rank_views_spearman"), payload))
        return {"snapshot_id": snapshot_id, "created_at": created_at,
                "deduplicated": False, "input_fingerprint": fingerprint}

    def list_evaluation_snapshots(self, limit=20):
        bounded = max(1, min(50, int(limit)))
        with self.db() as c:
            rows = c.execute("""SELECT id,created_at,evaluation_version,
                input_fingerprint,status,selected_count,measured_count,
                holdout_run_count,holdout_score_spearman,holdout_rank_spearman
                FROM recommendation_evaluation_snapshots
                ORDER BY created_at DESC,id DESC LIMIT ?""", (bounded,)).fetchall()
        return {"items": [dict(row) for row in rows], "count": len(rows),
                "limit": bounded, "immutable": True}


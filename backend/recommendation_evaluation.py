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


def _finite_nonnegative(value):
    """Normalize a finite nonnegative numeric metric, excluding booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _normalized_ratio(value):
    number = _finite_nonnegative(value)
    return number if number is not None and number <= 1 else None


def _normalized_dimension(value, max_length=120):
    """Accept bounded scalar labels only; malformed containers cannot become cohort keys."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > max_length:
        return None
    return value

def _normalized_timestamp(value, field_name):
    """Validate an ISO-8601 timestamp and normalize naive values to UTC."""
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        raise ValueError(f"{field_name} must be a valid ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{field_name} must be a valid ISO-8601 timestamp") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


def _json_safe(value):
    """Return JSON-safe metadata, replacing unsupported/non-finite leaves with null."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
            if isinstance(key, (str, int, float, bool))
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return None


def _normalized_outcome(item):
    """Copy only validated analytics fields into an evaluation-safe outcome."""
    if not isinstance(item, dict):
        return None
    normalized = dict(item)
    normalized["job_id"] = _normalized_dimension(item.get("job_id"), 160)
    normalized["platform"] = _normalized_dimension(item.get("platform", "youtube"), 20)
    for field in (
        "brand", "region", "publication_age_bucket", "duration_bucket", "format"
    ):
        normalized[field] = _normalized_dimension(item.get(field))
    normalized["views_per_hour"] = _finite_nonnegative(item.get("views_per_hour"))
    normalized["engaged_view_share"] = _normalized_ratio(item.get("engaged_view_share"))
    normalized["average_view_percentage"] = _finite_nonnegative(
        item.get("average_view_percentage")
    )
    normalized["average_view_duration_seconds"] = _finite_nonnegative(
        item.get("average_view_duration_seconds")
    )
    curve = []
    for point in item.get("audience_retention_curve", []):
        if not isinstance(point, dict):
            continue
        elapsed = _normalized_ratio(point.get("elapsed_video_time_ratio"))
        audience = _normalized_ratio(point.get("audience_watch_ratio"))
        if elapsed is not None and audience is not None:
            curve.append({
                "elapsed_video_time_ratio": elapsed,
                "audience_watch_ratio": audience,
            })
    normalized["audience_retention_curve"] = curve
    return normalized


def _retention_at(curve, target):
    """Return nearest valid source-reported audience ratio at a video-time ratio."""
    candidates = []
    for point in curve if isinstance(curve, list) else []:
        if not isinstance(point, dict):
            continue
        ratio = _normalized_ratio(point.get("elapsed_video_time_ratio"))
        value = _normalized_ratio(point.get("audience_watch_ratio"))
        if ratio is not None and value is not None:
            candidates.append((abs(ratio - target), value))
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[0])[1]


def _metric_holdout(diagnostics):
    diagnostics = sorted(diagnostics, key=lambda item: item["generated_at"])
    result = {
        "status": "insufficient_run_coverage",
        "eligible_run_count": len(diagnostics),
        "minimum_runs": 5,
        "minimum_selected_measured_per_cohort": 3,
        "pre_holdout_run_count": 0,
        "holdout_run_count": 0,
        "holdout_median_score_spearman": None,
        "holdout_median_rank_spearman": None,
        "holdout_positive_score_association_share": None,
        "score_adjustment_enabled": False,
    }
    if len(diagnostics) >= 5:
        split = max(2, int(math.ceil(len(diagnostics) * 0.30)))
        split = min(split, len(diagnostics) - 2)
        holdout = diagnostics[-split:]
        score_values = [item["median_score_spearman"] for item in holdout]
        rank_values = [item["median_rank_spearman"] for item in holdout]
        result.update({
            "status": "holdout_available",
            "pre_holdout_run_count": len(diagnostics) - split,
            "holdout_run_count": split,
            "holdout_start": holdout[0]["generated_at"],
            "holdout_end": holdout[-1]["generated_at"],
            "holdout_median_score_spearman": round(statistics.median(score_values), 4),
            "holdout_median_rank_spearman": round(statistics.median(rank_values), 4),
            "holdout_positive_score_association_share": round(
                sum(value > 0 for value in score_values) / len(score_values), 4
            ),
        })
    return result


class RecommendationEvaluationStore:
    def __init__(self, db_path="data/nexus.sqlite3"):
        self.db_path = str(db_path)
        with self.db() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS recommendation_runs(
              id TEXT PRIMARY KEY, region TEXT, generated_at TEXT NOT NULL,
              candidate_count INTEGER NOT NULL, scoring_method TEXT NOT NULL,
              platform TEXT NOT NULL DEFAULT 'youtube');
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
            if "platform" not in columns:
                c.execute("ALTER TABLE recommendation_runs ADD COLUMN platform TEXT NOT NULL DEFAULT 'youtube'")

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

    def record_run(self, region, items, generated_at=None, platform="youtube"):
        if not isinstance(platform, str) or platform not in ("youtube", "tiktok"):
            raise ValueError("platform must be youtube or tiktok")
        if region is not None:
            region = _normalized_dimension(region, 120)
            if region is None:
                raise ValueError("region must be a non-empty string of at most 120 characters")
        timestamp = _normalized_timestamp(_now() if generated_at is None else generated_at, "generated_at")
        run_id = str(uuid.uuid4())
        rows = []
        for rank, item in enumerate(items if isinstance(items, list) else [], start=1):
            if not isinstance(item, dict):
                continue
            trend = item.get("trend")
            trend = trend if isinstance(trend, dict) else {}
            best = item.get("best_brand")
            best = best if isinstance(best, dict) else {}
            trend_id = trend.get("id")
            if not isinstance(trend_id, (str, int)) or isinstance(trend_id, bool):
                continue
            trend_id = str(trend_id).strip()
            # Keep the persisted identifier compatible with the production-link
            # boundary, which accepts at most 160 characters.
            if not trend_id or len(trend_id) > 160:
                continue
            recommendation_score = _finite_nonnegative(
                item.get("recommendation_score", 0)
            )
            if recommendation_score is None:
                continue

            # Capture only well-formed selectable options and keep metadata JSON-safe.
            offered = item.get("brand_candidates")
            candidates = offered if isinstance(offered, list) else []
            if not candidates:
                candidates = [best]
            seen_brands = set()
            for candidate in candidates[:10]:
                if not isinstance(candidate, dict):
                    continue
                brand = candidate.get("brand")
                name = candidate.get("brand_name")
                if not isinstance(brand, str) or not isinstance(name, str):
                    continue
                brand_slug, brand_name = brand.strip(), name.strip()
                if (not brand_slug or not brand_name or len(brand_slug) > 160
                        or len(brand_name) > 200 or brand_slug in seen_brands):
                    continue
                seen_brands.add(brand_slug)
                score_breakdown = item.get("score_breakdown")
                score_breakdown = _json_safe(score_breakdown) if isinstance(score_breakdown, dict) else {}
                fit_score = _finite_nonnegative(candidate.get("fit_score"))
                if fit_score is not None:
                    score_breakdown["selected_brand_fit"] = fit_score
                cohort_context = candidate.get("comparable_cohort_performance")
                cohort_context = _json_safe(cohort_context) if isinstance(cohort_context, dict) else {}
                rows.append((
                    str(uuid.uuid4()), run_id, trend_id,
                    str(trend.get("title") or "")[:500],
                    str(trend.get("region") or "")[:120],
                    brand_slug, brand_name, rank,
                    recommendation_score,
                    json.dumps(score_breakdown, ensure_ascii=False, sort_keys=True, allow_nan=False),
                    json.dumps(cohort_context, ensure_ascii=False, sort_keys=True, allow_nan=False),
                    timestamp,
                ))
        signature_payload = [
            [platform, row[2], row[5], row[7], row[8], row[9], row[10]]
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
                WHERE region IS ? AND signature=? AND generated_at>=? AND platform=?
                ORDER BY generated_at DESC LIMIT 1""",
                (region, signature, cutoff, platform)).fetchone()
            if previous:
                return {
                    "run_id": previous["id"],
                    "recorded_candidates": int(previous["candidate_count"]),
                    "deduplicated": True,
                }
            c.execute("""INSERT INTO recommendation_runs
              (id,region,generated_at,candidate_count,scoring_method,signature,platform)
              VALUES(?,?,?,?,?,?,?)""",
              (run_id, region, timestamp, len(rows), "editorial_v1", signature, platform))
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

    def link_production(self, trend_id, brand_slug, job_id, selected_at=None,
                        platform="youtube", run_id=None):
        if not isinstance(platform, str) or platform not in ("youtube", "tiktok"):
            raise ValueError("platform must be youtube or tiktok")
        if not isinstance(run_id, str) or not run_id.strip() or len(run_id) > 64:
            return {"linked": False, "reason": "recommendation_run_id_required"}
        trend_id = _normalized_dimension(str(trend_id), 160) if isinstance(
            trend_id, (str, int)
        ) and not isinstance(trend_id, bool) else None
        brand_slug = _normalized_dimension(brand_slug, 160)
        job_id = _normalized_dimension(job_id, 160)
        if trend_id is None or brand_slug is None or job_id is None:
            return {"linked": False, "reason": "invalid_production_identity"}
        timestamp = _normalized_timestamp(_now() if selected_at is None else selected_at, "selected_at")
        with self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("""SELECT c.id FROM recommendation_candidates c
                JOIN recommendation_runs r ON r.id=c.run_id
                WHERE c.run_id=? AND c.trend_id=? AND c.brand_slug=?
                  AND c.selected_job_id IS NULL AND r.platform=?
                LIMIT 1""",
                (run_id, str(trend_id), str(brand_slug), platform)).fetchone()
            if row is None:
                return {"linked": False, "reason": "no_matching_candidate_in_recommendation_run"}
            changed = c.execute("""UPDATE recommendation_candidates
                SET selected_job_id=?,selected_at=?
                WHERE id=? AND selected_job_id IS NULL""",
                (str(job_id), timestamp, row["id"])).rowcount
            return {"linked": bool(changed), "candidate_id": row["id"] if changed else None,
                    "run_id": run_id}

    def evaluate(self, performance, platform="youtube"):
        if platform not in ("youtube", "tiktok"):
            raise ValueError("platform must be youtube or tiktok")
        measured = {}
        seen_performance_jobs = set()
        duplicate_performance_jobs = set()
        performance_rows = performance.get("videos", []) if isinstance(performance, dict) else []
        for raw_item in performance_rows if isinstance(performance_rows, list) else []:
            item = _normalized_outcome(raw_item)
            if item is None or item.get("platform", "youtube") != platform:
                continue
            job_id = item.get("job_id")
            if not isinstance(job_id, str) or not job_id.strip():
                continue
            # Conflicting duplicate snapshots must not be resolved by input order.
            # Exclude the job entirely so the evaluation cannot silently choose one.
            if job_id in seen_performance_jobs:
                measured.pop(job_id, None)
                duplicate_performance_jobs.add(job_id)
                continue
            seen_performance_jobs.add(job_id)
            has_views = (
                item.get("measurement_status") == "measured"
                and item["views_per_hour"] is not None
            )
            has_analytics = any(
                item.get(key) is not None
                for key in (
                    "engaged_view_share", "average_view_percentage",
                    "average_view_duration_seconds",
                )
            ) or bool(item["audience_retention_curve"])
            if has_views or has_analytics:
                measured[job_id] = item
        with self.db() as c:
            rows = c.execute("""SELECT c.run_id,r.generated_at AS run_generated_at,r.platform,
                c.selected_job_id,c.selected_at,c.created_at,
                c.recommendation_rank,c.recommendation_score,c.trend_id,c.brand_slug
                FROM recommendation_candidates c
                JOIN recommendation_runs r ON r.id=c.run_id
                WHERE c.selected_job_id IS NOT NULL AND r.platform=?
                ORDER BY r.generated_at,c.recommendation_rank,c.selected_job_id""",(platform,)).fetchall()
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
                "platform": row["platform"],
                "observed_at": row["selected_at"] or row["created_at"],
                "recommendation_rank": int(row["recommendation_rank"]),
                "recommendation_score": float(row["recommendation_score"]),
                "views_per_hour": (
                    float(measured[job_id]["views_per_hour"])
                    if isinstance(measured[job_id].get("views_per_hour"), (int, float))
                    and math.isfinite(float(measured[job_id]["views_per_hour"]))
                    and measured[job_id]["views_per_hour"] >= 0 else None
                ),
                "engaged_view_share": measured[job_id].get("engaged_view_share"),
                "average_view_percentage": measured[job_id].get("average_view_percentage"),
                "average_view_duration_seconds": measured[job_id].get("average_view_duration_seconds"),
                "audience_watch_ratio_25": _retention_at(
                    measured[job_id].get("audience_retention_curve"), 0.25
                ),
                "audience_watch_ratio_50": _retention_at(
                    measured[job_id].get("audience_retention_curve"), 0.50
                ),
                "audience_watch_ratio_75": _retention_at(
                    measured[job_id].get("audience_retention_curve"), 0.75
                ),
                "outcome_brand": measured[job_id].get("brand"),
                "outcome_region": measured[job_id].get("region"),
                "publication_age_bucket": measured[job_id].get("publication_age_bucket"),
                "duration_bucket": measured[job_id].get("duration_bucket"),
                "format": measured[job_id].get("format"),
                "brand": row["brand_slug"],
                "trend_id": row["trend_id"],
            })
        total_selected = len(rows)
        view_observations = [
            item for item in observations
            if isinstance(item.get("views_per_hour"), (int, float))
        ]
        total_measured = len(view_observations)
        analytics_metric_names = (
            "engaged_view_share", "average_view_percentage", "average_view_duration_seconds",
            "audience_watch_ratio_25", "audience_watch_ratio_50",
            "audience_watch_ratio_75",
        )
        analytics_measured = [
            item for item in observations
            if any(isinstance(item.get(name), (int, float)) for name in analytics_metric_names)
        ]
        # Compare candidates within the same exposure and comparable outcome cohort.
        # Raw scores from different API runs, brands, regions, ages or formats are
        # not directly comparable.
        grouped = {}
        for item in observations:
            run_id = item["run_id"]
            cohort_key = (
                item.get("platform"), item.get("outcome_brand"), item.get("outcome_region"),
                item.get("publication_age_bucket"), item.get("duration_bucket"),
                item.get("format"),
            )
            if not all(value and value != "unknown" for value in cohort_key):
                continue
            grouped.setdefault(run_id, {}).setdefault(cohort_key, []).append(item)
        run_diagnostics = []
        eligible_cohort_count = 0
        analytics_run_diagnostics = {name: [] for name in analytics_metric_names}
        for run_id, cohorts in grouped.items():
            cohort_score_rhos = []
            cohort_rank_rhos = []
            cohort_sample_count = 0
            metric_run = {
                name: {"score": [], "rank": [], "samples": 0}
                for name in analytics_metric_names
            }
            for cohort_items in cohorts.values():
                view_items = [
                    item for item in cohort_items
                    if isinstance(item.get("views_per_hour"), (int, float))
                ]
                if len(view_items) >= 3:
                    score_rho = _spearman(
                        [item["recommendation_score"] for item in view_items],
                        [item["views_per_hour"] for item in view_items],
                    )
                    rank_rho = _spearman(
                        [-item["recommendation_rank"] for item in view_items],
                        [item["views_per_hour"] for item in view_items],
                    )
                    if score_rho is not None and rank_rho is not None:
                        cohort_score_rhos.append(score_rho)
                        cohort_rank_rhos.append(rank_rho)
                        cohort_sample_count += len(view_items)
                        eligible_cohort_count += 1
                for metric_name in analytics_metric_names:
                    metric_items = [
                        item for item in cohort_items
                        if isinstance(item.get(metric_name), (int, float))
                        and math.isfinite(float(item[metric_name]))
                        and item[metric_name] >= 0
                    ]
                    if len(metric_items) < 3:
                        continue
                    score_rho = _spearman(
                        [item["recommendation_score"] for item in metric_items],
                        [item[metric_name] for item in metric_items],
                    )
                    rank_rho = _spearman(
                        [-item["recommendation_rank"] for item in metric_items],
                        [item[metric_name] for item in metric_items],
                    )
                    if score_rho is not None and rank_rho is not None:
                        metric_run[metric_name]["score"].append(score_rho)
                        metric_run[metric_name]["rank"].append(rank_rho)
                        metric_run[metric_name]["samples"] += len(metric_items)
            generated_at = next(iter(cohorts.values()))[0]["run_generated_at"]
            if cohort_score_rhos:
                run_diagnostics.append({
                    "run_id": run_id,
                    "generated_at": generated_at,
                    "eligible_cohort_count": len(cohort_score_rhos),
                    "selected_measured_count": cohort_sample_count,
                    "median_score_views_spearman": round(
                        statistics.median(cohort_score_rhos), 4
                    ),
                    "median_rank_views_spearman": round(
                        statistics.median(cohort_rank_rhos), 4
                    ),
                })
            for metric_name, values in metric_run.items():
                if values["score"]:
                    analytics_run_diagnostics[metric_name].append({
                        "generated_at": generated_at,
                        "median_score_spearman": round(
                            statistics.median(values["score"]), 4
                        ),
                        "median_rank_spearman": round(
                            statistics.median(values["rank"]), 4
                        ),
                        "selected_measured_count": values["samples"],
                    })
        analytics_validation = {
            metric_name: _metric_holdout(diagnostics)
            for metric_name, diagnostics in analytics_run_diagnostics.items()
        }
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
                "At least five recommendation exposure runs on the selected platform with one comparable "
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
        result = {
            "status": "insufficient_data",
            "platform": platform,
            "method": "chronological_70_30_holdout_spearman",
            "selected_production_count": total_selected,
            "measured_outcome_count": total_measured,
            "analytics_measured_outcome_count": len(analytics_measured),
            "any_metric_measured_outcome_count": len(observations),
            "unmeasured_selected_count": max(0, total_selected - len(observations)),
            "pre_holdout_count": 0,
            "holdout_count": 0,
            "holdout_score_views_spearman": None,
            "holdout_rank_views_spearman": None,
            "ranking_score_adjustment_enabled": False,
            "within_run_validation": within_run,
            "analytics_outcome_validation": analytics_validation,
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
        pre_holdout = view_observations[:-split]
        holdout = view_observations[-split:]
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

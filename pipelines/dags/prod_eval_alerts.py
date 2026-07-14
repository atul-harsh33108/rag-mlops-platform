"""prod_eval_alerts DAG (M7): 7-day rolling faithfulness regression alert.

The app samples 5% of /chat traffic and writes LLM-judge faithfulness + answer_relevancy
scores to sampled_evals (and onto Langfuse traces). This DAG rolls those up daily:

  current  = avg faithfulness over the last 7 days
  baseline = avg faithfulness over the prior 7 days (days 8-14)

If `current` drops below `baseline` by more than RELATIVE_DROP_THRESHOLD (relative %),
fire an Alertmanager alert + write a regression_alerts row. This is the production-sampled
counterpart to the nightly full-RAGAS gate (eval-nightly.yml): it catches regressions that
slip past the golden set because they only show up on real traffic.

answer_relevancy is tracked the same way (metric='answer_relevancy_drop') so a retrieval
regression (good answers to the WRONG questions) is caught separately from grounding loss.
"""

from __future__ import annotations

import json
from datetime import datetime

import httpx
import psycopg
from airflow.sdk import DAG, task
from pipelines.dags.assets import ALERTMANAGER_WEBHOOK, DATABASE_URL

# Relative drop that fires an alert: current < baseline * (1 - RELATIVE_DROP_THRESHOLD).
RELATIVE_DROP_THRESHOLD = 0.10  # 10% relative
MIN_SAMPLE = 20  # don't alert on tiny samples (noise)


with DAG(
    dag_id="prod_eval_alerts",
    schedule="23 4 * * *",  # daily 04:23 UTC
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["mlops", "m7", "eval"],
) as dag:

    @task
    def rollup() -> dict:
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  AVG(faithfulness)        AS faith,
                  AVG(answer_relevancy)    AS relev,
                  COUNT(*)                 AS n
                FROM sampled_evals
                WHERE sampled_at >= now() - interval '7 days'
                  AND faithfulness IS NOT NULL
                """
            )
            cur_row = cur.fetchone()
            cur_faith, cur_rel, cur_n = cur_row
            cur.execute(
                """
                SELECT
                  AVG(faithfulness)        AS faith,
                  AVG(answer_relevancy)    AS relev
                FROM sampled_evals
                WHERE sampled_at >= now() - interval '14 days'
                  AND sampled_at <  now() - interval '7 days'
                  AND faithfulness IS NOT NULL
                """
            )
            base_row = cur.fetchone()
            base_faith, base_rel = base_row
        return {
            "current_faithfulness": float(cur_faith) if cur_faith is not None else None,
            "baseline_faithfulness": float(base_faith) if base_faith is not None else None,
            "current_relevancy": float(cur_rel) if cur_rel is not None else None,
            "baseline_relevancy": float(base_rel) if base_rel is not None else None,
            "sample_n": int(cur_n or 0),
        }

    @task
    def evaluate(stats: dict) -> dict:
        alerts = []
        if stats["sample_n"] < MIN_SAMPLE:
            print(f"insufficient samples ({stats['sample_n']} < {MIN_SAMPLE}); skipping")
            return {"fired": 0, "sample_n": stats["sample_n"]}

        def _check(metric: str, current: float | None, baseline: float | None) -> dict | None:
            if current is None or baseline is None or baseline <= 0:
                return None
            drop_pct = (baseline - current) / baseline * 100.0
            if (baseline - current) > RELATIVE_DROP_THRESHOLD * baseline:
                return {
                    "metric": metric,
                    "current": current,
                    "baseline": baseline,
                    "drop_pct": round(drop_pct, 2),
                }
            return None

        for m in (
            _check(
                "faithfulness_drop",
                stats["current_faithfulness"],
                stats["baseline_faithfulness"],
            ),
            _check(
                "answer_relevancy_drop",
                stats["current_relevancy"],
                stats["baseline_relevancy"],
            ),
        ):
            if m:
                alerts.append(m)

        if not alerts:
            print(
                f"no regression; faith={stats['current_faithfulness']} "
                f"vs base={stats['baseline_faithfulness']}"
            )
            return {"fired": 0, "sample_n": stats["sample_n"]}

        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            for a in alerts:
                cur.execute(
                    """
                    INSERT INTO regression_alerts (metric, window_value, baseline_value, drop_pct)
                    VALUES (%(m)s, %(w)s, %(b)s, %(d)s)
                    """,
                    {"m": a["metric"], "w": a["current"], "b": a["baseline"], "d": a["drop_pct"]},
                )
            conn.commit()

        am_alerts = [
            {
                "labels": {"alertname": "RagFaithfulnessDrop", "severity": "critical"},
                "annotations": {
                    "summary": (
                        f"{a['metric']}: {a['current']:.3f} vs baseline "
                        f"{a['baseline']:.3f} (-{a['drop_pct']}%)"
                    ),
                    "current": str(a["current"]),
                    "baseline": str(a["baseline"]),
                },
            }
            for a in alerts
        ]
        try:
            httpx.post(ALERTMANAGER_WEBHOOK, json=am_alerts, timeout=10.0).raise_for_status()
        except Exception as e:
            print(f"alertmanager post failed: {e}")
        print(json.dumps(am_alerts))
        return {"fired": len(alerts), "sample_n": stats["sample_n"]}

    evaluate(rollup())

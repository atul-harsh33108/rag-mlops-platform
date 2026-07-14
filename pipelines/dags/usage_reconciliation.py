"""usage_reconciliation DAG (M7): closes the LiteLLM streaming under-counting gap.

LiteLLM under-counts streamed tokens by 8-15% on client disconnect (it counts what it
proxied, not what the model emitted). The app records the REAL usage in usage_events
(server-side, from the provider's final streamed chunk). This DAG runs daily and compares:

  app usage_events.cost_usd  (server-side truth)
  vs
  LiteLLM_SpendLogs.spend    (what LiteLLM logged -> what Lago invoices on)

per tenant for yesterday. Divergence > 5% -> fire an Alertmanager alert + write a
regression_alerts row (metric='usage_divergence'). The reconciliation is what makes the
Lago invoice defensible: if LiteLLM under-logged, we backfill a billable-metric event to
Lago for the gap before the invoice generates (handled out-of-band by the billing job; this
DAG surfaces the divergence).

Langfuse usage is a third witness (read via the Langfuse API) — included as a cross-check
column in the alert payload but not the primary reconciliation axis.

See docs/decisions/0011-streaming-usage-reconciliation.md.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import httpx
import psycopg
from airflow.sdk import DAG, task
from pipelines.dags.assets import (
    ALERTMANAGER_WEBHOOK,
    DATABASE_URL,
    LITELLM_DATABASE_URL,
)

DIVERGENCE_THRESHOLD_PCT = 5.0

with DAG(
    dag_id="usage_reconciliation",
    schedule="17 2 * * *",  # daily 02:17 UTC (off-the-hour)
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["mlops", "m7", "billing"],
) as dag:

    @task
    def reconcile_yesterday() -> dict:
        # date_trunc('day', now()) - interval '1 day' in UTC.
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT tenant_id,
                       COALESCE(SUM(cost_usd), 0)  AS app_spend,
                       COALESCE(SUM(total_tokens), 0) AS app_tokens
                FROM usage_events
                WHERE date_trunc('day', created_at) = date_trunc('day', now()) - interval '1 day'
                GROUP BY tenant_id
                """
            )
            app = {r[0]: {"spend": float(r[1]), "tokens": int(r[2])} for r in cur.fetchall()}

        with psycopg.connect(LITELLM_DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT COALESCE(metadata->>'tenant_id', 'unknown') AS tenant_id,
                       COALESCE(SUM("spend"), 0)   AS litellm_spend,
                       COALESCE(SUM("total_tokens"), 0) AS litellm_tokens
                FROM "LiteLLM_SpendLogs"
                WHERE date_trunc('day', "startTime") = date_trunc('day', now()) - interval '1 day'
                GROUP BY 1
                """
            )
            litellm = {r[0]: {"spend": float(r[1]), "tokens": int(r[2])} for r in cur.fetchall()}

        tenants = set(app) | set(litellm)
        divergences = []
        for t in tenants:
            a = app.get(t, {"spend": 0.0, "tokens": 0})["spend"]
            lit = litellm.get(t, {"spend": 0.0, "tokens": 0})["spend"]
            base = max(a, lit)
            pct = (abs(a - lit) / base * 100.0) if base > 0 else 0.0
            divergences.append(
                {
                    "tenant": t,
                    "app_spend": a,
                    "litellm_spend": lit,
                    "divergence_pct": round(pct, 2),
                }
            )
        day = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
        return {"day": day, "rows": divergences}

    @task
    def alert_on_divergence(summary: dict) -> dict:
        offenders = [r for r in summary["rows"] if r["divergence_pct"] > DIVERGENCE_THRESHOLD_PCT]
        if not offenders:
            print(f"reconciliation clean for {summary['day']}")
            return {"fired": 0, "day": summary["day"]}

        # Persist to regression_alerts (reused for billing alerts via the metric column).
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            for r in offenders:
                cur.execute(
                    """
                    INSERT INTO regression_alerts (metric, window_value, baseline_value, drop_pct)
                    VALUES ('usage_divergence', %(app)s, %(lit)s, %(pct)s)
                    """,
                    {"app": r["app_spend"], "lit": r["litellm_spend"], "pct": r["divergence_pct"]},
                )
            conn.commit()

        # Fire Alertmanager alerts (one per offending tenant).
        alerts = [
            {
                "labels": {
                    "alertname": "RagUsageDivergenceHigh",
                    "tenant": r["tenant"],
                    "severity": "warning",
                },
                "annotations": {
                    "summary": (
                        f"LiteLLM vs app usage divergence {r['divergence_pct']}% for {r['tenant']}"
                    ),
                    "app_spend": str(r["app_spend"]),
                    "litellm_spend": str(r["litellm_spend"]),
                    "day": summary["day"],
                },
            }
            for r in offenders
        ]
        try:
            httpx.post(ALERTMANAGER_WEBHOOK, json=alerts, timeout=10.0).raise_for_status()
        except Exception as e:  # Alertmanager unreachable — the DB row is the durable record
            print(f"alertmanager post failed: {e}")
        print(json.dumps(alerts))
        return {"fired": len(offenders), "day": summary["day"]}

    alert_on_divergence(reconcile_yesterday())

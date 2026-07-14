"use client";

import { useEffect, useState } from "react";

interface PlanSummary {
  tenant_id: string;
  plan: string;
  monthly_budget_usd: number;
  cap_usd: number;
  spent_usd: number;
  remaining_usd: number;
  rate_limit_per_minute: number;
}

interface Usage {
  tenant_id: string;
  month: string;
  request_count: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: number;
  estimated_frac: number;
  by_model: { model: string; request_count: number; total_tokens: number; cost_usd: number }[];
}

interface Forecast {
  tenant_id: string;
  spent_usd: number;
  projected_month_end_usd: number;
  days_elapsed: number;
  days_in_month: number;
}

export default function AdminPage() {
  const [plan, setPlan] = useState<PlanSummary | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const results = await Promise.all([
        fetch("/api/admin/plan").then((r) => (r.ok ? r.json() : Promise.reject(r.status))),
        fetch("/api/admin/usage").then((r) => (r.ok ? r.json() : Promise.reject(r.status))),
        fetch("/api/admin/usage/forecast").then((r) => (r.ok ? r.json() : Promise.reject(r.status))),
      ]);
      setPlan(results[0]);
      setUsage(results[1]);
      setForecast(results[2]);
    })().catch((e) => setErr(`failed to load admin data (${e})`));
  }, []);

  const pct = plan && plan.cap_usd > 0 ? Math.min(100, (plan.spent_usd / plan.cap_usd) * 100) : 0;
  const over = plan ? plan.spent_usd >= plan.cap_usd : false;

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <h1 className="text-xl font-semibold mb-1">Billing &amp; usage</h1>
      <p className="text-sm text-[oklch(0.45_0.01_250)] mb-6">
        Your tenant&apos;s plan, month-to-date spend, and a linear month-end forecast.
      </p>

      {err && <p className="text-sm text-red-600 mb-4">{err}</p>}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        <Card label="Plan" value={plan?.plan ?? "—"} sub={plan ? `${plan.rate_limit_per_minute}/min` : ""} />
        <Card
          label="Spent this month"
          value={plan ? `$${plan.spent_usd.toFixed(2)}` : "—"}
          sub={plan ? `of $${plan.cap_usd.toFixed(2)} cap` : ""}
        />
        <Card
          label="Remaining"
          value={plan ? `$${plan.remaining_usd.toFixed(2)}` : "—"}
          sub={over ? "over cap — upgrade to continue" : "budget remaining"}
          danger={over}
        />
      </div>

      {plan && (
        <div className="mb-8">
          <div className="h-3 rounded-full bg-[var(--color-bg)] overflow-hidden border border-[var(--color-border)]">
            <div
              className={`h-full ${over ? "bg-red-500" : "bg-[var(--color-accent)]"}`}
              style={{ width: `${pct}%` }}
            />
          </div>
          <p className="text-xs text-[oklch(0.5_0.01_250)] mt-1">{pct.toFixed(1)}% of monthly cap</p>
        </div>
      )}

      {forecast && (
        <div className="rounded-xl border border-[var(--color-border)] p-4 mb-8">
          <p className="text-sm font-medium mb-1">Month-end forecast</p>
          <p className="text-2xl font-semibold">${forecast.projected_month_end_usd.toFixed(2)}</p>
          <p className="text-xs text-[oklch(0.5_0.01_250)] mt-1">
            ${forecast.spent_usd.toFixed(2)} spent over {forecast.days_elapsed}/{forecast.days_in_month} days
            (linear projection)
          </p>
        </div>
      )}

      {usage && (
        <div className="rounded-xl border border-[var(--color-border)] p-4">
          <div className="flex items-center justify-between mb-3">
            <p className="text-sm font-medium">Usage — {usage.month}</p>
            {usage.estimated_frac > 0.05 && (
              <span className="text-xs text-amber-600">
                {Math.round(usage.estimated_frac * 100)}% estimated (provider gave no usage)
              </span>
            )}
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4 text-sm">
            <Stat label="Requests" value={usage.request_count} />
            <Stat label="Prompt tokens" value={usage.prompt_tokens} />
            <Stat label="Completion tokens" value={usage.completion_tokens} />
            <Stat label="Cost" value={`$${usage.cost_usd.toFixed(4)}`} />
          </div>
          {usage.by_model.length > 0 && (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[oklch(0.45_0.01_250)] border-b border-[var(--color-border)]">
                  <th className="py-2">Model</th>
                  <th className="py-2 text-right">Requests</th>
                  <th className="py-2 text-right">Tokens</th>
                  <th className="py-2 text-right">Cost</th>
                </tr>
              </thead>
              <tbody>
                {usage.by_model.map((m) => (
                  <tr key={m.model} className="border-b border-[var(--color-border)]">
                    <td className="py-2 font-mono text-xs">{m.model}</td>
                    <td className="py-2 text-right">{m.request_count}</td>
                    <td className="py-2 text-right">{m.total_tokens}</td>
                    <td className="py-2 text-right">${m.cost_usd.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

function Card({ label, value, sub, danger }: { label: string; value: string; sub?: string; danger?: boolean }) {
  return (
    <div className="rounded-xl border border-[var(--color-border)] p-4">
      <p className="text-xs text-[oklch(0.45_0.01_250)]">{label}</p>
      <p className={`text-2xl font-semibold mt-1 ${danger ? "text-red-600" : ""}`}>{value}</p>
      {sub && <p className="text-xs text-[oklch(0.5_0.01_250)] mt-1">{sub}</p>}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <p className="text-xs text-[oklch(0.45_0.01_250)]">{label}</p>
      <p className="font-medium mt-0.5">{value}</p>
    </div>
  );
}
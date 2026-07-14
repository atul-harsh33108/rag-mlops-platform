"use client";

import { useEffect, useState, useTransition } from "react";

interface KeyView {
  id: number;
  tenant_id: string;
  label: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

interface CreatedKey {
  key_id: number;
  key: string; // shown once
}

export default function KeysPage() {
  const [keys, setKeys] = useState<KeyView[]>([]);
  const [label, setLabel] = useState("default");
  const [justCreated, setJustCreated] = useState<CreatedKey | null>(null);
  const [copied, setCopied] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  async function load() {
    const r = await fetch("/api/keys");
    if (r.ok) setKeys(await r.json());
    else setErr(`failed to load keys (${r.status})`);
  }

  useEffect(() => {
    load();
  }, []);

  function issue() {
    setErr(null);
    setJustCreated(null);
    startTransition(async () => {
      const r = await fetch("/api/keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label }),
      });
      if (r.ok) {
        setJustCreated(await r.json());
        await load();
      } else {
        setErr(`issue failed (${r.status})`);
      }
    });
  }

  function revoke(id: number) {
    startTransition(async () => {
      const r = await fetch(`/api/keys?id=${id}`, { method: "DELETE" });
      if (r.ok) await load();
      else setErr(`revoke failed (${r.status})`);
    });
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <h1 className="text-xl font-semibold mb-1">API keys</h1>
      <p className="text-sm text-[oklch(0.45_0.01_250)] mb-6">
        Per-tenant programmatic keys for the REST API. Plaintext is shown once — store it now.
      </p>

      {justCreated && (
        <div className="mb-6 rounded-xl border border-amber-200 bg-amber-50 p-4">
          <p className="text-sm font-medium mb-1">Key created — copy it now:</p>
          <code className="block text-xs font-mono break-all bg-white border rounded p-2">
            {justCreated.key}
          </code>
          <div className="flex gap-2 mt-2">
            <button
              type="button"
              onClick={() => {
                navigator.clipboard.writeText(justCreated.key);
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              }}
              className="text-xs px-2 py-1 rounded border border-[var(--color-border)] bg-white hover:bg-[var(--color-bg)]"
            >
              {copied ? "Copied" : "Copy"}
            </button>
            <button
              type="button"
              onClick={() => setJustCreated(null)}
              className="text-xs px-2 py-1 rounded border border-[var(--color-border)] bg-white"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          issue();
        }}
        className="flex items-end gap-2 mb-6"
      >
        <label className="text-sm flex-1">
          <span className="block text-[oklch(0.45_0.01_250)] mb-1">Label</span>
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            className="w-full rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-sm"
          />
        </label>
        <button
          type="submit"
          disabled={pending}
          className="h-9 px-4 rounded-lg bg-[var(--color-accent)] text-[var(--color-accent-fg)] text-sm font-medium disabled:opacity-50"
        >
          {pending ? "Issuing…" : "Issue key"}
        </button>
      </form>

      {err && <p className="text-sm text-red-600 mb-4">{err}</p>}

      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[oklch(0.45_0.01_250)] border-b border-[var(--color-border)]">
            <th className="py-2">Label</th>
            <th className="py-2">Created</th>
            <th className="py-2">Last used</th>
            <th className="py-2">Status</th>
            <th className="py-2"></th>
          </tr>
        </thead>
        <tbody>
          {keys.map((k) => (
            <tr key={k.id} className="border-b border-[var(--color-border)]">
              <td className="py-2">{k.label}</td>
              <td className="py-2 text-[oklch(0.5_0.01_250)]">{fmt(k.created_at)}</td>
              <td className="py-2 text-[oklch(0.5_0.01_250)]">
                {k.last_used_at ? fmt(k.last_used_at) : "—"}
              </td>
              <td className="py-2">
                {k.revoked_at ? (
                  <span className="text-[oklch(0.5_0.01_250)]">revoked</span>
                ) : (
                  <span className="text-green-600">active</span>
                )}
              </td>
              <td className="py-2 text-right">
                {!k.revoked_at && (
                  <button
                    type="button"
                    onClick={() => revoke(k.id)}
                    className="text-xs text-red-600 hover:underline disabled:opacity-50"
                    disabled={pending}
                  >
                    Revoke
                  </button>
                )}
              </td>
            </tr>
          ))}
          {keys.length === 0 && (
            <tr>
              <td colSpan={5} className="py-6 text-center text-[oklch(0.5_0.01_250)]">
                No keys yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function fmt(s: string): string {
  try {
    return new Date(s).toLocaleString();
  } catch {
    return s;
  }
}
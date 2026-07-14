/**
 * /api/admin/* — proxy to the FastAPI backend's /admin/* endpoints (M7). Same auth model as
 * /api/keys: mint a Clerk session JWT server-side and forward it; the browser never sees the
 * token. Supports GET only (the admin endpoints are read-only self-serve billing views).
 *
 *   GET /api/admin/plan            -> plan + budget + spend
 *   GET /api/admin/usage           -> this-month usage by model
 *   GET /api/admin/usage/forecast  -> month-end spend forecast
 */
import { auth } from "@clerk/nextjs/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

export const runtime = "nodejs";

export async function GET(_req: Request, ctx: { params: Promise<{ path: string[] }> }) {
  const { getToken } = await auth();
  const token = await getToken();
  if (!token) return new Response("unauthorized", { status: 401 });
  const { path } = await ctx.params;
  const r = await fetch(`${BACKEND_URL}/admin/${path.join("/")}`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  return new Response(r.body, {
    status: r.status,
    headers: { "Content-Type": "application/json" },
  });
}
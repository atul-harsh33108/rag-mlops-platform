/**
 * /api/keys — proxy to the FastAPI backend's /keys endpoints. Same auth model as /api/chat:
 * mint a Clerk session JWT server-side and forward it; the browser never sees the token.
 *
 *   GET    /api/keys          -> list current tenant's keys (no secrets)
 *   POST   /api/keys {label}  -> issue a key (plaintext returned once, shown in UI)
 *   DELETE /api/keys/:id      -> revoke
 */
import { auth } from "@clerk/nextjs/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

export const runtime = "nodejs";

async function forward(path: string, init: RequestInit = {}) {
  const { getToken } = await auth();
  const token = await getToken();
  if (!token) {
    return new Response("unauthorized", { status: 401 });
  }
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  return fetch(`${BACKEND_URL}${path}`, { ...init, headers });
}

export async function GET() {
  const r = await forward("/keys");
  return new Response(r.body, { status: r.status, headers: { "Content-Type": "application/json" } });
}

export async function POST(req: Request) {
  const r = await forward("/keys", { method: "POST", body: await req.text() });
  return new Response(r.body, { status: r.status, headers: { "Content-Type": "application/json" } });
}

export async function DELETE(req: Request) {
  const id = new URL(req.url).searchParams.get("id");
  if (!id) return new Response("missing id", { status: 400 });
  const r = await forward(`/keys/${id}`, { method: "DELETE" });
  return new Response(r.body, { status: r.status, headers: { "Content-Type": "application/json" } });
}
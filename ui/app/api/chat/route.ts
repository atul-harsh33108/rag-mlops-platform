/**
 * /api/chat — proxy to the FastAPI RAG backend, translating its custom SSE into the
 * Vercel AI SDK UIMessage wire protocol (consumed by `useChat`/`DefaultChatTransport`).
 *
 * Why a proxy instead of calling the backend from the browser:
 *   - The Clerk session JWT never leaves the server (the browser only holds the Clerk
 *     session cookie; we mint a fresh backend JWT here via `auth().getToken()`).
 *   - We translate the backend's bespoke SSE (`event: citations|token|done`) into the AI
 *     SDK wire protocol so the frontend stays a stock `useChat` consumer.
 *   - Tenant isolation is enforced server-side: the backend resolves the tenant from the
 *     JWT (Qdrant RLS via group_id) — the client can never supply a tenant filter.
 *
 * Wire protocol emitted (header `x-vercel-ai-ui-message-stream: v1`, terminated by [DONE]):
 *   data: {"type":"source-document","sourceId":...,"mediaType":"text","title":...}   (per citation)
 *   data: {"type":"text-start","id":"msg-1"}
 *   data: {"type":"text-delta","id":"msg-1","delta":"..."}                          (per token)
 *   data: {"type":"text-end","id":"msg-1"}
 *   data: {"type":"finish"}
 *   data: [DONE]
 *
 * We build the SSE byte stream by hand rather than via `createUIMessageStream`/writer so
 * the protocol surface is fully under our control (the writer's text-part helper shapes
 * shifted across AI SDK 5→7; the wire format is the stable contract).
 */
import { auth } from "@clerk/nextjs/server";
import { type UIMessage } from "ai";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
const STREAM_HEADER = "x-vercel-ai-ui-message-stream";
// A single text block per assistant turn. AI SDK reconciles deltas by id.
const TEXT_ID = "msg-1";

interface BackendCitation {
  source: string;
  doc_id: string;
  chunk_idx: number;
  score?: number;
}

export const runtime = "nodejs";
export const maxDuration = 60;

export async function POST(req: Request) {
  const body = (await req.json()) as { messages: UIMessage[] };

  // Pull the last user message text out of the AI SDK parts structure.
  const last = body.messages[body.messages.length - 1];
  const question = extractText(last);
  if (!question) {
    return new Response("no user message", { status: 400 });
  }

  // Mint a Clerk session JWT to hand to the backend (tenant resolved from org claim).
  // When Clerk isn't configured (local dev / eval), fall back to a body tenant so the UI
  // works against the unauthenticated M1 backend.
  const { getToken } = await auth();
  const token = await getToken();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const payload: Record<string, unknown> = { question, stream: true };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  } else {
    // Local-dev fallback (matches the backend's no-auth M1 path).
    payload.tenant = process.env.LOCAL_DEV_TENANT ?? "acme";
  }

  const upstream = await fetch(`${BACKEND_URL}/chat`, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });

  if (!upstream.ok) {
    const text = await upstream.text().catch(() => "");
    return new Response(`backend error ${upstream.status}: ${text.slice(0, 200)}`, {
      status: 502,
    });
  }

  const ctype = upstream.headers.get("content-type") ?? "";
  // The backend returns SSE for streaming generations, but a plain JSON ChatResponse when the
  // semantic cache hits (chat.py returns the cached answer BEFORE the streaming branch). We
  // must handle both so cached answers don't hang the client.
  if (ctype.includes("text/event-stream") && upstream.body) {
    const stream = translate(upstream.body);
    return new Response(stream, {
      headers: {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
        [STREAM_HEADER]: "v1",
      },
    });
  }

  // JSON ChatResponse (cache hit, or stream:false): { answer, citations, cached }.
  const data = (await upstream.json()) as {
    answer?: string;
    citations?: BackendCitation[];
  };
  const answer = data.answer ?? "";
  const cites = data.citations ?? [];
  const stream = jsonToUIMessage(cites, answer);
  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      [STREAM_HEADER]: "v1",
    },
  });
}

/** Build a AI SDK UIMessage wire stream from a complete (non-streamed) JSON ChatResponse. */
function jsonToUIMessage(
  cites: BackendCitation[],
  answer: string,
): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  const part = (obj: unknown) => encoder.encode(`data: ${JSON.stringify(obj)}\n\n`);
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of cites) {
        controller.enqueue(
          part({
            type: "source-document",
            sourceId: `${c.doc_id}:${c.chunk_idx}`,
            mediaType: "text",
            title: c.source,
          }),
        );
      }
      controller.enqueue(part({ type: "text-start", id: TEXT_ID }));
      if (answer) controller.enqueue(part({ type: "text-delta", id: TEXT_ID, delta: answer }));
      controller.enqueue(part({ type: "text-end", id: TEXT_ID }));
      controller.enqueue(part({ type: "finish" }));
      controller.enqueue(encoder.encode("data: [DONE]\n\n"));
      controller.close();
    },
  });
}

function extractText(msg: UIMessage | undefined): string | undefined {
  if (!msg) return undefined;
  // AI SDK 7 user messages carry parts; prefer parts, fall back to a text field.
  const textPart = msg.parts?.find((p) => p.type === "text");
  if (textPart && textPart.type === "text") return textPart.text;
  return (msg as unknown as { text?: string }).text;
}

/**
 * Parse the backend's `event: <name>\ndata: <json>\n\n` stream and emit AI SDK wire parts.
 * Backend events: `citations` (list), `token` (string), `done` (object).
 */
function translate(backend: ReadableStream<Uint8Array>): ReadableStream<Uint8Array> {
  const decoder = new TextDecoder();
  const reader = backend.getReader();
  const encoder = new TextEncoder();

  let buffer = "";
  let textStarted = false;
  let finished = false;

  // SSE bytes for one data part.
  const part = (obj: unknown) => encoder.encode(`data: ${JSON.stringify(obj)}\n\n`);
  const done = () => encoder.encode("data: [DONE]\n\n");

  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      if (finished) {
        controller.close();
        return;
      }
      const { value, done: rdone } = await reader.read();
      if (rdone) {
        // Backend closed mid-stream — flush a finish so the client doesn't hang.
        if (textStarted) controller.enqueue(part({ type: "text-end", id: TEXT_ID }));
        if (!finished) {
          controller.enqueue(part({ type: "finish" }));
          controller.enqueue(done());
          finished = true;
        }
        controller.close();
        return;
      }
      buffer += decoder.decode(value, { stream: true });

      // SSE frames are separated by a blank line. Process complete frames.
      let nl: number;
      while ((nl = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, nl);
        buffer = buffer.slice(nl + 2);
        const evt = parseFrame(frame);
        if (!evt) continue;
        if (evt.name === "citations") {
          const cites = (evt.data as BackendCitation[]) ?? [];
          for (const c of cites) {
            controller.enqueue(
              part({
                type: "source-document",
                sourceId: `${c.doc_id}:${c.chunk_idx}`,
                mediaType: "text",
                title: c.source,
              }),
            );
          }
        } else if (evt.name === "token") {
          if (!textStarted) {
            controller.enqueue(part({ type: "text-start", id: TEXT_ID }));
            textStarted = true;
          }
          const delta = typeof evt.data === "string" ? evt.data : String(evt.data ?? "");
          controller.enqueue(part({ type: "text-delta", id: TEXT_ID, delta }));
        } else if (evt.name === "done") {
          if (textStarted) controller.enqueue(part({ type: "text-end", id: TEXT_ID }));
          controller.enqueue(part({ type: "finish" }));
          controller.enqueue(done());
          finished = true;
          controller.close();
          return;
        }
      }
    },
    cancel() {
      reader.cancel().catch(() => {});
    },
  });
}

function parseFrame(frame: string): { name: string; data: unknown } | null {
  let name = "message";
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return null;
  const raw = dataLines.join("\n");
  try {
    return { name, data: JSON.parse(raw) };
  } catch {
    return { name, data: raw };
  }
}
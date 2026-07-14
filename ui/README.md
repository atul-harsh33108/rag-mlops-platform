# RAG Platform UI

Customer-facing Next.js 16 + React 19 shell over the FastAPI RAG backend. Clerk auth
(Organizations = tenants), Vercel AI SDK 7 `useChat`, inline citation chips, a source pane,
and an API-key management page.

## Stack

- **Next.js 16.2** App Router + React 19.2
- **Vercel AI SDK 7** (`@ai-sdk/react` `useChat` + `DefaultChatTransport`) — UI message wire protocol
- **Clerk 7** (`@clerk/nextjs`) — session JWT, Organization switcher (org id → Qdrant `group_id`)
- **Tailwind v4** (CSS-first `@theme`)

## How it talks to the backend

The browser never calls FastAPI directly. Two Next.js route handlers proxy for it:

| Route | Purpose | Backend |
|---|---|---|
| `app/api/chat/route.ts` | stream grounded answers | `POST /chat` (SSE → AI SDK wire protocol) |
| `app/api/keys/route.ts` | list/issue/revoke API keys | `GET/POST/DELETE /keys` |

`/api/chat` mints a Clerk session JWT server-side (`auth().getToken()`) and forwards it as
`Authorization: Bearer <jwt>`. The backend resolves the tenant from the JWT org claim and
enforces Qdrant RLS (`group_id` filter) — the client cannot supply a tenant. When Clerk is
unconfigured (`NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` unset) the route falls back to
`LOCAL_DEV_TENANT` so the UI works against the unauthenticated M1 backend.

### SSE translation

The backend emits a bespoke SSE stream (`event: citations|token|done`). `/api/chat` parses it
and re-emits the AI SDK UIMessage **wire protocol** directly (header
`x-vercel-ai-ui-message-stream: v1`, terminated by `data: [DONE]`):

```
data: {"type":"source-document","sourceId":"doc:0","mediaType":"text","title":"…"}
data: {"type":"text-start","id":"msg-1"}
data: {"type":"text-delta","id":"msg-1","delta":"Hello"}
data: {"type":"text-end","id":"msg-1"}
data: {"type":"finish"}
data: [DONE]
```

We build the bytes by hand rather than via `createUIMessageStream`/writer so the protocol
surface is fully under our control (the writer's text-part helper shapes shifted across AI
SDK 5→7; the wire format is the stable contract).

## Run locally

```bash
cp .env.example .env        # set BACKEND_URL + Clerk keys (optional for local dev)
npm install
npm run dev                 # http://localhost:3000
```

Without Clerk keys, the UI queries the `acme` tenant against the backend's no-auth path. With
Clerk configured, sign in, pick/switch an Organization (= tenant), and ask a question —
citations render as chips above the answer and in the source pane.

## Docker

```bash
docker build -f docker/Dockerfile.ui -t mlops/ui:0.1.0 .
```

Multi-stage: `node:22-alpine` build → `node:22-alpine` runner, non-root, read-only-ish
filesystem. Standalone output (`output: "standalone"` is set in the Dockerfile via
`NEXT_PRIVATE_STANDALONE`).

## K8s / Helm

Deployed by the umbrella chart when `ui.enabled: true` (see `helm/mlops-platform/values-generic.yaml`).
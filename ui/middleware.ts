import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

/**
 * Clerk middleware: gate everything except Clerk's own handshake routes. The /api/chat +
 * /api/keys routes do their own Clerk resolution (mint a backend JWT or fall back to a dev
 * tenant), so they are public at the middleware layer.
 *
 * Note (@clerk/nextjs 7): the handler signature is `(auth, req)` — `auth` is the AuthFn
 * (with `.protect()`), NOT a context object. `protect()` is async and must be awaited.
 *
 * In local-dev without Clerk configured (NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY unset), Clerk's
 * middleware is a no-op pass-through, so the UI still talks to the unauthenticated backend.
 * Sign-in URL comes from NEXT_PUBLIC_CLERK_SIGN_IN_URL (set in .env / the Helm ConfigMap).
 */
const isPublic = createRouteMatcher([
  "/sign-in(.*)",
  "/sign-up(.*)",
  "/api/chat(.*)",
  "/api/keys(.*)",
]);

export default clerkMiddleware(async (auth, req) => {
  if (isPublic(req)) return;
  await auth.protect();
});

export const config = {
  matcher: [
    // Skip Next internals + static files; run on everything else.
    "/((?!_next|.*\\..*).*)",
    "/(api|trpc)(.*)",
  ],
};
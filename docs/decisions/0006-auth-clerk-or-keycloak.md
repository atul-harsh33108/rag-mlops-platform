# ADR 0006 — Auth: Clerk (demo) / Keycloak (self-hosted)

**Status:** Accepted

## Decision

- **Clerk** for portfolio/demo speed: drop-in Next.js components, Organizations for multi-tenant SaaS, SAML SSO on Pro ($25/mo). Clerk Organizations map 1:1 to tenants.
- **Keycloak** documented as the zero-vendor/self-hosted alternative: one realm per tenant, LDAP/AD/SCIM, no per-MAU licensing. Use when data sovereignty or >100K users matters.

## Rationale

- For a demo SaaS that must "look production-grade" with least effort, Clerk is the fastest path.
- Both integrate with the same server-side pattern: validate the JWT, read `tenant_id` claim, build the Qdrant RLS filter in `filter_builder.py`. **Clients never supply filters.**

## Consequences

- Switching Clerk → Keycloak later is localized to `app/src/app/auth/` (a validator + claim extractor per provider). The RLS path is unchanged.
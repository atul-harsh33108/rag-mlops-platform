-- API keys (M6): hashed per-tenant keys for programmatic access. The plaintext key is
-- shown ONCE at issue time; we store only the SHA-256 hash (key_hash, UNIQUE). M7 adds
-- plan scoping + spend caps; M6 keeps a single tier + soft last_used tracking.
SET TIME ZONE 'UTC';

CREATE TABLE IF NOT EXISTS tenant_api_keys (
    id           BIGSERIAL PRIMARY KEY,
    tenant_id    TEXT        NOT NULL,
    key_hash     CHAR(64)    NOT NULL UNIQUE,   -- sha256 hex
    label        TEXT        NOT NULL DEFAULT 'default',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ,
    revoked_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS tenant_api_keys_tenant_idx ON tenant_api_keys (tenant_id)
    WHERE revoked_at IS NULL;
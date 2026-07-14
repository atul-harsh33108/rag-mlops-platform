-- Per-tenant schema + tables created at first boot. UTC enforced by the
-- container env (TZ=UTC). Milestone 1 only needs tenants + corpus_version.
SET TIME ZONE 'UTC';

CREATE TABLE IF NOT EXISTS tenants (
    id           TEXT PRIMARY KEY,          -- maps to Qdrant payload group_id
    name         TEXT NOT NULL,
    plan         TEXT NOT NULL DEFAULT 'free',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS corpus_state (
    id              INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    corpus_version  BIGINT NOT NULL DEFAULT 1,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO corpus_state (id, corpus_version) VALUES (1, 1)
ON CONFLICT (id) DO NOTHING;

-- Seed the demo tenant so /chat works out of the box.
INSERT INTO tenants (id, name, plan) VALUES ('acme', 'Acme Demo', 'pro')
ON CONFLICT (id) DO NOTHING;
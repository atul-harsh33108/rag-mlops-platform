-- LiteLLM proxy database + role (M3). The shared `postgres` container runs this as the
-- bootstrap superuser, so role/db creation is allowed. LiteLLM auto-creates its schema
-- (LiteLLM_SpendLogs, LiteLLM_VerificationModel, etc.) on first boot against this DB.
-- Idempotent: safe on volume restarts.
SELECT format('CREATE ROLE litellm WITH LOGIN PASSWORD ''litellm''')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'litellm')\gexec

SELECT format('CREATE DATABASE litellm OWNER litellm')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'litellm')\gexec

GRANT ALL PRIVILEGES ON DATABASE litellm TO litellm;
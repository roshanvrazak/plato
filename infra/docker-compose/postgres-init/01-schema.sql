CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    api_key_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    allowed_models TEXT[] NOT NULL DEFAULT ARRAY['local-llama3']::TEXT[],
    daily_token_budget INT NOT NULL DEFAULT 100000
);

CREATE TABLE usage_log (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    request_id UUID NOT NULL DEFAULT gen_random_uuid(),
    model TEXT NOT NULL,
    input_tokens INT NOT NULL DEFAULT 0,
    output_tokens INT NOT NULL DEFAULT 0,
    cost_pence NUMERIC(10, 4) NOT NULL DEFAULT 0,
    status_code INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_usage_tenant_time ON usage_log(tenant_id, created_at DESC);
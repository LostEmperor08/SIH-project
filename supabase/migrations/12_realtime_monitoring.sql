-- =====================================================================
-- Migration 12: Real-Time Wallet Monitoring, Event Detection & Alert Engine
-- SIH 2026 Problem Statement 26183 — Chakravyuh SETU
-- =====================================================================

-- 1. Monitored Wallets Table
CREATE TABLE IF NOT EXISTS public.monitored_wallets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id TEXT NOT NULL DEFAULT 'SIH/2026/00412',
    chain TEXT NOT NULL,
    address TEXT NOT NULL,
    label TEXT,
    enabled BOOLEAN NOT NULL DEFAULT true,
    monitoring_mode TEXT NOT NULL DEFAULT 'CONTINUOUS' CHECK (monitoring_mode IN ('CONTINUOUS', 'POLLING', 'MANUAL_REFRESH')),
    last_processed_block BIGINT,
    last_processed_timestamp TIMESTAMPTZ,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_monitored_wallet UNIQUE (case_id, chain, address)
);

CREATE INDEX IF NOT EXISTS idx_monitored_wallets_enabled ON public.monitored_wallets(enabled, chain);
CREATE INDEX IF NOT EXISTS idx_monitored_wallets_case ON public.monitored_wallets(case_id);

-- 2. Monitoring Cursors Table
CREATE TABLE IF NOT EXISTS public.monitoring_cursors (
    chain TEXT NOT NULL,
    address TEXT NOT NULL,
    last_processed_block BIGINT DEFAULT 0,
    last_processed_tx_hash TEXT,
    last_processed_timestamp TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (chain, address)
);

-- 3. Alerts Table
CREATE TABLE IF NOT EXISTS public.alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id TEXT NOT NULL DEFAULT 'SIH/2026/00412',
    monitored_wallet_id UUID REFERENCES public.monitored_wallets(id) ON DELETE SET NULL,
    chain TEXT NOT NULL,
    tx_hash TEXT NOT NULL,
    idempotency_key TEXT UNIQUE NOT NULL,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    risk_score NUMERIC(5,2),
    relevance_score NUMERIC(5,2),
    attributed_value_usd NUMERIC(16,2) DEFAULT 0.00,
    attribution_share NUMERIC(6,4) DEFAULT 0.0000,
    vasp_name TEXT,
    vasp_confidence NUMERIC(5,4),
    bridge_name TEXT,
    bridge_confidence NUMERIC(5,4),
    evidence JSONB DEFAULT '[]'::jsonb,
    triggered_rules JSONB DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'NEW' CHECK (status IN ('NEW', 'ACKNOWLEDGED', 'INVESTIGATING', 'RESOLVED', 'DISMISSED')),
    suppressed BOOLEAN NOT NULL DEFAULT false,
    suppression_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    acknowledged_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    acknowledged_by TEXT,
    resolved_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_alerts_case_status ON public.alerts(case_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON public.alerts(severity, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_wallet ON public.alerts(chain, tx_hash);

-- 4. Configurable Alert Rules Catalog
CREATE TABLE IF NOT EXISTS public.alert_rules (
    rule_id TEXT PRIMARY KEY,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    enabled BOOLEAN NOT NULL DEFAULT true,
    description TEXT NOT NULL,
    conditions JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed Default Alert Rules
INSERT INTO public.alert_rules (rule_id, alert_type, severity, description, conditions) VALUES
('RULE_SANCTIONS', 'SANCTIONS_MATCH', 'CRITICAL', 'Direct verified sanctions match on wallet or transaction', '{"sanctions_required": true}'),
('RULE_CRITICAL_RISK', 'CRITICAL_TRANSACTION', 'CRITICAL', 'Transaction risk score >= 80.0', '{"min_risk_score": 80.0}'),
('RULE_HIGH_RISK', 'HIGH_RISK_TRANSACTION', 'HIGH', 'Transaction risk score >= 60.0', '{"min_risk_score": 60.0}'),
('RULE_LARGE_ATTRIBUTED_FUND', 'LARGE_REPORTED_FUND_MOVEMENT', 'HIGH', 'Attributed victim fund movement >= $1,000 USD', '{"min_attributed_usd": 1000.0}'),
('RULE_RAPID_FORWARDING', 'RAPID_FUND_FORWARDING', 'HIGH', 'Funds forwarded within 600 seconds of receipt', '{"max_forwarding_delay_sec": 600}'),
('RULE_KNOWN_EXCHANGE', 'KNOWN_EXCHANGE_REACHED', 'INFO', 'Newly monitored funds deposit into a verified crypto exchange', '{"exchange_required": true}'),
('RULE_CROSS_CHAIN_BRIDGE', 'CROSS_CHAIN_MOVEMENT', 'MEDIUM', 'Verified cross-chain bridge transfer detected', '{"bridge_required": true}'),
('RULE_MIXER_INTERACTION', 'MIXER_INTERACTION', 'HIGH', 'Direct interaction with a privacy mixer or tumbler', '{"mixer_required": true}'),
('RULE_STRUCTURING', 'STRUCTURING_PATTERN', 'MEDIUM', 'Transfer amount structured just below $10,000 reporting threshold', '{"min_value_usd": 8000.0, "max_value_usd": 9999.0}')
ON CONFLICT (rule_id) DO NOTHING;

-- 5. Alert Delivery Log
CREATE TABLE IF NOT EXISTS public.alert_delivery_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id UUID NOT NULL REFERENCES public.alerts(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    delivered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivery_status TEXT NOT NULL CHECK (delivery_status IN ('SUCCESS', 'FAILED', 'PENDING')),
    failure_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_alert_delivery_alert_id ON public.alert_delivery_log(alert_id);

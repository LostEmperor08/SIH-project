-- =====================================================================
-- Migration 14: Evidence Provenance, Reports & Government Integrations
-- SIH 2026 Problem Statement 26183 — Chakravyuh SETU
-- =====================================================================

-- 1. Evidence Records Table (Complements evidence_ledger with provenance metadata)
CREATE TABLE IF NOT EXISTS public.evidence_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id TEXT NOT NULL DEFAULT 'SIH/2026/00412',
    case_ref TEXT NOT NULL DEFAULT 'SIH/2026/00412',
    classification TEXT NOT NULL DEFAULT 'OBSERVED' CHECK (classification IN ('OBSERVED', 'DERIVED', 'EXTERNAL_INTELLIGENCE', 'INVESTIGATOR_CREATED', 'SYSTEM_GENERATED')),
    evidence_type TEXT NOT NULL DEFAULT 'BLOCKCHAIN_TRANSACTION' CHECK (evidence_type IN ('BLOCKCHAIN_TRANSACTION', 'BLOCKCHAIN_TRANSFER', 'WALLET_ACTIVITY', 'VASP_IDENTIFICATION', 'BRIDGE_CORRELATION', 'RISK_ASSESSMENT', 'ML_ASSESSMENT', 'SANCTIONS_MATCH', 'ALERT_EVENT', 'INVESTIGATOR_NOTE', 'REPORT', 'NOTICE')),
    chain TEXT DEFAULT 'polygon',
    address TEXT,
    tx_hash TEXT,
    block_number BIGINT,
    source_provider TEXT DEFAULT 'Chakravyuh Provider Network',
    source_endpoint TEXT,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    observed_at TIMESTAMPTZ DEFAULT NOW(),
    raw_payload_hash TEXT,
    normalized_payload_hash TEXT NOT NULL,
    prev_hash TEXT,
    chain_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'SEALED' CHECK (status IN ('COLLECTED', 'VERIFIED', 'SEALED', 'SUPERSEDED', 'INVALIDATED')),
    engine_versions JSONB DEFAULT '{}'::jsonb,
    created_by TEXT DEFAULT 'Officer User',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_evidence_records_case ON public.evidence_records(case_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_evidence_records_ref ON public.evidence_records(case_ref);
CREATE INDEX IF NOT EXISTS idx_evidence_records_tx ON public.evidence_records(tx_hash);
CREATE INDEX IF NOT EXISTS idx_evidence_records_class ON public.evidence_records(classification);

-- 2. Generated Reports Table
CREATE TABLE IF NOT EXISTS public.generated_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id TEXT NOT NULL,
    case_ref TEXT NOT NULL,
    report_version TEXT NOT NULL DEFAULT 'v1.0.0',
    pdf_hash TEXT NOT NULL,
    html_content TEXT,
    pdf_path TEXT,
    report_metadata JSONB DEFAULT '{}'::jsonb,
    engine_versions JSONB DEFAULT '{}'::jsonb,
    created_by TEXT DEFAULT 'Officer User',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_generated_reports_case ON public.generated_reports(case_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_generated_reports_hash ON public.generated_reports(pdf_hash);

-- 3. Outbound Government Integrations Log (NCRP & SAHYOG)
CREATE TABLE IF NOT EXISTS public.outbound_integration_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id TEXT NOT NULL,
    integration TEXT NOT NULL CHECK (integration IN ('NCRP', 'SAHYOG')),
    action_type TEXT NOT NULL,
    idempotency_key TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL DEFAULT 'SIMULATION' CHECK (status IN ('NOT_CONFIGURED', 'SIMULATION', 'CONNECTED', 'SUBMITTED', 'FAILED')),
    external_reference TEXT,
    payload_hash TEXT NOT NULL,
    response_hash TEXT,
    response_payload JSONB DEFAULT '{}'::jsonb,
    created_by TEXT DEFAULT 'Officer User',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_outbound_integration_case ON public.outbound_integration_log(case_id, integration);

-- RLS Enablement
ALTER TABLE public.evidence_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.generated_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.outbound_integration_log ENABLE ROW LEVEL SECURITY;

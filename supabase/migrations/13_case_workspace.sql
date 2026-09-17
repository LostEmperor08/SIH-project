-- =====================================================================
-- Migration 13: Investigator Case Workspace, Notes, Tasks & Audit Timeline
-- SIH 2026 Problem Statement 26183 — Chakravyuh SETU
-- =====================================================================

-- 1. Cases Master Table (Extends existing table if present, else creates)
CREATE TABLE IF NOT EXISTS public.investigation_cases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_ref TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    reported_wallet TEXT NOT NULL,
    reported_chain TEXT NOT NULL DEFAULT 'polygon',
    reported_amount_usd NUMERIC(16,2) DEFAULT 0.00,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('OPEN', 'ACTIVE', 'UNDER_REVIEW', 'PENDING_ACTION', 'CLOSED', 'ARCHIVED')),
    priority TEXT NOT NULL DEFAULT 'HIGH' CHECK (priority IN ('LOW', 'MEDIUM', 'HIGH', 'URGENT')),
    assigned_officer_id TEXT,
    org_unit TEXT DEFAULT 'Cyber Crime PS · I4C Operations',
    created_by TEXT DEFAULT 'Officer User',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_investigation_cases_ref ON public.investigation_cases(case_ref);
CREATE INDEX IF NOT EXISTS idx_investigation_cases_status ON public.investigation_cases(status);
CREATE INDEX IF NOT EXISTS idx_investigation_cases_wallet ON public.investigation_cases(reported_wallet);
CREATE INDEX IF NOT EXISTS idx_investigation_cases_officer ON public.investigation_cases(assigned_officer_id);

-- 2. Case Notes Table
CREATE TABLE IF NOT EXISTS public.case_notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id TEXT NOT NULL,
    author_id TEXT NOT NULL,
    author_name TEXT NOT NULL,
    text TEXT NOT NULL,
    is_pinned BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_case_notes_case ON public.case_notes(case_id, created_at DESC);

-- 3. Case Tasks Table
CREATE TABLE IF NOT EXISTS public.case_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    assignee TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'IN_PROGRESS', 'COMPLETED')),
    priority TEXT NOT NULL DEFAULT 'MEDIUM' CHECK (priority IN ('LOW', 'MEDIUM', 'HIGH')),
    due_at TIMESTAMPTZ,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_case_tasks_case ON public.case_tasks(case_id, status);

-- 4. Case Audit & Timeline Events Log
CREATE TABLE IF NOT EXISTS public.case_timeline (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    actor TEXT NOT NULL,
    actor_role TEXT DEFAULT 'INVESTIGATOR',
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_case_timeline_case ON public.case_timeline(case_id, created_at DESC);

-- RLS Enablement
ALTER TABLE public.investigation_cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.case_notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.case_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.case_timeline ENABLE ROW LEVEL SECURITY;

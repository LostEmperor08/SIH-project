-- =====================================================================
-- SKV | Blockchain Financial-Crime Detection Platform
-- 09_transaction_risk_schema.sql  —  Transaction Risk & Relevance Schema
-- =====================================================================

alter table public.transactions
  add column if not exists risk_score numeric(5,2),
  add column if not exists risk_band text,
  add column if not exists risk_confidence numeric(4,3),
  add column if not exists relevance_score numeric(5,2),
  add column if not exists taint_share numeric(4,3),
  add column if not exists risk_factors jsonb default '[]'::jsonb;

create index if not exists tx_risk_score_idx on public.transactions (risk_score desc) where risk_score is not null;
create index if not exists tx_relevance_idx on public.transactions (relevance_score desc) where relevance_score is not null;

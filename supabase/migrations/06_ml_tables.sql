-- =====================================================================
-- 06_ml_tables.sql — ML persistence for Chakravyuh SETU
-- Run after your existing supabase-setup.sql.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Model registry mirror — so the DB can answer "which model scored this"
-- without reaching into the filesystem the API runs on.
-- ---------------------------------------------------------------------
create table if not exists public.ml_models (
  id            bigserial primary key,
  name          text not null,
  version       text not null,
  trained_at    timestamptz not null,
  label_source  text,
  metrics       jsonb not null default '{}'::jsonb,
  feature_count integer,
  content_sha256 text,
  is_active     boolean not null default false,
  registered_at timestamptz not null default now(),
  unique (name, version)
);

create unique index if not exists ml_models_one_active
  on public.ml_models (name) where is_active;

-- ---------------------------------------------------------------------
-- Predictions — every score the system has ever produced.
-- Append-only: a risk score that contributed to a freeze decision must
-- still be retrievable, unchanged, months later.
-- ---------------------------------------------------------------------
create table if not exists public.ml_predictions (
  id             bigserial primary key,
  chain          text not null,
  address        text not null,
  risk_score     numeric(5,2) not null check (risk_score between 0 and 100),
  risk_band      text not null,
  illicit_probability numeric(6,4),
  anomaly_score  numeric(6,4),
  rule_score     numeric(5,2),
  vasp_type      text,
  vasp_confidence numeric(6,4),
  typologies     jsonb not null default '[]'::jsonb,
  explanation    jsonb not null default '[]'::jsonb,
  narrative      text,
  recommended_actions jsonb not null default '[]'::jsonb,
  hops_to_exchange   integer,
  hops_to_sanctioned integer,
  hops_to_mixer      integer,
  model_versions jsonb not null default '{}'::jsonb,
  scored_by      uuid references auth.users(id),
  scored_at      timestamptz not null default now()
);

create index if not exists mlp_addr_idx  on public.ml_predictions (chain, address, scored_at desc);
create index if not exists mlp_score_idx on public.ml_predictions (risk_score desc);
create index if not exists mlp_band_idx  on public.ml_predictions (risk_band, scored_at desc);
create index if not exists mlp_vasp_idx  on public.ml_predictions (vasp_type)
  where vasp_type is not null;

-- ---------------------------------------------------------------------
-- Analyst feedback — the ground-truth loop.
-- This table is the single most valuable asset the platform accumulates:
-- real labels from real investigations, which no public dataset provides.
-- ---------------------------------------------------------------------
create table if not exists public.ml_feedback (
  id          bigserial primary key,
  chain       text not null,
  address     text not null,
  verdict     text not null check (verdict in
                ('confirmed_fraud','false_positive','inconclusive')),
  typology    text,
  vasp_name   text,
  notes       text,
  officer_id  uuid references auth.users(id),
  case_ref    text,
  created_at  timestamptz not null default now()
);

create index if not exists mlf_addr_idx on public.ml_feedback (chain, address);
create index if not exists mlf_verdict_idx on public.ml_feedback (verdict, created_at desc);

-- ---------------------------------------------------------------------
-- Drift monitoring — a model trained in September and still running in
-- March is a liability unless someone is watching the input distribution.
-- ---------------------------------------------------------------------
create table if not exists public.ml_drift (
  id            bigserial primary key,
  model_name    text not null,
  window_start  timestamptz not null,
  window_end    timestamptz not null,
  n_scored      integer not null,
  mean_score    numeric(6,3),
  band_mix      jsonb,
  psi           numeric(8,4),        -- population stability index vs training
  alert         boolean not null default false,
  computed_at   timestamptz not null default now()
);

-- =====================================================================
-- RLS
-- =====================================================================
alter table public.ml_models      enable row level security;
alter table public.ml_predictions enable row level security;
alter table public.ml_feedback    enable row level security;
alter table public.ml_drift       enable row level security;

alter table public.ml_models      force row level security;
alter table public.ml_predictions force row level security;
alter table public.ml_feedback    force row level security;
alter table public.ml_drift       force row level security;

-- helper: is the caller an active officer?  Adapt to your existing table.
create or replace function public.is_active_officer()
returns boolean
language sql stable security definer set search_path = public, auth as $$
  select exists (
    select 1 from public.user_roles ur
     where ur.user_id = auth.uid()
  );
$$;

-- Predictions: active officers read; only the service role writes.
drop policy if exists mlp_read on public.ml_predictions;
create policy mlp_read on public.ml_predictions
  for select to authenticated using (public.is_active_officer());

drop policy if exists mlp_write on public.ml_predictions;
create policy mlp_write on public.ml_predictions
  for insert to service_role with check (true);

-- Predictions are never edited or deleted by anyone. Evidentiary integrity.
create or replace function public.ml_predictions_immutable() returns trigger
language plpgsql as $$
begin
  raise exception 'ml_predictions is append-only' using errcode = '42501';
end $$;

drop trigger if exists trg_mlp_immutable on public.ml_predictions;
create trigger trg_mlp_immutable before update or delete on public.ml_predictions
  for each row execute function public.ml_predictions_immutable();

-- Feedback: an officer writes their own and reads their own; supervisors read all.
drop policy if exists mlf_insert on public.ml_feedback;
create policy mlf_insert on public.ml_feedback
  for insert to authenticated
  with check (public.is_active_officer() and officer_id = auth.uid());

drop policy if exists mlf_read on public.ml_feedback;
create policy mlf_read on public.ml_feedback
  for select to authenticated
  using (officer_id = auth.uid() or public.has_min_role('investigator'));

-- Models + drift: readable by officers, written by the service role.
drop policy if exists mlm_read on public.ml_models;
create policy mlm_read on public.ml_models
  for select to authenticated using (public.is_active_officer());

drop policy if exists mld_read on public.ml_drift;
create policy mld_read on public.ml_drift
  for select to authenticated using (public.has_min_role('investigator'));

-- =====================================================================
-- Convenience views
-- =====================================================================
create or replace view public.v_latest_prediction as
  select distinct on (chain, address) *
    from public.ml_predictions
   order by chain, address, scored_at desc;

create or replace view public.v_ml_dashboard as
  select
    count(*)                                             as total_scored,
    count(*) filter (where risk_band = 'critical')       as critical,
    count(*) filter (where risk_band = 'high')           as high,
    count(*) filter (where hops_to_exchange = 0)         as direct_exchange_deposits,
    count(*) filter (where hops_to_sanctioned = 0)       as sanctioned_hits,
    count(distinct vasp_type) filter (where vasp_type is not null
                                        and vasp_type <> 'unknown') as vasp_types_seen,
    round(avg(risk_score), 2)                            as mean_risk,
    max(scored_at)                                       as last_scored_at
  from public.v_latest_prediction;

-- Model quality against analyst ground truth — the number that actually
-- tells you whether the ML is working in the field.
create or replace view public.v_model_accuracy as
  select
    f.verdict,
    count(*)                                   as n,
    round(avg(p.risk_score), 2)                as mean_predicted_risk,
    count(*) filter (where p.risk_band in ('high','critical')) as flagged_high
  from public.ml_feedback f
  join public.v_latest_prediction p
    on p.chain = f.chain and p.address = f.address
  group by f.verdict;

do $$ begin
  alter publication supabase_realtime add table public.ml_predictions;
exception when duplicate_object then null; end $$;

-- =====================================================================
-- SKV | Blockchain Financial-Crime Detection Platform
-- 01_schema.sql  —  Core domain schema
-- Run in Supabase SQL Editor (or `supabase db push`)
-- =====================================================================

create extension if not exists "pgcrypto";      -- digest(), gen_random_uuid()
create extension if not exists "pg_stat_statements";

-- ---------------------------------------------------------------------
-- Enumerations
-- ---------------------------------------------------------------------
do $$ begin
  create type chain_t as enum ('btc','eth','bsc','polygon','tron');
exception when duplicate_object then null; end $$;

do $$ begin
  create type entity_t as enum (
    'unknown','exchange','mixer','gambling','bridge','defi',
    'darknet','ransomware','scam','sanctioned','merchant','p2p'
  );
exception when duplicate_object then null; end $$;

do $$ begin
  create type app_role_t as enum ('viewer','analyst','investigator','admin');
exception when duplicate_object then null; end $$;

do $$ begin
  create type alert_status_t as enum ('open','triaged','escalated','closed_tp','closed_fp');
exception when duplicate_object then null; end $$;

do $$ begin
  create type case_status_t as enum ('draft','active','under_review','submitted','closed');
exception when duplicate_object then null; end $$;

-- ---------------------------------------------------------------------
-- 1. Identity & RBAC
-- ---------------------------------------------------------------------
create table if not exists public.user_roles (
  user_id     uuid primary key references auth.users(id) on delete cascade,
  role        app_role_t not null default 'viewer',
  full_name   text,
  org_unit    text,
  mfa_enrolled boolean not null default false,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

comment on table public.user_roles is
  'RBAC assignment. One role per principal. Role is read by the RLS helper fn.';

-- ---------------------------------------------------------------------
-- 2. Wallets (graph vertices)
-- ---------------------------------------------------------------------
create table if not exists public.wallets (
  id              bigserial primary key,
  chain           chain_t   not null,
  address         text      not null,
  first_seen      timestamptz,
  last_seen       timestamptz,
  tx_count        integer   not null default 0,
  in_count        integer   not null default 0,
  out_count       integer   not null default 0,
  total_in_usd    numeric(24,2) not null default 0,
  total_out_usd   numeric(24,2) not null default 0,
  balance_usd     numeric(24,2) generated always as (total_in_usd - total_out_usd) stored,
  entity_type     entity_t  not null default 'unknown',
  vasp_name       text,                       -- attributed VASP, if any
  vasp_confidence numeric(4,3),               -- 0..1
  is_sanctioned   boolean   not null default false,
  labels          text[]    not null default '{}',
  metadata        jsonb     not null default '{}'::jsonb,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (chain, address)
);

create index if not exists wallets_addr_idx        on public.wallets (address);
create index if not exists wallets_entity_idx      on public.wallets (entity_type);
create index if not exists wallets_sanctioned_idx  on public.wallets (is_sanctioned) where is_sanctioned;
create index if not exists wallets_labels_gin      on public.wallets using gin (labels);

-- ---------------------------------------------------------------------
-- 3. Transactions (graph edges)  — edge-list model, chain agnostic
-- ---------------------------------------------------------------------
create table if not exists public.transactions (
  id            bigserial primary key,
  chain         chain_t  not null,
  tx_hash       text     not null,
  vout_index    integer  not null default 0,   -- output idx (BTC) / log idx (EVM)
  block_height  bigint,
  block_time    timestamptz not null,
  from_address  text     not null,
  to_address    text     not null,
  value_native  numeric(38,18) not null default 0,
  value_usd     numeric(24,2)  not null default 0,
  fee_usd       numeric(18,2)  not null default 0,
  asset         text     not null default 'native',
  raw           jsonb    not null default '{}'::jsonb,
  ingested_at   timestamptz not null default now(),
  unique (chain, tx_hash, vout_index, from_address, to_address)
);

create index if not exists tx_from_idx   on public.transactions (chain, from_address, block_time desc);
create index if not exists tx_to_idx     on public.transactions (chain, to_address,   block_time desc);
create index if not exists tx_time_idx   on public.transactions (block_time desc);
create index if not exists tx_hash_idx   on public.transactions (tx_hash);
create index if not exists tx_value_idx  on public.transactions (value_usd desc);
-- supports the peel-chain recursion in compute_wallet_features()
create index if not exists tx_peel_idx   on public.transactions (chain, from_address, value_usd)
  where value_usd > 100;

-- ---------------------------------------------------------------------
-- 4. Wallet clusters (co-spend / common-input-ownership heuristic)
-- ---------------------------------------------------------------------
create table if not exists public.clusters (
  id              bigserial primary key,
  chain           chain_t not null,
  root_address    text    not null,            -- canonical representative
  size            integer not null default 1,
  entity_type     entity_t not null default 'unknown',
  vasp_name       text,
  vasp_confidence numeric(4,3),
  attribution_evidence jsonb not null default '[]'::jsonb,
  total_volume_usd numeric(24,2) not null default 0,
  risk_score      numeric(5,2) not null default 0,
  heuristic       text    not null default 'common_input_ownership',
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (chain, root_address)
);

create table if not exists public.cluster_members (
  cluster_id  bigint not null references public.clusters(id) on delete cascade,
  wallet_id   bigint not null references public.wallets(id)  on delete cascade,
  joined_via  text   not null default 'co_spend',
  confidence  numeric(4,3) not null default 1.0,
  primary key (cluster_id, wallet_id)
);

create index if not exists cluster_members_wallet_idx on public.cluster_members (wallet_id);

-- ---------------------------------------------------------------------
-- 5. Threat intelligence (sanctions + open-source feeds)
-- ---------------------------------------------------------------------
create table if not exists public.threat_intel (
  id           bigserial primary key,
  chain        chain_t not null,
  address      text    not null,
  source       text    not null,               -- 'OFAC_SDN', 'CryptoScamDB', 'manual'
  category     entity_t not null default 'sanctioned',
  entity_name  text,
  program      text,                           -- e.g. 'CYBER2', 'DPRK3'
  severity     smallint not null default 100 check (severity between 0 and 100),
  reference_url text,
  first_listed timestamptz,
  synced_at    timestamptz not null default now(),
  unique (chain, address, source)
);

create index if not exists ti_addr_idx on public.threat_intel (address);

-- ---------------------------------------------------------------------
-- 6. Behavioural features + risk scores (explainable)
-- ---------------------------------------------------------------------
create table if not exists public.wallet_features (
  wallet_id            bigint primary key references public.wallets(id) on delete cascade,
  tx_velocity_7d       numeric(12,4) not null default 0,  -- tx/day
  avg_value_usd        numeric(24,2) not null default 0,
  value_stddev_usd     numeric(24,2) not null default 0,
  round_amount_ratio   numeric(5,4)  not null default 0,  -- share of "round" amounts
  fan_in               integer not null default 0,        -- distinct senders
  fan_out              integer not null default 0,        -- distinct receivers
  peel_chain_depth     integer not null default 0,
  mixer_hops           integer,                           -- hops to nearest mixer (null = none)
  sanction_hops        integer,                           -- hops to nearest sanctioned addr
  dormancy_days        numeric(10,2) not null default 0,
  night_activity_ratio numeric(5,4)  not null default 0,  -- 00:00-05:00 UTC share
  counterparty_entropy numeric(8,4)  not null default 0,  -- Shannon entropy
  structuring_score    numeric(5,4)  not null default 0,  -- sub-threshold clustering
  computed_at          timestamptz not null default now()
);

create table if not exists public.risk_scores (
  id           bigserial primary key,
  wallet_id    bigint not null references public.wallets(id) on delete cascade,
  score        numeric(5,2) not null check (score between 0 and 100),
  band         text generated always as (
                 case when score >= 80 then 'critical'
                      when score >= 60 then 'high'
                      when score >= 35 then 'medium'
                      else 'low' end) stored,
  contributions jsonb not null default '[]'::jsonb,  -- [{factor,weight,value,points}]
  model_version text  not null default 'v1.0.0',
  scored_at    timestamptz not null default now()
);

create index if not exists risk_wallet_idx on public.risk_scores (wallet_id, scored_at desc);
create index if not exists risk_score_idx  on public.risk_scores (score desc);

-- ---------------------------------------------------------------------
-- 7. Alerts
-- ---------------------------------------------------------------------
create table if not exists public.alerts (
  id           bigserial primary key,
  wallet_id    bigint references public.wallets(id) on delete set null,
  cluster_id   bigint references public.clusters(id) on delete set null,
  tx_id        bigint references public.transactions(id) on delete set null,
  rule_code    text    not null,               -- 'SANCTION_DIRECT','PEEL_CHAIN', ...
  title        text    not null,
  detail       text,
  severity     smallint not null default 50 check (severity between 0 and 100),
  status       alert_status_t not null default 'open',
  assigned_to  uuid references auth.users(id),
  evidence_ref jsonb not null default '{}'::jsonb,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index if not exists alerts_status_idx on public.alerts (status, severity desc, created_at desc);

-- ---------------------------------------------------------------------
-- 8. Investigation cases
-- ---------------------------------------------------------------------
create table if not exists public.cases (
  id            bigserial primary key,
  case_ref      text unique not null default ('CASE-' || to_char(now(),'YYYY') || '-' || lpad((floor(random()*99999))::text, 5, '0')),
  title         text not null,
  summary       text,
  status        case_status_t not null default 'draft',
  lead_analyst  uuid references auth.users(id),
  classification text not null default 'restricted',
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create table if not exists public.case_alerts (
  case_id  bigint not null references public.cases(id)  on delete cascade,
  alert_id bigint not null references public.alerts(id) on delete cascade,
  primary key (case_id, alert_id)
);

-- ---------------------------------------------------------------------
-- 9. Updated-at trigger helper
-- ---------------------------------------------------------------------
create or replace function public.touch_updated_at() returns trigger
language plpgsql as $$
begin new.updated_at := now(); return new; end $$;

do $$
declare t text;
begin
  foreach t in array array['user_roles','wallets','clusters','alerts','cases'] loop
    execute format(
      'drop trigger if exists trg_touch_%1$s on public.%1$s;
       create trigger trg_touch_%1$s before update on public.%1$s
       for each row execute function public.touch_updated_at();', t);
  end loop;
end $$;

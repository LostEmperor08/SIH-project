-- =====================================================================
-- 08_reconcile.sql
--
-- Reconciles the ORIGINAL supabase-setup.sql schema with migrations 01–07.
-- Run this AFTER both. Without it the two halves fight each other:
--
--   * is_active_officer() gets redefined to read user_roles, but every
--     officer lives in profiles -> EVERY USER IS LOCKED OUT of everything.
--   * Two append_audit() overloads coexist (3-param and 4-param), writing
--     different hash formats into one audit_log -> the chain can never
--     verify.
--   * dossiers/audit_log already exist with different columns, so the
--     migrations' CREATE TABLE IF NOT EXISTS silently skip and their
--     policies then fail on columns that were never created.
--   * evidence_ledger stores a per-row sha256 but NO prev_hash, so
--     deleting a row is undetectable — it is a checksum, not a chain.
--
-- Decision: `profiles` wins as the identity source of truth. It carries
-- badge_id and station_code, which a law-enforcement system genuinely
-- needs and user_roles does not.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. IDENTITY — one table, four tiers, least privilege
-- ---------------------------------------------------------------------

-- The original allows only admin/investigator/viewer. Add the analyst
-- tier the RBAC model expects between viewer and investigator.
alter table public.profiles drop constraint if exists profiles_role_check;
alter table public.profiles add constraint profiles_role_check
  check (role in ('viewer', 'analyst', 'investigator', 'admin'));

-- SECURITY FIX: the original defaults a new signup to 'investigator'.
-- That is privilege-by-default — anyone who registers can immediately
-- read case data. Privilege must be granted, never assumed.
alter table public.profiles alter column role set default 'viewer';

alter table public.profiles
  add column if not exists mfa_enrolled boolean not null default false,
  add column if not exists last_login_at timestamptz,
  add column if not exists failed_login_count integer not null default 0;

-- Carry across anyone created under the migrations' user_roles table
-- before this reconciliation ran.
do $$
begin
  if exists (select 1 from information_schema.tables
              where table_schema='public' and table_name='user_roles') then
    insert into public.profiles (id, email, full_name, role, status)
    select ur.user_id,
           coalesce(u.email, ur.user_id::text || '@unknown.local'),
           ur.full_name,
           ur.role::text,
           'active'
      from public.user_roles ur
      left join auth.users u on u.id = ur.user_id
    on conflict (id) do nothing;
  end if;
end $$;

-- ---------------------------------------------------------------------
-- 2. ROLE HELPERS — all read profiles, all pin search_path
-- ---------------------------------------------------------------------
create or replace function public.is_active_officer()
returns boolean
language sql stable security definer set search_path = public, auth as $$
  select exists (
    select 1 from public.profiles
     where id = auth.uid() and status = 'active'
  );
$$;

create or replace function public.role_rank_text(r text)
returns integer language sql immutable as $$
  select case r
    when 'viewer'       then 1
    when 'analyst'      then 2
    when 'investigator' then 3
    when 'admin'        then 4
    else 0 end;
$$;

-- 02_rbac_rls.sql created this returning app_role_t. Postgres will not let
-- CREATE OR REPLACE change a return type, so drop it first. Nothing depends
-- on it directly — the policies depend on has_min_role(), handled below.
drop function if exists public.current_role_name();
create or replace function public.current_role_name()
returns text
language sql stable security definer set search_path = public, auth as $$
  select coalesce(
    (select role from public.profiles where id = auth.uid() and status = 'active'),
    'viewer');
$$;

-- has_min_role(app_role_t) CANNOT be dropped: every RLS policy written by
-- 02_rbac_rls.sql depends on it, and a CASCADE drop would silently delete
-- those policies — turning default-deny tables into open ones. So it is
-- REPLACED in place, keeping its signature, and repointed at profiles.
create or replace function public.has_min_role(required app_role_t)
returns boolean
language sql stable security definer set search_path = public, auth as $$
  select public.is_active_officer()
     and public.role_rank_text(public.current_role_name())
       >= public.role_rank_text(required::text);
$$;

-- Text overload, so new code can call has_min_role('admin') without a cast.
create or replace function public.has_min_role(required text)
returns boolean
language sql stable security definer set search_path = public, auth as $$
  select public.is_active_officer()
     and public.role_rank_text(public.current_role_name())
       >= public.role_rank_text(required);
$$;

create or replace function public.is_admin()
returns boolean
language sql stable security definer set search_path = public, auth as $$
  select public.has_min_role('admin');
$$;

-- user_roles becomes a read-only view so anything still referencing it
-- sees the same truth instead of a stale second copy.
do $$
begin
  if exists (select 1 from information_schema.tables
              where table_schema='public' and table_name='user_roles'
                and table_type='BASE TABLE') then
    execute 'alter table public.user_roles rename to user_roles_deprecated';
  end if;
end $$;

create or replace view public.user_roles as
  select id as user_id, role, full_name, status, mfa_enrolled, created_at
    from public.profiles;

-- One signup handler. The original and migration 02 both defined this;
-- whichever ran last silently won, so a new user got only one of the two
-- rows they needed.
create or replace function public.handle_new_user()
returns trigger
language plpgsql security definer set search_path = public, auth as $$
begin
  insert into public.profiles (id, email, full_name, role, status)
  values (new.id,
          new.email,
          coalesce(new.raw_user_meta_data->>'full_name', new.email),
          'viewer',        -- least privilege
          'pending')       -- an admin must activate the account
  on conflict (id) do nothing;
  return new;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------------
-- 3. AUDIT LOG — upgrade the original table into a real hash chain
-- ---------------------------------------------------------------------
alter table public.audit_log
  add column if not exists actor_role  text,
  add column if not exists resource_id text,
  add column if not exists before_data jsonb,
  add column if not exists prev_hash   text,
  add column if not exists row_hash    text,
  add column if not exists ip_address  inet,
  add column if not exists user_agent  text;

create index if not exists audit_actor_idx on public.audit_log (actor_id, created_at desc);
create index if not exists audit_action_idx on public.audit_log (action, created_at desc);

create or replace function public.canonical_json(j jsonb)
returns text language sql immutable as $$
  select coalesce(
    (select '{' || string_agg(format('%s:%s', to_json(key), value::text), ',' order by key) || '}'
       from jsonb_each(j)), '{}');
$$;

create or replace function public.sha256_hex(t text)
returns text language sql immutable as $$
  select encode(extensions.digest(t, 'sha256'), 'hex');
$$;

-- THE canonical hash. One definition for every writer and the verifier —
-- two writers with two formats is precisely what breaks a hash chain.
-- Dropped first: 03_audit_evidence.sql created it with different parameter
-- names, and CREATE OR REPLACE cannot rename parameters.
drop function if exists public.audit_hash(text, timestamptz, uuid, text, text, text, jsonb, jsonb);
create or replace function public.audit_hash(
  p_prev text, p_at timestamptz, p_actor uuid, p_action text,
  p_target text, p_resource_id text, p_before jsonb, p_after jsonb
) returns text
language sql immutable set search_path = public, extensions as $$
  select public.sha256_hex(concat_ws('|',
    coalesce(p_prev, 'GENESIS'), p_at::text,
    coalesce(p_actor::text, 'system'), p_action,
    coalesce(p_target, ''), coalesce(p_resource_id, ''),
    public.canonical_json(coalesce(p_before, '{}'::jsonb)),
    public.canonical_json(coalesce(p_after,  '{}'::jsonb))));
$$;

-- Remove BOTH prior overloads, then create exactly one.
drop function if exists public.append_audit(text, text, jsonb);
drop function if exists public.append_audit(text, text, text, jsonb);

create or replace function public.append_audit(
  p_action      text,
  p_target      text default null,
  p_resource_id text default null,
  p_detail      jsonb default '{}'::jsonb
) returns bigint
language plpgsql security definer set search_path = public, extensions, auth as $$
declare
  v_actor uuid := auth.uid();
  v_email text;
  v_prev  text;
  v_hash  text;
  v_id    bigint;
begin
  if v_actor is null then
    raise exception 'append_audit requires an authenticated caller'
      using errcode = '42501';
  end if;
  if not public.is_active_officer() then
    raise exception 'no active officer record' using errcode = '42501';
  end if;
  if p_action !~ '^[A-Z_]{3,48}$' then
    raise exception 'invalid action code %', p_action using errcode = '22023';
  end if;

  select email into v_email from public.profiles where id = v_actor;
  select row_hash into v_prev from public.audit_log order by id desc limit 1;

  v_hash := public.audit_hash(v_prev, now(), v_actor, p_action,
                              p_target, p_resource_id,
                              '{}'::jsonb, coalesce(p_detail, '{}'::jsonb));

  insert into public.audit_log(
    actor_id, actor_email, actor_role, action, target, resource_id,
    detail, prev_hash, row_hash)
  values (v_actor, v_email, public.current_role_name(), p_action,
          p_target, p_resource_id, coalesce(p_detail, '{}'::jsonb),
          v_prev, v_hash)
  returning id into v_id;

  return v_id;
end $$;

grant execute on function public.append_audit(text, text, text, jsonb) to authenticated;

-- Append-only, enforced twice: no grant, and a trigger.
revoke insert, update, delete on public.audit_log from authenticated, anon;

create or replace function public.audit_immutable() returns trigger
language plpgsql as $$
begin
  raise exception 'audit_log is append-only (attempted %)', tg_op
    using errcode = '42501';
end $$;

drop trigger if exists trg_audit_immutable on public.audit_log;
create trigger trg_audit_immutable before update or delete on public.audit_log
  for each row execute function public.audit_immutable();

-- 03_audit_evidence.sql attached a generic audit trigger to several tables,
-- writing to columns (occurred_at, table_name, record_pk, after_data) that
-- the original audit_log does not have. It has an exception handler, so it
-- degraded to a WARNING — meaning table-level changes were SILENTLY NOT
-- AUDITED. Repointed at the real column names.
create or replace function public.audit_trigger() returns trigger
language plpgsql security definer set search_path = public, extensions, auth as $$
declare
  v_before jsonb; v_after jsonb; v_prev text; v_pk text; v_hash text;
begin
  v_before := case when tg_op in ('UPDATE','DELETE') then to_jsonb(old) end;
  v_after  := case when tg_op in ('INSERT','UPDATE') then to_jsonb(new) end;
  v_pk     := coalesce(v_after->>'id', v_before->>'id');

  select row_hash into v_prev from public.audit_log order by id desc limit 1;
  v_hash := public.audit_hash(v_prev, now(), auth.uid(), tg_op,
                              tg_table_name, v_pk, v_before, v_after);

  insert into public.audit_log(
    actor_id, actor_email, actor_role, action, target, resource_id,
    before_data, detail, prev_hash, row_hash)
  values (
    auth.uid(),
    (select email from public.profiles where id = auth.uid()),
    case when auth.uid() is null then 'system' else public.current_role_name() end,
    tg_op, tg_table_name, v_pk, v_before, v_after, v_prev, v_hash);

  return coalesce(new, old);
end $$;

create or replace function public.verify_audit_chain()
returns table (ok boolean, checked bigint, first_bad_id bigint, detail text)
language plpgsql security definer set search_path = public, extensions as $$
declare r record; v_prev text := null; n bigint := 0; v_expect text;
begin
  for r in select * from public.audit_log order by id asc loop
    n := n + 1;
    -- rows written before this migration have no hash; chain starts there
    if r.row_hash is null then
      continue;
    end if;
    v_expect := public.audit_hash(v_prev, r.created_at, r.actor_id, r.action,
                                  r.target, r.resource_id,
                                  r.before_data, r.detail);
    if r.row_hash <> v_expect then
      return query select false, n, r.id, 'hash mismatch at audit id ' || r.id;
      return;
    end if;
    v_prev := r.row_hash;
  end loop;
  return query select true, n, null::bigint, 'chain intact';
end $$;

grant execute on function public.verify_audit_chain() to authenticated;

-- ---------------------------------------------------------------------
-- 4. DOSSIERS — add ownership, then real separation of duties
-- ---------------------------------------------------------------------

-- The original has approved_by but no created_by, so "an officer may not
-- approve their own dossier" was impossible to enforce. It is the single
-- most important control on a document that authorises a freeze.
alter table public.dossiers
  add column if not exists created_by uuid references auth.users on delete set null,
  add column if not exists submitted_at timestamptz;

create index if not exists dossiers_creator_idx on public.dossiers (created_by);
create index if not exists dossiers_status_idx  on public.dossiers (approval_status, created_at desc);

drop function if exists public.review_dossier(text, text, text);

create or replace function public.review_dossier(
  p_dossier_id      text,
  p_approval_status text,
  p_note            text default null
) returns public.dossiers
language plpgsql security definer set search_path = public, auth as $$
declare v_row public.dossiers;
begin
  if not public.has_min_role('admin') then
    raise exception 'dossier review requires the admin role' using errcode = '42501';
  end if;
  if p_approval_status not in ('approved', 'rejected') then
    raise exception 'approval_status must be approved or rejected'
      using errcode = '22023';
  end if;

  select * into v_row from public.dossiers where id = p_dossier_id;
  if not found then
    raise exception 'dossier % not found', p_dossier_id using errcode = 'P0002';
  end if;

  -- SEPARATION OF DUTIES — holds even for an admin.
  if v_row.created_by is not null and v_row.created_by = auth.uid() then
    raise exception 'an officer cannot review their own dossier'
      using errcode = '42501';
  end if;

  if v_row.approval_status <> 'pending' then
    raise exception 'dossier % is already %', p_dossier_id, v_row.approval_status
      using errcode = '22023';
  end if;

  update public.dossiers
     set approval_status = p_approval_status,
         approved_by = auth.uid(), approved_at = now(), review_note = p_note
   where id = p_dossier_id
   returning * into v_row;

  perform public.append_audit('DOSSIER_REVIEW', 'dossier', p_dossier_id,
            jsonb_build_object('decision', p_approval_status, 'note', p_note));

  return v_row;
end $$;

grant execute on function public.review_dossier(text, text, text) to authenticated;

-- Clients may never set approval fields directly; the RPC is the only door.
drop policy if exists dossiers_write on public.dossiers;
drop policy if exists dossiers_insert on public.dossiers;
drop policy if exists dossiers_update_own_draft on public.dossiers;
create policy dossiers_insert on public.dossiers
  for insert to authenticated
  with check (public.has_min_role('analyst') and created_by = auth.uid());

create policy dossiers_update_own_draft on public.dossiers
  for update to authenticated
  using (public.is_active_officer() and created_by = auth.uid()
         and approval_status = 'pending')
  with check (created_by = auth.uid() and approval_status = 'pending');

-- ---------------------------------------------------------------------
-- 5. EVIDENCE LEDGER — turn a checksum into a chain
-- ---------------------------------------------------------------------

-- The original stores sha256 per row. That detects an EDIT but not a
-- DELETION: remove row 3 and rows 1,2,4,5 all still verify individually.
-- Linking each row to the previous one closes that hole.
alter table public.evidence_ledger
  add column if not exists case_ref    text,
  add column if not exists seq         integer,
  add column if not exists prev_hash   text,
  add column if not exists chain_hash  text,
  add column if not exists collected_by uuid references auth.users on delete set null,
  add column if not exists sealed      boolean not null default true;

create index if not exists evidence_case_idx on public.evidence_ledger (case_ref, seq);

create or replace function public.add_evidence_link(
  p_id         text,
  p_case_ref   text,
  p_chain      text,
  p_tx_hash    text,
  p_from       text,
  p_to         text,
  p_value_usdt numeric,
  p_risk_score int,
  p_hop        int default null,
  p_observed_at timestamptz default now()
) returns public.evidence_ledger
language plpgsql security definer set search_path = public, extensions, auth as $$
declare
  v_seq int; v_prev text; v_content text; v_sha text; v_chain text;
  v_row public.evidence_ledger;
begin
  if not public.has_min_role('analyst') then
    raise exception 'analyst role required to collect evidence' using errcode = '42501';
  end if;

  select coalesce(max(seq), 0) + 1,
         (select chain_hash from public.evidence_ledger
           where case_ref = p_case_ref order by seq desc limit 1)
    into v_seq, v_prev
    from public.evidence_ledger where case_ref = p_case_ref;

  v_content := concat_ws('|', p_chain, p_tx_hash, p_from, p_to,
                         p_value_usdt::text, p_observed_at::text);
  v_sha   := public.sha256_hex(v_content);
  v_chain := public.sha256_hex(concat_ws('|', coalesce(v_prev, 'GENESIS'),
                               p_case_ref, v_seq::text, v_sha,
                               auth.uid()::text, now()::text));

  insert into public.evidence_ledger(
    id, case_ref, seq, hop, chain, tx_hash, from_addr, to_addr,
    value_usdt, risk_score, sha256, prev_hash, chain_hash,
    collected_by, observed_at)
  values (p_id, p_case_ref, v_seq, p_hop, p_chain, p_tx_hash, p_from, p_to,
          p_value_usdt, p_risk_score, v_sha, v_prev, v_chain,
          auth.uid(), p_observed_at)
  returning * into v_row;

  perform public.append_audit('EVIDENCE_SEAL', 'evidence_ledger', p_id,
            jsonb_build_object('caseRef', p_case_ref, 'seq', v_seq));

  return v_row;
end $$;

grant execute on function public.add_evidence_link(
  text, text, text, text, text, text, numeric, int, int, timestamptz) to authenticated;

create or replace function public.evidence_immutable() returns trigger
language plpgsql as $$
begin
  raise exception 'sealed evidence is immutable' using errcode = '42501';
end $$;

drop trigger if exists trg_evidence_immutable on public.evidence_ledger;
create trigger trg_evidence_immutable before update or delete on public.evidence_ledger
  for each row when (old.sealed and old.chain_hash is not null)
  execute function public.evidence_immutable();

create or replace function public.verify_evidence_chain(p_case_ref text)
returns table (seq integer, content_ok boolean, link_ok boolean, verdict text)
language plpgsql security definer set search_path = public, extensions as $$
declare r record; v_prev text := null; v_content text; v_sha text; v_chain text;
begin
  for r in select * from public.evidence_ledger
            where case_ref = p_case_ref and chain_hash is not null
            order by seq asc loop
    v_content := concat_ws('|', r.chain, r.tx_hash, r.from_addr, r.to_addr,
                           r.value_usdt::text, r.observed_at::text);
    v_sha := public.sha256_hex(v_content);
    v_chain := public.sha256_hex(concat_ws('|', coalesce(v_prev, 'GENESIS'),
                                 r.case_ref, r.seq::text, r.sha256,
                                 r.collected_by::text, r.created_at::text));
    return query select r.seq, (v_sha = r.sha256), (v_chain = r.chain_hash),
      case when v_sha = r.sha256 and v_chain = r.chain_hash
           then 'INTACT' else 'TAMPERED' end;
    v_prev := r.chain_hash;
  end loop;
end $$;

grant execute on function public.verify_evidence_chain(text) to authenticated;

-- ---------------------------------------------------------------------
-- 6. Rebuild the policies that failed while dossiers/audit_log were
--    the original tables
-- ---------------------------------------------------------------------
alter table public.profiles        enable row level security;
alter table public.audit_log       enable row level security;
alter table public.dossiers        enable row level security;
alter table public.evidence_ledger enable row level security;
alter table public.watchlist       enable row level security;

drop policy if exists dossiers_read on public.dossiers;
create policy dossiers_read on public.dossiers
  for select to authenticated
  using (public.is_active_officer()
         and (created_by = auth.uid() or public.has_min_role('investigator')));

drop policy if exists evidence_ledger_read on public.evidence_ledger;
create policy evidence_ledger_read on public.evidence_ledger
  for select to authenticated using (public.is_active_officer());

drop policy if exists evidence_ledger_write on public.evidence_ledger;
-- inserts go through add_evidence_link() only
revoke insert, update, delete on public.evidence_ledger from authenticated, anon;

drop policy if exists audit_admin_read on public.audit_log;
drop policy if exists audit_read on public.audit_log;
create policy audit_read on public.audit_log
  for select to authenticated using (public.has_min_role('investigator'));

-- ---------------------------------------------------------------------
-- 7. Post-migration check — run this and read the output
-- ---------------------------------------------------------------------
do $$
declare n int;
begin
  select count(*) into n from pg_proc p join pg_namespace ns on ns.oid = p.pronamespace
   where ns.nspname = 'public' and p.proname = 'append_audit';
  if n <> 1 then
    raise warning 'append_audit has % definitions, expected 1', n;
  else
    raise notice 'OK: exactly one append_audit';
  end if;

  if (select pg_get_functiondef(p.oid) like '%profiles%'
        from pg_proc p join pg_namespace ns on ns.oid = p.pronamespace
       where ns.nspname='public' and p.proname='is_active_officer') then
    raise notice 'OK: is_active_officer reads profiles';
  else
    raise warning 'is_active_officer does NOT read profiles — users will be locked out';
  end if;
end $$;

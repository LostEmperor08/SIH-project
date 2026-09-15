-- =====================================================================
-- 07_officer_audit_dossier.sql
-- The RPCs the FastAPI backend calls, plus active-officer RLS.
-- Run after 01–06.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Officer status. An account can exist in auth.users and still not be an
-- active officer — suspension must revoke access without deleting the
-- account, because the audit trail references it.
-- ---------------------------------------------------------------------
alter table public.user_roles
  add column if not exists is_active boolean not null default true,
  add column if not exists badge_no text,
  add column if not exists unit text,
  add column if not exists suspended_at timestamptz,
  add column if not exists suspended_reason text;

create or replace function public.is_active_officer()
returns boolean
language sql stable security definer set search_path = public, auth as $$
  select exists (
    select 1 from public.user_roles ur
     where ur.user_id = auth.uid() and ur.is_active
  );
$$;

grant execute on function public.is_active_officer() to authenticated;

-- ---------------------------------------------------------------------
-- append_audit — Control 9.
--
-- The actor is derived from auth.uid() INSIDE the function. There is no
-- parameter for it, so a client physically cannot write another officer's
-- identity into the audit trail. Same for the timestamp: now() server-side,
-- never a client clock.
-- ---------------------------------------------------------------------
create or replace function public.append_audit(
  p_action      text,
  p_resource    text,
  p_resource_id text default null,
  p_detail      jsonb default '{}'::jsonb
) returns bigint
language plpgsql security definer set search_path = public, extensions, auth as $$
declare
  v_actor uuid := auth.uid();
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

  select row_hash into v_prev from public.audit_log order by id desc limit 1;

  -- Uses the SHARED audit_hash(). Rolling a bespoke hash here is exactly
  -- what broke verification before: this function omitted the before_data
  -- segment the verifier expected, so every RPC-written row read as
  -- TAMPERED. One definition, no drift.
  v_hash := public.audit_hash(
              v_prev, now(), v_actor, p_action, p_resource, p_resource_id,
              '{}'::jsonb, coalesce(p_detail, '{}'::jsonb));

  insert into public.audit_log(
    actor_id, actor_role, action, table_name, record_pk,
    after_data, prev_hash, row_hash)
  values (
    v_actor, public.current_role_name(), p_action, p_resource, p_resource_id,
    coalesce(p_detail, '{}'::jsonb), v_prev, v_hash)
  returning id into v_id;

  return v_id;
end $$;

grant execute on function public.append_audit(text, text, text, jsonb) to authenticated;

-- Control: direct audit inserts are revoked. append_audit is the only door.
revoke insert, update, delete on public.audit_log from authenticated, anon;

-- ---------------------------------------------------------------------
-- Dossiers
-- ---------------------------------------------------------------------
create table if not exists public.dossiers (
  id            text primary key default ('DSR-' || to_char(now(), 'YYYYMMDD') || '-' ||
                                           upper(substr(md5(random()::text), 1, 6))),
  case_ref      text,
  title         text not null,
  chain         text,
  subject_address text,
  summary       text,
  findings      jsonb not null default '{}'::jsonb,
  graph_snapshot jsonb,
  notice_type   text,                        -- 'BNSS_91' | 'BNSS_94' | null
  status        text not null default 'draft'
                check (status in ('draft','submitted','approved','rejected','returned')),
  created_by    uuid not null default auth.uid() references auth.users(id),
  reviewed_by   uuid references auth.users(id),
  reviewed_at   timestamptz,
  review_remarks text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index if not exists dossiers_status_idx  on public.dossiers (status, created_at desc);
create index if not exists dossiers_creator_idx on public.dossiers (created_by);

alter table public.dossiers enable row level security;
alter table public.dossiers force row level security;

-- Read: your own, or investigator+ (need-to-know)
drop policy if exists dossiers_read on public.dossiers;
create policy dossiers_read on public.dossiers
  for select to authenticated
  using (public.is_active_officer()
         and (created_by = auth.uid() or public.has_min_role('investigator')));

-- Create: analysts and above, as themselves
drop policy if exists dossiers_insert on public.dossiers;
create policy dossiers_insert on public.dossiers
  for insert to authenticated
  with check (public.is_active_officer()
              and public.has_min_role('analyst')
              and created_by = auth.uid());

-- Update: only your own, only while still a draft.
-- Approval status is deliberately NOT reachable from here — it moves only
-- through review_dossier(), so an author cannot approve their own work.
drop policy if exists dossiers_update on public.dossiers;
create policy dossiers_update on public.dossiers
  for update to authenticated
  using (public.is_active_officer() and created_by = auth.uid() and status = 'draft')
  with check (created_by = auth.uid() and status in ('draft', 'submitted'));

-- No delete policy at all: a dossier is evidence.

-- ---------------------------------------------------------------------
-- review_dossier — Control 8, admin only, enforced in the database.
--
-- The API layer also checks the role, but this check is what actually
-- holds: a bug in the API must not be sufficient to approve a dossier.
-- ---------------------------------------------------------------------
create or replace function public.review_dossier(
  p_dossier_id text,
  p_decision   text,
  p_remarks    text default null
) returns public.dossiers
language plpgsql security definer set search_path = public, auth as $$
declare v_row public.dossiers;
begin
  if not public.has_min_role('admin') then
    raise exception 'dossier review requires the admin role' using errcode = '42501';
  end if;
  if not public.is_active_officer() then
    raise exception 'no active officer record' using errcode = '42501';
  end if;
  if p_decision not in ('approved', 'rejected', 'returned') then
    raise exception 'decision must be approved, rejected or returned'
      using errcode = '22023';
  end if;

  select * into v_row from public.dossiers where id = p_dossier_id;
  if not found then
    raise exception 'dossier % not found', p_dossier_id using errcode = 'P0002';
  end if;

  -- Separation of duties: the author cannot sign off their own dossier,
  -- even if they hold the admin role.
  if v_row.created_by = auth.uid() then
    raise exception 'an officer cannot review their own dossier'
      using errcode = '42501';
  end if;

  if v_row.status not in ('submitted', 'returned') then
    raise exception 'dossier % is %, only submitted dossiers can be reviewed',
      p_dossier_id, v_row.status using errcode = '22023';
  end if;

  update public.dossiers
     set status = p_decision, reviewed_by = auth.uid(), reviewed_at = now(),
         review_remarks = p_remarks, updated_at = now()
   where id = p_dossier_id
   returning * into v_row;

  perform public.append_audit(
    'DOSSIER_REVIEW', 'dossier', p_dossier_id,
    jsonb_build_object('decision', p_decision, 'remarks', p_remarks));

  return v_row;
end $$;

grant execute on function public.review_dossier(text, text, text) to authenticated;

-- Direct status changes are impossible for clients: the UPDATE policy above
-- only permits draft->draft/submitted, and this function is SECURITY DEFINER.

-- ---------------------------------------------------------------------
-- Watchlist
-- ---------------------------------------------------------------------
create table if not exists public.watchlist (
  id         bigserial primary key,
  chain      text not null,
  address    text not null,
  label      text,
  reason     text,
  case_ref   text,
  officer_id uuid not null default auth.uid() references auth.users(id),
  created_at timestamptz not null default now(),
  unique (chain, address, officer_id)
);

alter table public.watchlist enable row level security;
alter table public.watchlist force row level security;

drop policy if exists watchlist_rw on public.watchlist;
create policy watchlist_rw on public.watchlist
  for all to authenticated
  using (public.is_active_officer()
         and (officer_id = auth.uid() or public.has_min_role('investigator')))
  with check (public.is_active_officer() and officer_id = auth.uid());

-- ---------------------------------------------------------------------
-- Audit trigger on dossiers, so edits are recorded even outside the RPC
-- ---------------------------------------------------------------------
drop trigger if exists trg_audit_dossiers on public.dossiers;
create trigger trg_audit_dossiers
  after insert or update or delete on public.dossiers
  for each row execute function public.audit_trigger();

-- ---------------------------------------------------------------------
-- Officer-facing view
-- ---------------------------------------------------------------------
create or replace view public.v_my_activity as
  select a.occurred_at, a.action, a.table_name, a.record_pk, a.after_data
    from public.audit_log a
   where a.actor_id = auth.uid()
   order by a.occurred_at desc
   limit 500;

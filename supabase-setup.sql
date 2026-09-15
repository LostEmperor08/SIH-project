-- ═══════════════════════════════════════════════════════════════════════
--  Chakravyuh SETU — Supabase schema
--
--  Run once in the Supabase SQL editor (Dashboard → SQL → New query → Run).
--  Safe to re-run: every statement is idempotent.
--
--  The app probes for the `profiles` table on load. Until this script has
--  run it stays on seeded browser data; afterwards it uses Supabase for
--  sign-in, roles, dossier review and the audit trail with no code change.
-- ═══════════════════════════════════════════════════════════════════════

create extension if not exists "pgcrypto";

-- ── Officers ───────────────────────────────────────────────────────────
create table if not exists public.profiles (
  id           uuid primary key references auth.users on delete cascade,
  email        text unique not null,
  full_name    text,
  badge_id     text,
  station_code text,
  clearance    text default 'Tier 1 - Unit Attribution',
  role         text not null default 'investigator'
               check (role in ('admin', 'investigator', 'viewer')),
  status       text not null default 'active'
               check (status in ('active', 'pending', 'suspended')),
  created_at   timestamptz not null default now()
);

-- ── Audit trail ────────────────────────────────────────────────────────
create table if not exists public.audit_log (
  id          bigserial primary key,
  actor_id    uuid references auth.users on delete set null,
  actor_email text,
  action      text not null,
  target      text,
  detail      jsonb,
  created_at  timestamptz not null default now()
);
create index if not exists audit_log_created_idx on public.audit_log (created_at desc);

-- ── Case data ──────────────────────────────────────────────────────────
create table if not exists public.watchlist (
  id            text primary key,
  address       text not null,
  label         text,
  chain         text,
  risk          text,
  risk_score    int,
  reason        text,
  status        text default 'ACTIVE_SURVEILLANCE',
  last_tx_value text,
  added_at      timestamptz not null default now()
);

create table if not exists public.dossiers (
  id                 text primary key,
  case_ref           text,
  title              text,
  target_vasp        text,
  deposit_address    text,
  total_traced_usdt  numeric,
  total_traced_inr   numeric,
  confidence         text,
  status             text,
  statutory_act      text,
  io_name            text,
  approval_status    text default 'pending'
                     check (approval_status in ('pending', 'approved', 'rejected')),
  approved_by        uuid references auth.users on delete set null,
  approved_at        timestamptz,
  review_note        text,
  created_at         timestamptz not null default now()
);

create table if not exists public.evidence_ledger (
  id          text primary key,
  hop         int,
  chain       text,
  tx_hash     text,
  from_addr   text,
  to_addr     text,
  value_usdt  numeric,
  risk_score  int,
  sha256      text,
  observed_at timestamptz,
  created_at  timestamptz not null default now()
);
create index if not exists evidence_hop_idx on public.evidence_ledger (hop);

-- Columns added after an earlier install.
alter table public.dossiers add column if not exists approval_status text default 'pending';
alter table public.dossiers add column if not exists approved_by uuid;
alter table public.dossiers add column if not exists approved_at timestamptz;
alter table public.dossiers add column if not exists review_note text;

-- ── A profile row per new signup ───────────────────────────────────────
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
  insert into public.profiles (id, email, full_name, badge_id, station_code, clearance)
  values (
    new.id,
    new.email,
    new.raw_user_meta_data ->> 'full_name',
    new.raw_user_meta_data ->> 'badge_id',
    new.raw_user_meta_data ->> 'station_code',
    coalesce(new.raw_user_meta_data ->> 'clearance', 'Tier 1 - Unit Attribution')
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ── Role helper (security definer, so policies don't recurse) ──────────
create or replace function public.is_admin()
returns boolean
language sql
security definer set search_path = public
stable
as $$
  select exists (
    select 1 from public.profiles
    where id = auth.uid() and role = 'admin' and status = 'active'
  );
$$;

create or replace function public.is_active_officer()
returns boolean
language sql
security definer set search_path = public
stable
as $$
  select exists (
    select 1 from public.profiles
    where id = auth.uid() and status = 'active'
  );
$$;

create or replace function public.append_audit(
  p_action text,
  p_target text default null,
  p_detail jsonb default null
)
returns void
language plpgsql
security definer set search_path = public
as $$
begin
  if not public.is_active_officer() then
    raise exception 'active officer required';
  end if;
  if p_action is null or p_action !~ '^[a-z][a-z0-9_.-]{2,80}$' then
    raise exception 'invalid audit action';
  end if;
  insert into public.audit_log (actor_id, actor_email, action, target, detail)
  select p.id, p.email, p_action, left(p_target, 300), p_detail
  from public.profiles p
  where p.id = auth.uid();
end;
$$;

create or replace function public.review_dossier(
  p_dossier_id text,
  p_approval_status text,
  p_note text default null
)
returns void
language plpgsql
security definer set search_path = public
as $$
begin
  if not public.is_admin() then
    raise exception 'active administrator required';
  end if;
  if p_approval_status not in ('pending', 'approved', 'rejected') then
    raise exception 'invalid approval status';
  end if;
  update public.dossiers
  set approval_status = p_approval_status,
      approved_by = auth.uid(),
      approved_at = case when p_approval_status = 'pending' then null else now() end,
      review_note = left(p_note, 2000)
  where id = p_dossier_id;
end;
$$;

-- ── Row level security ─────────────────────────────────────────────────
alter table public.profiles        enable row level security;
alter table public.audit_log       enable row level security;
alter table public.watchlist       enable row level security;
alter table public.dossiers        enable row level security;
alter table public.evidence_ledger enable row level security;

-- profiles: read your own, admins read and write all.
drop policy if exists profiles_self_read     on public.profiles;
drop policy if exists profiles_self_update   on public.profiles;
drop policy if exists profiles_admin_read    on public.profiles;
drop policy if exists profiles_admin_write   on public.profiles;

create policy profiles_self_read   on public.profiles for select using (auth.uid() = id);
create policy profiles_self_update on public.profiles for update using (auth.uid() = id)
  with check (
    auth.uid() = id
    and role = (select role from public.profiles where id = auth.uid())
    and status = (select status from public.profiles where id = auth.uid())
  );
create policy profiles_admin_read  on public.profiles for select using (public.is_admin());
create policy profiles_admin_write on public.profiles for update using (public.is_admin());

-- audit_log: any signed-in officer appends; admins read.
drop policy if exists audit_insert     on public.audit_log;
drop policy if exists audit_admin_read on public.audit_log;
create policy audit_insert     on public.audit_log for insert to authenticated with check (true);
create policy audit_admin_read on public.audit_log for select using (public.is_admin());
revoke insert on public.audit_log from authenticated;
grant execute on function public.append_audit(text, text, jsonb) to authenticated;

-- case data: signed-in officers read; admins and investigators write.
do $$
declare t text;
begin
  foreach t in array array['watchlist', 'dossiers', 'evidence_ledger'] loop
    execute format('drop policy if exists %I_read on public.%I', t, t);
    execute format('drop policy if exists %I_write on public.%I', t, t);
    execute format('create policy %I_read on public.%I for select to authenticated using (public.is_active_officer())', t, t);
    execute format($f$create policy %I_write on public.%I for all to authenticated
      using (exists (select 1 from public.profiles p where p.id = auth.uid()
                       and p.role in ('admin','investigator') and p.status = 'active'))
      with check (exists (select 1 from public.profiles p where p.id = auth.uid()
                       and p.role in ('admin','investigator') and p.status = 'active'))$f$, t, t);
  end loop;
end $$;

revoke update on public.dossiers from authenticated;
grant execute on function public.review_dossier(text, text, text) to authenticated;

-- ═══════════════════════════════════════════════════════════════════════
--  After running this:
--
--  1. Auth → Providers → Email: turn OFF "Confirm email" for demo use, so a
--     new signup lands straight in the dashboard.
--  2. Create your first officer through the app's Request Access screen.
--  3. Promote that account to admin (replace the address):
--
--       update public.profiles set role = 'admin', status = 'active'
--       where email = 'you@example.com';
--
--     From then on, roles are managed inside the admin panel.
-- ═══════════════════════════════════════════════════════════════════════

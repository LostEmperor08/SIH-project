-- =====================================================================
-- 02_rbac_rls.sql  —  Role-based access control + Row Level Security
-- Model: viewer < analyst < investigator < admin
-- =====================================================================

-- ---------------------------------------------------------------------
-- Role helpers.  SECURITY DEFINER + fixed search_path so an RLS policy
-- cannot be subverted by a caller-controlled search_path.
-- ---------------------------------------------------------------------
create or replace function public.current_role_name()
returns app_role_t
language sql stable security definer set search_path = public, auth as $$
  select coalesce(
    (select role from public.user_roles where user_id = auth.uid()),
    'viewer'::app_role_t
  );
$$;

create or replace function public.role_rank(r app_role_t)
returns integer language sql immutable as $$
  select case r
    when 'viewer'       then 1
    when 'analyst'      then 2
    when 'investigator' then 3
    when 'admin'        then 4
  end;
$$;

-- "Does the caller hold at least this role?"
create or replace function public.has_min_role(required app_role_t)
returns boolean
language sql stable security definer set search_path = public, auth as $$
  select public.role_rank(public.current_role_name()) >= public.role_rank(required);
$$;

create or replace function public.is_service_role()
returns boolean language sql stable as $$
  select coalesce(current_setting('request.jwt.claims', true)::jsonb ->> 'role', '') = 'service_role';
$$;

-- ---------------------------------------------------------------------
-- Auto-provision a viewer row on signup (least privilege by default)
-- ---------------------------------------------------------------------
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public, auth as $$
begin
  insert into public.user_roles (user_id, role, full_name)
  values (new.id, 'viewer', coalesce(new.raw_user_meta_data->>'full_name', new.email))
  on conflict (user_id) do nothing;
  return new;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------------
-- Enable RLS everywhere.  Default-deny: no policy == no access.
-- ---------------------------------------------------------------------
do $$
declare t text;
begin
  foreach t in array array[
    'user_roles','wallets','transactions','clusters','cluster_members',
    'threat_intel','wallet_features','risk_scores','alerts','cases','case_alerts'
  ] loop
    execute format('alter table public.%I enable row level security;', t);
    execute format('alter table public.%I force row level security;', t);
  end loop;
end $$;

-- ---------------------------------------------------------------------
-- user_roles: you see yourself; only admin manages roles.
-- Self-escalation is blocked because the UPDATE policy requires admin.
-- ---------------------------------------------------------------------
drop policy if exists ur_select_self on public.user_roles;
create policy ur_select_self on public.user_roles
  for select using (user_id = auth.uid() or public.has_min_role('admin'));

drop policy if exists ur_admin_write on public.user_roles;
create policy ur_admin_write on public.user_roles
  for all using (public.has_min_role('admin'))
  with check (public.has_min_role('admin'));

-- ---------------------------------------------------------------------
-- Read-mostly intelligence tables: any authenticated role may READ,
-- only the ingestion service (service_role) or admin may WRITE.
-- ---------------------------------------------------------------------
do $$
declare t text;
begin
  foreach t in array array[
    'wallets','transactions','clusters','cluster_members',
    'threat_intel','wallet_features','risk_scores'
  ] loop
    execute format('drop policy if exists %1$s_read on public.%1$s;', t);
    execute format($p$
      create policy %1$s_read on public.%1$s
        for select to authenticated
        using (public.has_min_role('viewer'));
    $p$, t);

    execute format('drop policy if exists %1$s_write on public.%1$s;', t);
    execute format($p$
      create policy %1$s_write on public.%1$s
        for all
        using (public.is_service_role() or public.has_min_role('admin'))
        with check (public.is_service_role() or public.has_min_role('admin'));
    $p$, t);
  end loop;
end $$;

-- ---------------------------------------------------------------------
-- Alerts: analysts read + triage; investigators may escalate/close;
-- viewers see only non-sensitive open alerts.
-- ---------------------------------------------------------------------
drop policy if exists alerts_read on public.alerts;
create policy alerts_read on public.alerts
  for select to authenticated
  using (
    public.has_min_role('analyst')
    or (public.has_min_role('viewer') and severity < 80)
  );

drop policy if exists alerts_insert on public.alerts;
create policy alerts_insert on public.alerts
  for insert to authenticated
  with check (public.is_service_role() or public.has_min_role('analyst'));

drop policy if exists alerts_update on public.alerts;
create policy alerts_update on public.alerts
  for update to authenticated
  using (
    public.has_min_role('investigator')
    or (public.has_min_role('analyst') and assigned_to = auth.uid())
  )
  with check (
    public.has_min_role('investigator')
    or (public.has_min_role('analyst') and status in ('open','triaged'))
  );

drop policy if exists alerts_delete on public.alerts;
create policy alerts_delete on public.alerts
  for delete to authenticated using (public.has_min_role('admin'));

-- ---------------------------------------------------------------------
-- Cases: need-to-know. Lead analyst + investigators + admin.
-- ---------------------------------------------------------------------
drop policy if exists cases_read on public.cases;
create policy cases_read on public.cases
  for select to authenticated
  using (lead_analyst = auth.uid() or public.has_min_role('investigator'));

drop policy if exists cases_write on public.cases;
create policy cases_write on public.cases
  for all to authenticated
  using (lead_analyst = auth.uid() or public.has_min_role('investigator'))
  with check (public.has_min_role('analyst'));

drop policy if exists case_alerts_rw on public.case_alerts;
create policy case_alerts_rw on public.case_alerts
  for all to authenticated
  using (exists (select 1 from public.cases c where c.id = case_id
                 and (c.lead_analyst = auth.uid() or public.has_min_role('investigator'))))
  with check (public.has_min_role('analyst'));

-- ---------------------------------------------------------------------
-- Column-level hardening: hide raw payloads from viewers.
-- (Postgres column privileges compose with RLS.)
-- ---------------------------------------------------------------------
revoke all on public.transactions from authenticated;
grant select (id, chain, tx_hash, block_height, block_time, from_address,
              to_address, value_native, value_usd, fee_usd, asset)
  on public.transactions to authenticated;

-- ---------------------------------------------------------------------
-- Encryption at rest for analyst notes (pgcrypto, key held in Vault).
-- Store the key in Supabase Vault:  select vault.create_secret('<32b key>','skv_field_key');
-- ---------------------------------------------------------------------
create or replace function public.encrypt_field(plaintext text)
returns bytea
language plpgsql security definer set search_path = public, vault, extensions as $$
declare k text;
begin
  select decrypted_secret into k from vault.decrypted_secrets where name = 'skv_field_key';
  if k is null then raise exception 'skv_field_key not present in Vault'; end if;
  return extensions.pgp_sym_encrypt(plaintext, k, 'cipher-algo=aes256');
end $$;

create or replace function public.decrypt_field(ciphertext bytea)
returns text
language plpgsql security definer set search_path = public, vault, extensions as $$
declare k text;
begin
  if not public.has_min_role('investigator') then
    raise exception 'insufficient privilege to decrypt' using errcode = '42501';
  end if;
  select decrypted_secret into k from vault.decrypted_secrets where name = 'skv_field_key';
  return extensions.pgp_sym_decrypt(ciphertext, k);
end $$;

revoke execute on function public.encrypt_field(text) from public;
revoke execute on function public.decrypt_field(bytea) from public;
grant  execute on function public.encrypt_field(text)  to authenticated;
grant  execute on function public.decrypt_field(bytea) to authenticated;

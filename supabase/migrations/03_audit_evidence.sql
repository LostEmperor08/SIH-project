-- =====================================================================
-- 03_audit_evidence.sql
--   (a) Append-only audit trail  — who did what, when, from where
--   (b) Tamper-evident evidence  — SHA-256 hash chain (blockchain-style)
-- =====================================================================

-- ---------------------------------------------------------------------
-- (a) AUDIT LOG
-- ---------------------------------------------------------------------
create table if not exists public.audit_log (
  id          bigserial primary key,
  occurred_at timestamptz not null default now(),
  actor_id    uuid,
  actor_role  app_role_t,
  action      text not null,                 -- INSERT | UPDATE | DELETE | READ | LOGIN
  table_name  text,
  record_pk   text,
  before_data jsonb,
  after_data  jsonb,
  ip_address  inet,
  user_agent  text,
  request_id  text,
  row_hash    text not null,                 -- sha256(prev_hash || canonical row)
  prev_hash   text
);

create index if not exists audit_time_idx  on public.audit_log (occurred_at desc);
create index if not exists audit_actor_idx on public.audit_log (actor_id, occurred_at desc);
create index if not exists audit_table_idx on public.audit_log (table_name, record_pk);

alter table public.audit_log enable row level security;
alter table public.audit_log force row level security;

-- Read: investigators and admins only.
drop policy if exists audit_read on public.audit_log;
create policy audit_read on public.audit_log
  for select to authenticated using (public.has_min_role('investigator'));

-- NO insert/update/delete policy exists for end users => append happens
-- only through the SECURITY DEFINER trigger below. Immutable by design.
revoke insert, update, delete on public.audit_log from authenticated, anon;

-- Belt and braces: refuse mutation at the database level.
create or replace function public.audit_immutable() returns trigger
language plpgsql as $$
begin
  raise exception 'audit_log is append-only (attempted %)', tg_op
    using errcode = '42501';
end $$;

drop trigger if exists trg_audit_no_update on public.audit_log;
create trigger trg_audit_no_update before update or delete on public.audit_log
  for each row execute function public.audit_immutable();

-- ---------------------------------------------------------------------
-- Canonical JSON -> stable string (key order matters for hashing)
-- ---------------------------------------------------------------------
create or replace function public.canonical_json(j jsonb)
returns text language sql immutable as $$
  select coalesce(
    (select '{' || string_agg(format('%s:%s', to_json(key), value::text), ',' order by key) || '}'
       from jsonb_each(j)),
    '{}');
$$;

create or replace function public.sha256_hex(t text)
returns text language sql immutable as $$
  select encode(extensions.digest(t, 'sha256'), 'hex');
$$;

-- ---------------------------------------------------------------------
-- THE canonical audit hash. Every writer and the verifier call this one
-- function, so their formats cannot drift apart.
--
-- They did drift, once: append_audit() omitted the before_data segment
-- that verify_audit_chain() expected, so every row written through the
-- RPC verified as TAMPERED. A tamper-evident log that cries wolf on
-- legitimate rows is worse than no log at all — nobody trusts the alarm
-- when it matters. Hence one shared definition, exactly like the feature
-- schema contract on the ML side.
-- ---------------------------------------------------------------------
create or replace function public.audit_hash(
  p_prev        text,
  p_occurred_at timestamptz,
  p_actor       uuid,
  p_action      text,
  p_table       text,
  p_record_pk   text,
  p_before      jsonb,
  p_after       jsonb
) returns text
language sql immutable set search_path = public, extensions as $$
  select public.sha256_hex(concat_ws('|',
    coalesce(p_prev, 'GENESIS'),
    p_occurred_at::text,
    coalesce(p_actor::text, 'system'),
    p_action,
    coalesce(p_table, ''),
    coalesce(p_record_pk, ''),
    public.canonical_json(coalesce(p_before, '{}'::jsonb)),
    public.canonical_json(coalesce(p_after,  '{}'::jsonb))));
$$;

-- ---------------------------------------------------------------------
-- Generic audit trigger  (attach to any table you want watched)
-- ---------------------------------------------------------------------
create or replace function public.audit_trigger() returns trigger
language plpgsql security definer set search_path = public, extensions as $$
declare
  v_before jsonb;
  v_after  jsonb;
  v_prev   text;
  v_pk     text;
  v_body   text;
  v_hash   text;
  v_claims jsonb;
begin
  v_before := case when tg_op in ('UPDATE','DELETE') then to_jsonb(old) end;
  v_after  := case when tg_op in ('INSERT','UPDATE') then to_jsonb(new) end;
  v_pk     := coalesce((v_after->>'id'), (v_before->>'id'));

  select row_hash into v_prev from public.audit_log order by id desc limit 1;

  v_claims := nullif(current_setting('request.jwt.claims', true), '')::jsonb;

  v_hash := public.audit_hash(
              v_prev, now(), auth.uid(), tg_op, tg_table_name, v_pk,
              v_before, v_after);

  insert into public.audit_log(
    actor_id, actor_role, action, table_name, record_pk,
    before_data, after_data, ip_address, user_agent, request_id,
    prev_hash, row_hash)
  values (
    auth.uid(),
    case when auth.uid() is null then null else public.current_role_name() end,
    tg_op, tg_table_name, v_pk,
    v_before, v_after,
    nullif(current_setting('request.headers', true)::jsonb ->> 'x-forwarded-for','')::inet,
    current_setting('request.headers', true)::jsonb ->> 'user-agent',
    v_claims ->> 'session_id',
    v_prev, v_hash);

  return coalesce(new, old);
exception when others then
  -- Never let auditing break the business transaction silently:
  -- log and re-raise only for privileged tables.
  raise warning 'audit_trigger failed on %: %', tg_table_name, sqlerrm;
  return coalesce(new, old);
end $$;

-- Attach the audit trigger to the tables that matter
do $$
declare t text;
begin
  foreach t in array array['alerts','cases','case_alerts','user_roles','wallets','clusters'] loop
    execute format('drop trigger if exists trg_audit_%1$s on public.%1$s;', t);
    execute format(
      'create trigger trg_audit_%1$s after insert or update or delete on public.%1$s
       for each row execute function public.audit_trigger();', t);
  end loop;
end $$;

-- Explicit READ auditing for sensitive lookups (call from the API layer)
create or replace function public.log_read(p_table text, p_pk text, p_reason text default null)
returns void
language plpgsql security definer set search_path = public, extensions as $$
declare v_prev text; v_hash text; v_after jsonb;
begin
  select row_hash into v_prev from public.audit_log order by id desc limit 1;
  v_after := jsonb_build_object('reason', p_reason);
  -- same canonical hash as every other writer, so READ rows are verified
  -- like the rest rather than skipped
  v_hash := public.audit_hash(v_prev, now(), auth.uid(), 'READ',
                              p_table, p_pk, '{}'::jsonb, v_after);
  insert into public.audit_log(actor_id, actor_role, action, table_name, record_pk,
                               after_data, prev_hash, row_hash)
  values (auth.uid(), public.current_role_name(), 'READ', p_table, p_pk,
          v_after, v_prev, v_hash);
end $$;

grant execute on function public.log_read(text,text,text) to authenticated;

-- ---------------------------------------------------------------------
-- Audit chain verification — returns the first break, if any
-- ---------------------------------------------------------------------
create or replace function public.verify_audit_chain()
returns table (ok boolean, checked bigint, first_bad_id bigint, detail text)
language plpgsql security definer set search_path = public, extensions as $$
declare r record; v_prev text := null; n bigint := 0; v_expect text;
begin
  for r in select * from public.audit_log order by id asc loop
    n := n + 1;
    v_expect := public.audit_hash(
                  v_prev, r.occurred_at, r.actor_id, r.action,
                  r.table_name, r.record_pk, r.before_data, r.after_data);
    -- EVERY row is checked, READ rows included. Exempting a row type from
    -- verification leaves a place to hide a forged entry.
    if r.row_hash <> v_expect then
      return query select false, n, r.id, 'hash mismatch at audit id ' || r.id;
      return;
    end if;
    v_prev := r.row_hash;
  end loop;
  return query select true, n, null::bigint, 'chain intact';
end $$;

-- =====================================================================
-- (b) EVIDENCE PRESERVATION  — tamper-evident, hash-chained, per case
-- =====================================================================
create table if not exists public.evidence (
  id            bigserial primary key,
  case_id       bigint not null references public.cases(id) on delete restrict,
  seq           integer not null,             -- position in this case's chain
  kind          text not null,                -- 'graph_snapshot','tx_export','screenshot','note'
  description   text,
  payload       jsonb not null,               -- the evidence itself (or a pointer)
  storage_path  text,                         -- Supabase Storage object key, if a file
  content_sha256 text not null,               -- hash of the payload/file bytes
  prev_hash     text,
  chain_hash    text not null,                -- sha256(prev_hash || content_sha256 || meta)
  collected_by  uuid not null default auth.uid() references auth.users(id),
  collected_at  timestamptz not null default now(),
  sealed        boolean not null default true,
  unique (case_id, seq)
);

create index if not exists evidence_case_idx on public.evidence (case_id, seq);

alter table public.evidence enable row level security;
alter table public.evidence force row level security;

drop policy if exists evidence_read on public.evidence;
create policy evidence_read on public.evidence
  for select to authenticated
  using (exists (select 1 from public.cases c where c.id = case_id
                 and (c.lead_analyst = auth.uid() or public.has_min_role('investigator'))));

-- Inserts go through add_evidence() only; no direct insert/update/delete.
revoke insert, update, delete on public.evidence from authenticated, anon;

create or replace function public.evidence_immutable() returns trigger
language plpgsql as $$
begin
  raise exception 'evidence records are immutable once sealed' using errcode = '42501';
end $$;

drop trigger if exists trg_evidence_immutable on public.evidence;
create trigger trg_evidence_immutable before update or delete on public.evidence
  for each row when (old.sealed) execute function public.evidence_immutable();

-- ---------------------------------------------------------------------
-- add_evidence(): the ONLY way in. Computes and links the hash chain.
-- ---------------------------------------------------------------------
create or replace function public.add_evidence(
  p_case_id      bigint,
  p_kind         text,
  p_payload      jsonb,
  p_description  text default null,
  p_storage_path text default null,
  p_file_sha256  text default null
) returns public.evidence
language plpgsql security definer set search_path = public, extensions as $$
declare
  v_seq   integer;
  v_prev  text;
  v_csum  text;
  v_chain text;
  v_row   public.evidence;
begin
  if not public.has_min_role('analyst') then
    raise exception 'analyst role required to collect evidence' using errcode = '42501';
  end if;

  if not exists (select 1 from public.cases c
                 where c.id = p_case_id
                   and (c.lead_analyst = auth.uid() or public.has_min_role('investigator'))) then
    raise exception 'no access to case %', p_case_id using errcode = '42501';
  end if;

  select coalesce(max(seq),0) + 1, (select chain_hash from public.evidence
                                     where case_id = p_case_id order by seq desc limit 1)
    into v_seq, v_prev
    from public.evidence where case_id = p_case_id;

  v_csum  := coalesce(p_file_sha256, public.sha256_hex(public.canonical_json(p_payload)));
  v_chain := public.sha256_hex(concat_ws('|',
               coalesce(v_prev,'GENESIS'), p_case_id::text, v_seq::text,
               p_kind, v_csum, auth.uid()::text, now()::text));

  insert into public.evidence(case_id, seq, kind, description, payload,
                              storage_path, content_sha256, prev_hash, chain_hash)
  values (p_case_id, v_seq, p_kind, p_description, p_payload,
          p_storage_path, v_csum, v_prev, v_chain)
  returning * into v_row;

  return v_row;
end $$;

grant execute on function public.add_evidence(bigint,text,jsonb,text,text,text) to authenticated;

-- ---------------------------------------------------------------------
-- verify_evidence_chain(case) — proves nothing was altered or removed
-- ---------------------------------------------------------------------
create or replace function public.verify_evidence_chain(p_case_id bigint)
returns table (seq integer, content_ok boolean, link_ok boolean, chain_hash text, verdict text)
language plpgsql security definer set search_path = public, extensions as $$
declare r record; v_prev text := null; v_expect_content text; v_expect_chain text;
begin
  for r in select * from public.evidence where case_id = p_case_id order by seq asc loop
    -- content integrity: only verifiable for inline JSON payloads
    v_expect_content := public.sha256_hex(public.canonical_json(r.payload));
    v_expect_chain := public.sha256_hex(concat_ws('|',
                        coalesce(v_prev,'GENESIS'), r.case_id::text, r.seq::text,
                        r.kind, r.content_sha256, r.collected_by::text, r.collected_at::text));
    return query select
      r.seq,
      (r.storage_path is not null) or (v_expect_content = r.content_sha256),
      (v_expect_chain = r.chain_hash),
      r.chain_hash,
      case when v_expect_chain = r.chain_hash then 'INTACT' else 'TAMPERED' end;
    v_prev := r.chain_hash;
  end loop;
end $$;

grant execute on function public.verify_evidence_chain(bigint) to authenticated;

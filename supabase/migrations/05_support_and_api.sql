-- =====================================================================
-- 05_support_and_api.sql
-- Helper RPCs called by the edge functions + the read APIs the
-- frontend calls directly via supabase.rpc().
-- =====================================================================

-- ---------------------------------------------------------------------
-- Recompute wallet aggregates after an ingest batch
-- ---------------------------------------------------------------------
create or replace function public.refresh_wallet_stats(p_chain chain_t)
returns integer
language plpgsql security definer set search_path = public as $$
declare n integer;
begin
  with agg as (
    select w.id,
           min(t.block_time) as first_seen,
           max(t.block_time) as last_seen,
           count(*)                                              as tx_count,
           count(*) filter (where t.to_address   = w.address)     as in_count,
           count(*) filter (where t.from_address = w.address)     as out_count,
           coalesce(sum(t.value_usd) filter (where t.to_address   = w.address),0) as in_usd,
           coalesce(sum(t.value_usd) filter (where t.from_address = w.address),0) as out_usd
      from public.wallets w
      join public.transactions t
        on t.chain = w.chain
       and (t.from_address = w.address or t.to_address = w.address)
     where w.chain = p_chain
     group by w.id
  )
  update public.wallets w
     set first_seen    = a.first_seen,
         last_seen     = a.last_seen,
         tx_count      = a.tx_count,
         in_count      = a.in_count,
         out_count     = a.out_count,
         total_in_usd  = a.in_usd,
         total_out_usd = a.out_usd,
         updated_at    = now()
    from agg a where w.id = a.id;

  get diagnostics n = row_count;
  return n;
end $$;

-- ---------------------------------------------------------------------
-- Flag wallets that appear in the threat-intel feed
-- ---------------------------------------------------------------------
create or replace function public.apply_threat_intel()
returns integer
language plpgsql security definer set search_path = public as $$
declare n integer;
begin
  update public.wallets w
     set is_sanctioned = (ti.category = 'sanctioned'),
         entity_type   = ti.category,
         labels        = array(select distinct unnest(w.labels || array[ti.source])),
         updated_at    = now()
    from public.threat_intel ti
   where ti.chain = w.chain
     and lower(ti.address) = lower(w.address)
     and (w.entity_type is distinct from ti.category
          or w.is_sanctioned is distinct from (ti.category = 'sanctioned'));
  get diagnostics n = row_count;
  return n;
end $$;

-- ---------------------------------------------------------------------
-- Link clustered addresses to wallet rows
--   p_pairs :: jsonb array of { "root": "...", "address": "..." }
-- ---------------------------------------------------------------------
create or replace function public.link_cluster_members(p_chain chain_t, p_pairs jsonb)
returns integer
language plpgsql security definer set search_path = public as $$
declare n integer;
begin
  insert into public.cluster_members (cluster_id, wallet_id, joined_via, confidence)
  select c.id, w.id, 'co_spend', 1.0
    from jsonb_to_recordset(p_pairs) as p(root text, address text)
    join public.clusters c on c.chain = p_chain and c.root_address = p.root
    join public.wallets  w on w.chain = p_chain and w.address      = p.address
  on conflict (cluster_id, wallet_id) do nothing;
  get diagnostics n = row_count;
  return n;
end $$;

-- ---------------------------------------------------------------------
-- Push cluster-level attribution down to member wallets
-- ---------------------------------------------------------------------
create or replace function public.propagate_cluster_labels(p_chain chain_t)
returns integer
language plpgsql security definer set search_path = public as $$
declare n integer;
begin
  update public.wallets w
     set entity_type     = c.entity_type,
         vasp_name       = coalesce(w.vasp_name, c.vasp_name),
         vasp_confidence = c.vasp_confidence,
         updated_at      = now()
    from public.cluster_members cm
    join public.clusters c on c.id = cm.cluster_id
   where cm.wallet_id = w.id
     and w.chain = p_chain
     and c.entity_type <> 'unknown'
     and w.is_sanctioned = false;          -- never overwrite a sanctions hit
  get diagnostics n = row_count;
  return n;
end $$;

-- =====================================================================
-- READ APIs for the frontend
-- =====================================================================

-- Live dashboard payload in one round trip
create or replace function public.api_dashboard()
returns jsonb
language sql stable security invoker set search_path = public as $$
  select jsonb_build_object(
    'metrics', (select to_jsonb(m) from public.v_live_metrics m),
    'topRisk', (select coalesce(jsonb_agg(x), '[]'::jsonb) from (
        select address, chain, entity_type, vasp_name, is_sanctioned,
               score, band, contributions, tx_count, balance_usd
          from public.v_wallet_risk
         where score is not null
         order by score desc limit 15) x),
    'recentAlerts', (select coalesce(jsonb_agg(x), '[]'::jsonb) from (
        select a.id, a.rule_code, a.title, a.detail, a.severity, a.status,
               a.created_at, w.address
          from public.alerts a left join public.wallets w on w.id = a.wallet_id
         where a.status in ('open','triaged')
         order by a.severity desc, a.created_at desc limit 20) x),
    'entityBreakdown', (select coalesce(jsonb_object_agg(entity_type, n), '{}'::jsonb) from (
        select entity_type, count(*) n from public.wallets group by 1) e),
    'volumeSeries', (select coalesce(jsonb_agg(x order by x->>'t'), '[]'::jsonb) from (
        select jsonb_build_object(
                 't', to_char(date_trunc('hour', block_time), 'YYYY-MM-DD"T"HH24:00'),
                 'volumeUsd', round(sum(value_usd)),
                 'txCount', count(*)) as x
          from public.transactions
         where block_time > now() - interval '24 hours'
         group by date_trunc('hour', block_time)) v)
  );
$$;

grant execute on function public.api_dashboard() to authenticated;

-- Full investigation view for one address
create or replace function public.api_investigate(p_chain chain_t, p_address text, p_hops integer default 2)
returns jsonb
language plpgsql stable security invoker set search_path = public as $$
declare v jsonb;
begin
  -- record the lookup in the audit trail (need-to-know accountability)
  perform public.log_read('wallets', p_address, 'investigation lookup');

  select jsonb_build_object(
    'wallet', (select to_jsonb(r) from public.v_wallet_risk r
                where r.chain = p_chain and r.address = p_address),
    'graph',  public.graph_neighbourhood(p_chain, p_address, p_hops),
    'cluster', (select jsonb_build_object(
                  'id', c.id, 'size', c.size, 'entity', c.entity_type,
                  'vasp', c.vasp_name, 'confidence', c.vasp_confidence,
                  'evidence', c.attribution_evidence)
                  from public.clusters c
                  join public.cluster_members cm on cm.cluster_id = c.id
                  join public.wallets w on w.id = cm.wallet_id
                 where w.chain = p_chain and w.address = p_address limit 1),
    'sanctionPaths', (select coalesce(jsonb_agg(x), '[]'::jsonb) from (
        select jsonb_build_object('hop', hop, 'path', path,
                                  'valueUsd', value_usd, 'taint', taint_share) x
          from public.trace_funds(p_chain, p_address, p_hops, 'forward')
         where to_address in (select address from public.threat_intel where chain = p_chain)
         limit 50) s),
    'alerts', (select coalesce(jsonb_agg(to_jsonb(a)), '[]'::jsonb)
                 from public.alerts a
                 join public.wallets w on w.id = a.wallet_id
                where w.chain = p_chain and w.address = p_address)
  ) into v;
  return v;
end $$;

grant execute on function public.api_investigate(chain_t,text,integer) to authenticated;

-- =====================================================================
-- SCHEDULING — keeps the data live without anyone clicking anything
-- Requires: create extension pg_cron; create extension pg_net;
-- Store your service key once:
--   select vault.create_secret('<SERVICE_ROLE_KEY>', 'service_key');
-- =====================================================================
create extension if not exists pg_cron;
create extension if not exists pg_net;

create or replace function public.invoke_edge(fn text, body jsonb default '{}'::jsonb)
returns bigint
language plpgsql security definer set search_path = public, vault, net as $$
declare k text; url text;
begin
  select decrypted_secret into k from vault.decrypted_secrets where name = 'service_key';
  url := current_setting('app.settings.functions_url', true);
  if url is null then
    raise exception 'set app.settings.functions_url to https://<project-ref>.supabase.co/functions/v1';
  end if;
  return net.http_post(
    url      := url || '/' || fn,
    headers  := jsonb_build_object('Content-Type','application/json',
                                   'Authorization','Bearer ' || k),
    body     := body,
    timeout_milliseconds := 55000);
end $$;

-- Example schedule (run once, then check `select * from cron.job;`)
-- select cron.schedule('skv-ingest-btc',  '*/5 * * * *',  $$select public.invoke_edge('ingest-chain', '{"chain":"btc","blocks":1}')$$);
-- select cron.schedule('skv-ingest-eth',  '*/3 * * * *',  $$select public.invoke_edge('ingest-chain', '{"chain":"eth","blocks":2}')$$);
-- select cron.schedule('skv-cluster',     '*/15 * * * *', $$select public.invoke_edge('cluster-attribute', '{"chain":"btc"}')$$);
-- select cron.schedule('skv-threatintel', '17 * * * *',   $$select public.invoke_edge('sync-threat-intel')$$);

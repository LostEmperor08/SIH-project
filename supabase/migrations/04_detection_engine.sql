-- =====================================================================
-- 04_detection_engine.sql
-- The cybersecurity core: transaction-graph analysis, behavioural
-- anomaly detection, threat-intel proximity and composite risk scoring.
-- All functions are callable from the frontend via supabase.rpc().
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. TRANSACTION GRAPH TRAVERSAL
--    Multi-hop fund tracing with cycle protection and value decay.
--    Value decay = the share of the original amount still attributable
--    to this path (poison/haircut model used in real forensics).
-- ---------------------------------------------------------------------
create or replace function public.trace_funds(
  p_chain      chain_t,
  p_address    text,
  p_max_hops   integer default 4,
  p_direction  text    default 'forward',      -- 'forward' | 'backward'
  p_min_usd    numeric default 0
)
returns table (
  hop            integer,
  from_address   text,
  to_address     text,
  tx_hash        text,
  value_usd      numeric,
  block_time     timestamptz,
  taint_share    numeric,
  path           text[]
)
language sql stable security invoker set search_path = public as $$
  with recursive walk as (
    -- seed
    select 1 as hop,
           t.from_address, t.to_address, t.tx_hash, t.value_usd, t.block_time,
           1.0::numeric as taint_share,
           array[case when p_direction = 'forward' then t.from_address else t.to_address end,
                 case when p_direction = 'forward' then t.to_address   else t.from_address end] as path
      from public.transactions t
     where t.chain = p_chain
       and t.value_usd >= p_min_usd
       and ((p_direction = 'forward'  and t.from_address = p_address)
         or (p_direction = 'backward' and t.to_address   = p_address))

    union all

    select w.hop + 1,
           t.from_address, t.to_address, t.tx_hash, t.value_usd, t.block_time,
           -- haircut: split taint proportionally across the next hop's outflow
           (w.taint_share * least(1.0, t.value_usd / nullif(w.value_usd,0)))::numeric,
           w.path || (case when p_direction = 'forward' then t.to_address else t.from_address end)
      from walk w
      join public.transactions t
        on t.chain = p_chain
       and t.value_usd >= p_min_usd
       and ((p_direction = 'forward'  and t.from_address = w.to_address
             and t.block_time >= w.block_time)
         or (p_direction = 'backward' and t.to_address   = w.from_address
             and t.block_time <= w.block_time))
     where w.hop < p_max_hops
       -- cycle protection
       and not ((case when p_direction = 'forward' then t.to_address else t.from_address end)
                = any(w.path))
       and w.taint_share > 0.001
  )
  select hop, from_address, to_address, tx_hash, value_usd, block_time,
         round(taint_share, 6), path
    from walk
   order by hop, value_usd desc
   limit 5000;
$$;

grant execute on function public.trace_funds(chain_t,text,integer,text,numeric) to authenticated;

-- ---------------------------------------------------------------------
-- 2. GRAPH SUBGRAPH for the UI (nodes + edges, ready for cytoscape/d3)
-- ---------------------------------------------------------------------
create or replace function public.graph_neighbourhood(
  p_chain   chain_t,
  p_address text,
  p_hops    integer default 2,
  p_limit   integer default 300
) returns jsonb
language sql stable security invoker set search_path = public as $$
  with edges as (
    select * from (
      select t.from_address, t.to_address, t.tx_hash, t.value_usd, t.block_time
        from public.transactions t
       where t.chain = p_chain
         and (t.from_address = p_address or t.to_address = p_address)
      union
      select f.from_address, f.to_address, f.tx_hash, f.value_usd, f.block_time
        from public.trace_funds(p_chain, p_address, p_hops, 'forward') f
      union
      select b.from_address, b.to_address, b.tx_hash, b.value_usd, b.block_time
        from public.trace_funds(p_chain, p_address, p_hops, 'backward') b
    ) u
    order by u.value_usd desc
    limit p_limit
  ),
  verts as (
    select from_address as a from edges
    union
    select to_address   as a from edges
  ),
  nodes as (
    select jsonb_agg(jsonb_build_object(
             'id', w.address,
             'label', coalesce(w.vasp_name, left(w.address, 10) || '…'),
             'entity', w.entity_type,
             'sanctioned', w.is_sanctioned,
             'risk', coalesce(r.score, 0),
             'balanceUsd', w.balance_usd,
             'txCount', w.tx_count,
             'isSeed', (w.address = p_address))) as j
      from public.wallets w
      join verts v on v.a = w.address
      left join lateral (select rs.score from public.risk_scores rs
                          where rs.wallet_id = w.id
                          order by rs.scored_at desc limit 1) r on true
     where w.chain = p_chain
  ),
  links as (
    select jsonb_agg(jsonb_build_object(
             'source', e.from_address, 'target', e.to_address,
             'txHash', e.tx_hash, 'valueUsd', e.value_usd, 'time', e.block_time)) as j
      from edges e
  )
  select jsonb_build_object(
           'nodes', coalesce((select j from nodes), '[]'::jsonb),
           'edges', coalesce((select j from links), '[]'::jsonb),
           'seed',  p_address,
           'generatedAt', now());
$$;

grant execute on function public.graph_neighbourhood(chain_t,text,integer,integer) to authenticated;

-- ---------------------------------------------------------------------
-- 3. BEHAVIOURAL FEATURE EXTRACTION
--    Recomputes wallet_features from raw transactions.
-- ---------------------------------------------------------------------
create or replace function public.compute_wallet_features(p_chain chain_t, p_since interval default '90 days')
returns integer
language plpgsql security definer set search_path = public as $$
declare n integer;
begin
  with flows as (
    select w.id as wallet_id, w.address,
           t.value_usd, t.block_time,
           case when t.to_address = w.address then 'in' else 'out' end as dir,
           case when t.to_address = w.address then t.from_address else t.to_address end as counterparty
      from public.wallets w
      join public.transactions t
        on t.chain = w.chain
       and (t.from_address = w.address or t.to_address = w.address)
     where w.chain = p_chain
       and t.block_time > now() - p_since
  ),
  agg as (
    select wallet_id,
           count(*)::numeric / greatest(extract(epoch from (max(block_time)-min(block_time)))/86400, 1)
             as tx_velocity,
           avg(value_usd) as avg_v,
           coalesce(stddev_pop(value_usd),0) as sd_v,
           -- "round" amounts: a strong structuring / automation tell
           avg(case when value_usd > 0
                     and (value_usd = round(value_usd, -2) or value_usd = round(value_usd, -3))
                    then 1 else 0 end)::numeric as round_ratio,
           count(distinct counterparty) filter (where dir='in')  as fan_in,
           count(distinct counterparty) filter (where dir='out') as fan_out,
           avg(case when extract(hour from block_time at time zone 'UTC') < 5
                    then 1 else 0 end)::numeric as night_ratio,
           extract(epoch from (now() - max(block_time)))/86400 as dormancy,
           -- structuring: share of transfers sitting just under $10k
           avg(case when value_usd between 8000 and 9999 then 1 else 0 end)::numeric as structuring
      from flows group by wallet_id
  ),
  ent as (   -- Shannon entropy of counterparty distribution
    select wallet_id,
           -sum(p * ln(p)) as entropy
      from (select wallet_id, counterparty,
                   count(*)::numeric / sum(count(*)) over (partition by wallet_id) as p
              from flows group by wallet_id, counterparty) s
     group by wallet_id
  )
  insert into public.wallet_features as f (
    wallet_id, tx_velocity_7d, avg_value_usd, value_stddev_usd, round_amount_ratio,
    fan_in, fan_out, night_activity_ratio, dormancy_days, counterparty_entropy,
    structuring_score, computed_at)
  select a.wallet_id, a.tx_velocity, a.avg_v, a.sd_v, a.round_ratio,
         a.fan_in, a.fan_out, a.night_ratio, a.dormancy,
         coalesce(e.entropy,0), a.structuring, now()
    from agg a left join ent e using (wallet_id)
  on conflict (wallet_id) do update set
    tx_velocity_7d       = excluded.tx_velocity_7d,
    avg_value_usd        = excluded.avg_value_usd,
    value_stddev_usd     = excluded.value_stddev_usd,
    round_amount_ratio   = excluded.round_amount_ratio,
    fan_in               = excluded.fan_in,
    fan_out              = excluded.fan_out,
    night_activity_ratio = excluded.night_activity_ratio,
    dormancy_days        = excluded.dormancy_days,
    counterparty_entropy = excluded.counterparty_entropy,
    structuring_score    = excluded.structuring_score,
    computed_at          = now();

  get diagnostics n = row_count;

  -- Peel-chain depth: long single-hop chains where most value moves on
  -- and a small remainder is peeled off. Classic laundering pattern.
  -- A peel chain is a *temporally ordered* walk in which each hop keeps
  -- 70-98% of the previous value (the rest is "peeled" off). Both the
  -- value floor and the strict time ordering are required: without the
  -- time constraint the recursion explores physically impossible paths
  -- and blows up combinatorially.
  with recursive peel as (
    select t.from_address as origin, t.to_address as node, 1 as depth,
           t.value_usd, t.block_time, t.chain,
           array[t.from_address, t.to_address] as seen
      from public.transactions t
     where t.chain = p_chain
       and t.block_time > now() - p_since
       and t.value_usd > 100
    union all
    select p.origin, t.to_address, p.depth + 1,
           t.value_usd, t.block_time, t.chain,
           p.seen || t.to_address
      from peel p
      join public.transactions t
        on t.chain = p.chain
       and t.from_address = p.node
       and t.block_time > p.block_time                     -- strictly forward in time
       and t.block_time < p.block_time + interval '7 days' -- and within a plausible window
       and t.value_usd between p.value_usd * 0.70 and p.value_usd * 0.98
     where p.depth < 6                 -- depth 6 already identifies a peel chain
       and not (t.to_address = any(p.seen))                -- no revisits
  )
  update public.wallet_features f
     set peel_chain_depth = d.max_depth
    from (select w.id as wallet_id, max(p.depth) as max_depth
            from peel p join public.wallets w
              on w.chain = p_chain and w.address = p.origin
           group by w.id) d
   where f.wallet_id = d.wallet_id;

  -- Hops to nearest mixer / sanctioned address.
  -- Level-by-level BFS with a visited set: O(V+E). A recursive CTE
  -- cannot express "stop when already visited" across branches, so on a
  -- dense transaction graph it re-walks the same nodes exponentially.
  perform public.compute_proximity(p_chain, 'mixer');
  perform public.compute_proximity(p_chain, 'sanctioned');

  return n;
end $$;

-- ---------------------------------------------------------------------
-- Iterative BFS from every seed of a given kind, writing the hop count
-- of the nearest seed onto each reachable wallet.
--   p_kind: 'mixer' -> wallet_features.mixer_hops
--           'sanctioned' -> wallet_features.sanction_hops
-- ---------------------------------------------------------------------
create or replace function public.compute_proximity(p_chain chain_t, p_kind text, p_max_hops integer default 4)
returns integer
language plpgsql security definer set search_path = public as $$
declare h integer := 0; touched integer := 0; more integer;
begin
  -- both kinds run inside one transaction, so always start clean
  -- (to_regclass avoids the NOTICE spam of DROP TABLE IF EXISTS)
  if to_regclass('pg_temp._visited')  is not null then drop table _visited;  end if;
  if to_regclass('pg_temp._frontier') is not null then drop table _frontier; end if;
  if to_regclass('pg_temp._next')     is not null then drop table _next;     end if;

  create temp table _visited (address text primary key, hops integer) on commit drop;
  create temp table _frontier (address text primary key) on commit drop;

  -- seeds
  insert into _visited (address, hops)
  select w.address, 0 from public.wallets w
   where w.chain = p_chain
     and case p_kind when 'mixer' then w.entity_type = 'mixer'
                     else w.is_sanctioned end;
  insert into _frontier select address from _visited;

  while h < p_max_hops loop
    h := h + 1;

    create temp table _next on commit drop as
      select distinct nb.address
        from _frontier f
        join public.transactions t
          on t.chain = p_chain
         and (t.from_address = f.address or t.to_address = f.address)
        cross join lateral (
          select case when t.from_address = f.address then t.to_address
                      else t.from_address end as address) nb
       where not exists (select 1 from _visited v where v.address = nb.address);

    select count(*) into more from _next;
    if more = 0 then drop table _next; exit; end if;

    insert into _visited (address, hops)
    select address, h from _next
    on conflict (address) do nothing;      -- first visit wins = shortest path

    truncate _frontier;
    insert into _frontier select address from _next;
    drop table _next;
  end loop;

  if p_kind = 'mixer' then
    update public.wallet_features f set mixer_hops = v.hops
      from _visited v join public.wallets w
        on w.chain = p_chain and w.address = v.address
     where f.wallet_id = w.id;
  else
    update public.wallet_features f set sanction_hops = v.hops
      from _visited v join public.wallets w
        on w.chain = p_chain and w.address = v.address
     where f.wallet_id = w.id;
  end if;
  get diagnostics touched = row_count;

  drop table _visited;
  drop table _frontier;
  return touched;
end $$;

-- ---------------------------------------------------------------------
-- 4. ROBUST ANOMALY SCORING (median / MAD z-score, outlier-resistant)
--    Classic z-scores break when the population already contains the
--    fraud you are hunting. Modified z = 0.6745*(x-median)/MAD.
-- ---------------------------------------------------------------------
create or replace function public.anomaly_zscores(p_chain chain_t)
returns table (
  wallet_id bigint, address text,
  z_velocity numeric, z_value numeric, z_fanout numeric,
  z_entropy numeric, z_structuring numeric, composite_z numeric
)
language sql stable security definer set search_path = public as $$
  with base as (
    select f.*, w.address
      from public.wallet_features f
      join public.wallets w on w.id = f.wallet_id
     where w.chain = p_chain
  ),
  stats as (
    select
      percentile_cont(0.5) within group (order by tx_velocity_7d)       as med_vel,
      percentile_cont(0.5) within group (order by avg_value_usd)        as med_val,
      percentile_cont(0.5) within group (order by fan_out)              as med_fo,
      percentile_cont(0.5) within group (order by counterparty_entropy) as med_ent,
      percentile_cont(0.5) within group (order by structuring_score)    as med_str
    from base
  ),
  -- MAD collapses to ~0 when most wallets share a feature value (very
  -- common early in ingestion). An unguarded divide then produces
  -- meaningless six-figure z-scores. Floor each MAD at 1% of the
  -- feature's own median, which keeps the scale meaningful.
  mad as (
    select
      greatest(percentile_cont(0.5) within group (order by abs(b.tx_velocity_7d - s.med_vel)),
               max(abs(s.med_vel)) * 0.01, 1e-3) as mad_vel,
      greatest(percentile_cont(0.5) within group (order by abs(b.avg_value_usd  - s.med_val)),
               max(abs(s.med_val)) * 0.01, 1e-3) as mad_val,
      greatest(percentile_cont(0.5) within group (order by abs(b.fan_out        - s.med_fo )),
               max(abs(s.med_fo))  * 0.01, 0.5)  as mad_fo,
      greatest(percentile_cont(0.5) within group (order by abs(b.counterparty_entropy - s.med_ent)),
               max(abs(s.med_ent)) * 0.01, 1e-2) as mad_ent,
      greatest(percentile_cont(0.5) within group (order by abs(b.structuring_score    - s.med_str)),
               0.02)                             as mad_str
    from base b cross join stats s
  )
  select b.wallet_id, b.address,
         round((0.6745*(b.tx_velocity_7d       - s.med_vel)/m.mad_vel)::numeric, 3),
         round((0.6745*(b.avg_value_usd        - s.med_val)/m.mad_val)::numeric, 3),
         round((0.6745*(b.fan_out              - s.med_fo )/m.mad_fo )::numeric, 3),
         round((0.6745*(b.counterparty_entropy - s.med_ent)/m.mad_ent)::numeric, 3),
         round((0.6745*(b.structuring_score    - s.med_str)/m.mad_str)::numeric, 3),
         -- each component winsorised at |z| = 12 so one wild feature
         -- cannot swamp the composite
         round((
           least(abs(0.6745*(b.tx_velocity_7d       - s.med_vel)/m.mad_vel), 12) * 0.20 +
           least(abs(0.6745*(b.avg_value_usd        - s.med_val)/m.mad_val), 12) * 0.20 +
           least(abs(0.6745*(b.fan_out              - s.med_fo )/m.mad_fo ), 12) * 0.25 +
           least(abs(0.6745*(b.counterparty_entropy - s.med_ent)/m.mad_ent), 12) * 0.15 +
           least(abs(0.6745*(b.structuring_score    - s.med_str)/m.mad_str), 12) * 0.20
         )::numeric, 3)
    from base b cross join stats s cross join mad m;
$$;

grant execute on function public.anomaly_zscores(chain_t) to authenticated;

-- ---------------------------------------------------------------------
-- 5. COMPOSITE RISK SCORE  (0–100, fully explainable)
--    Every point is attributable to a named factor -> defensible in
--    an investigation and auditable after the fact.
-- ---------------------------------------------------------------------
create or replace function public.score_wallets(p_chain chain_t)
returns integer
language plpgsql security definer set search_path = public as $$
declare n integer := 0;
begin
  with z as (select * from public.anomaly_zscores(p_chain)),
  scored as (
    select w.id as wallet_id,
      -- factor points
      (case when w.is_sanctioned then 45 else 0 end)                                   as p_sanction,
      (case f.sanction_hops when 1 then 25 when 2 then 12 when 3 then 5 else 0 end)    as p_sanction_prox,
      (case f.mixer_hops    when 0 then 30 when 1 then 20 when 2 then 10 else 0 end)   as p_mixer,
      least(15, coalesce(f.peel_chain_depth,0) * 2.5)                                  as p_peel,
      least(15, coalesce(z.composite_z,0) * 3.0)                                       as p_anomaly,
      least(10, coalesce(f.structuring_score,0) * 40)                                  as p_structuring,
      least(8,  coalesce(f.round_amount_ratio,0) * 12)                                 as p_round,
      (case when f.dormancy_days > 180 and f.tx_velocity_7d > 5 then 8 else 0 end)     as p_dormant_burst,
      (case when f.fan_in > 50 and f.fan_out <= 3 then 7 else 0 end)                   as p_collector,
      (case when f.fan_out > 50 and f.fan_in  <= 3 then 7 else 0 end)                  as p_distributor,
      -- carry only what the explanation needs (f.* would clash on wallet_id)
      f.sanction_hops, f.mixer_hops, f.peel_chain_depth, f.fan_in, f.fan_out,
      coalesce(z.composite_z, 0) as composite_z
      from public.wallets w
      join public.wallet_features f on f.wallet_id = w.id
      left join z on z.wallet_id = w.id
     where w.chain = p_chain
  ),
  final as (
    select wallet_id,
      least(100, p_sanction + p_sanction_prox + p_mixer + p_peel + p_anomaly
                 + p_structuring + p_round + p_dormant_burst + p_collector + p_distributor
      )::numeric(5,2) as score,
      jsonb_build_array(
        jsonb_build_object('factor','Direct sanctions match',   'points', p_sanction),
        jsonb_build_object('factor','Sanctions proximity',      'points', p_sanction_prox, 'hops', sanction_hops),
        jsonb_build_object('factor','Mixer exposure',           'points', p_mixer,         'hops', mixer_hops),
        jsonb_build_object('factor','Peel-chain depth',         'points', p_peel,          'depth', peel_chain_depth),
        jsonb_build_object('factor','Behavioural anomaly (MAD z)','points', p_anomaly,     'z', composite_z),
        jsonb_build_object('factor','Structuring pattern',      'points', p_structuring),
        jsonb_build_object('factor','Round-amount automation',  'points', p_round),
        jsonb_build_object('factor','Dormant-then-burst',       'points', p_dormant_burst),
        jsonb_build_object('factor','Fan-in collector',         'points', p_collector,     'fanIn', fan_in),
        jsonb_build_object('factor','Fan-out distributor',      'points', p_distributor,   'fanOut', fan_out)
      ) as contributions
    from scored
  )
  insert into public.risk_scores (wallet_id, score, contributions, model_version)
  select wallet_id, score,
         (select jsonb_agg(c) from jsonb_array_elements(contributions) c
           where (c->>'points')::numeric > 0),
         'v1.0.0'
    from final;

  get diagnostics n = row_count;
  return n;
end $$;

-- ---------------------------------------------------------------------
-- 6. RULE ENGINE -> ALERTS
-- ---------------------------------------------------------------------
create or replace function public.generate_alerts(p_chain chain_t)
returns integer
language plpgsql security definer set search_path = public as $$
declare n integer;
begin
  with latest as (
    select distinct on (wallet_id) wallet_id, score, band, contributions
      from public.risk_scores order by wallet_id, scored_at desc
  )
  insert into public.alerts (wallet_id, rule_code, title, detail, severity, evidence_ref)
  select w.id,
         case
           when w.is_sanctioned                    then 'SANCTION_DIRECT'
           when f.sanction_hops = 1                then 'SANCTION_1HOP'
           when f.mixer_hops = 0                   then 'MIXER_DIRECT'
           when f.peel_chain_depth >= 5            then 'PEEL_CHAIN'
           when f.structuring_score > 0.3          then 'STRUCTURING'
           when f.fan_in > 50 and f.fan_out <= 3   then 'FUNNEL_ACCOUNT'
           else 'HIGH_RISK_COMPOSITE'
         end,
         case
           when w.is_sanctioned         then 'Sanctioned address active'
           when f.sanction_hops = 1     then 'One hop from a sanctioned address'
           when f.mixer_hops = 0        then 'Direct mixer interaction'
           when f.peel_chain_depth >= 5 then format('Peel chain of depth %s detected', f.peel_chain_depth)
           when f.structuring_score>0.3 then 'Sub-threshold structuring pattern'
           else 'Composite risk exceeded threshold'
         end,
         format('Wallet %s scored %s (%s band).', left(w.address,16)||'…', l.score, l.band),
         least(100, greatest(50, l.score))::smallint,
         jsonb_build_object('walletId', w.id, 'address', w.address,
                            'contributions', l.contributions, 'features', to_jsonb(f))
    from latest l
    join public.wallets w on w.id = l.wallet_id
    join public.wallet_features f on f.wallet_id = w.id
   where w.chain = p_chain
     and l.score >= 60
     and not exists (
       select 1 from public.alerts a
        where a.wallet_id = w.id
          and a.status in ('open','triaged')
          and a.created_at > now() - interval '24 hours');

  get diagnostics n = row_count;
  return n;
end $$;

-- ---------------------------------------------------------------------
-- 7. ONE-SHOT PIPELINE (call after every ingest batch)
-- ---------------------------------------------------------------------
create or replace function public.run_detection_pipeline(p_chain chain_t)
returns jsonb
language plpgsql security definer set search_path = public as $$
declare f int; s int; a int; t0 timestamptz := clock_timestamp();
begin
  -- flag sanctioned wallets from threat intel
  update public.wallets w set is_sanctioned = true, entity_type = 'sanctioned'
    from public.threat_intel ti
   where ti.chain = w.chain and lower(ti.address) = lower(w.address)
     and w.is_sanctioned = false;

  f := public.compute_wallet_features(p_chain);
  s := public.score_wallets(p_chain);
  a := public.generate_alerts(p_chain);

  return jsonb_build_object(
    'chain', p_chain, 'featuresComputed', f, 'walletsScored', s,
    'alertsRaised', a, 'ms', round(extract(milliseconds from clock_timestamp()-t0)));
end $$;

grant execute on function public.run_detection_pipeline(chain_t) to authenticated;

-- ---------------------------------------------------------------------
-- 8. DASHBOARD VIEWS (what the frontend subscribes to)
-- ---------------------------------------------------------------------
create or replace view public.v_wallet_risk as
  select w.id, w.chain, w.address, w.entity_type, w.vasp_name, w.is_sanctioned,
         w.balance_usd, w.tx_count, w.last_seen,
         r.score, r.band, r.contributions, r.scored_at,
         f.mixer_hops, f.sanction_hops, f.peel_chain_depth, f.fan_in, f.fan_out
    from public.wallets w
    left join lateral (select * from public.risk_scores rs
                        where rs.wallet_id = w.id
                        order by rs.scored_at desc limit 1) r on true
    left join public.wallet_features f on f.wallet_id = w.id;

create or replace view public.v_live_metrics as
  select
    (select count(*) from public.wallets)                                   as wallets_tracked,
    (select count(*) from public.transactions)                              as transactions_indexed,
    (select count(*) from public.transactions
      where block_time > now() - interval '1 hour')                         as tx_last_hour,
    (select count(*) from public.alerts where status = 'open')              as open_alerts,
    (select count(*) from public.alerts
      where status='open' and severity >= 80)                               as critical_alerts,
    (select count(*) from public.wallets where is_sanctioned)               as sanctioned_hits,
    (select count(*) from public.clusters)                                  as clusters,
    (select count(distinct vasp_name) from public.clusters
      where vasp_name is not null)                                          as vasps_attributed,
    (select coalesce(sum(value_usd),0) from public.transactions
      where block_time > now() - interval '24 hours')                       as volume_24h_usd,
    (select max(ingested_at) from public.transactions)                      as last_ingest_at;

-- Expose live tables to Supabase Realtime so the UI updates itself
do $$ begin
  alter publication supabase_realtime add table public.transactions;
exception when duplicate_object then null; end $$;
do $$ begin
  alter publication supabase_realtime add table public.alerts;
exception when duplicate_object then null; end $$;
do $$ begin
  alter publication supabase_realtime add table public.risk_scores;
exception when duplicate_object then null; end $$;

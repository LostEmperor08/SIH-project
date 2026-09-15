// =====================================================================
// client/skvClient.ts — drop this into your frontend.
// Works with React, Vue or plain JS. Nothing here is demo data:
// every value comes from the live ingest pipeline.
// =====================================================================
import { createClient, RealtimeChannel } from "@supabase/supabase-js";

export const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY,
  { realtime: { params: { eventsPerSecond: 10 } } },
);

// ---------------------------------------------------------------------
// Reads (RLS-enforced — the JWT decides what comes back)
// ---------------------------------------------------------------------
export const getDashboard = async () => {
  const { data, error } = await supabase.rpc("api_dashboard");
  if (error) throw error;
  return data;
};

export const investigate = async (address: string, chain: "btc" | "eth" = "btc", hops = 2) => {
  const { data, error } = await supabase.rpc("api_investigate", {
    p_chain: chain, p_address: address, p_hops: hops,
  });
  if (error) throw error;
  return data;   // { wallet, graph:{nodes,edges}, cluster, sanctionPaths, alerts }
};

export const traceFunds = async (address: string, chain: "btc" | "eth" = "btc", hops = 4) => {
  const { data, error } = await supabase.rpc("trace_funds", {
    p_chain: chain, p_address: address, p_max_hops: hops, p_direction: "forward",
  });
  if (error) throw error;
  return data;
};

export const verifyEvidence = async (caseId: number) => {
  const { data, error } = await supabase.rpc("verify_evidence_chain", { p_case_id: caseId });
  if (error) throw error;
  return data;   // [{ seq, content_ok, link_ok, chain_hash, verdict }]
};

export const verifyAuditChain = async () => {
  const { data, error } = await supabase.rpc("verify_audit_chain");
  if (error) throw error;
  return data?.[0];
};

export const sealEvidence = async (
  caseId: number, kind: string, payload: unknown, description?: string,
) => {
  const { data, error } = await supabase.rpc("add_evidence", {
    p_case_id: caseId, p_kind: kind, p_payload: payload, p_description: description ?? null,
  });
  if (error) throw error;
  return data;
};

// ---------------------------------------------------------------------
// Live triggers (edge functions) — pull fresh chain data on demand
// ---------------------------------------------------------------------
export const ingestNow = async (chain: "btc" | "eth", blocks = 1, address?: string) => {
  const { data, error } = await supabase.functions.invoke("ingest-chain", {
    body: { chain, blocks, address },
  });
  if (error) throw error;
  return data;
};

export const runClustering = async (chain: "btc" | "eth" = "btc") => {
  const { data, error } = await supabase.functions.invoke("cluster-attribute", { body: { chain } });
  if (error) throw error;
  return data;
};

// ---------------------------------------------------------------------
// REALTIME — this is what makes the page move on its own.
// Every row the ingest function writes is pushed here over a websocket.
// ---------------------------------------------------------------------
export function subscribeLive(handlers: {
  onTransaction?: (tx: any) => void;
  onAlert?: (alert: any) => void;
  onScore?: (score: any) => void;
}): RealtimeChannel {
  return supabase
    .channel("skv-live")
    .on("postgres_changes",
        { event: "INSERT", schema: "public", table: "transactions" },
        (p) => handlers.onTransaction?.(p.new))
    .on("postgres_changes",
        { event: "*", schema: "public", table: "alerts" },
        (p) => handlers.onAlert?.(p.new))
    .on("postgres_changes",
        { event: "INSERT", schema: "public", table: "risk_scores" },
        (p) => handlers.onScore?.(p.new))
    .subscribe();
}

// ---------------------------------------------------------------------
// React hook — live dashboard with zero polling
// ---------------------------------------------------------------------
/*
import { useEffect, useRef, useState } from "react";

export function useLiveDashboard(autoIngestMs = 0) {
  const [data, setData]   = useState<any>(null);
  const [feed, setFeed]   = useState<any[]>([]);
  const [alerts, setAlerts] = useState<any[]>([]);
  const chan = useRef<RealtimeChannel>();

  useEffect(() => {
    getDashboard().then(setData).catch(console.error);

    chan.current = subscribeLive({
      onTransaction: (tx) => setFeed((f) => [tx, ...f].slice(0, 100)),
      onAlert:       (a)  => { setAlerts((x) => [a, ...x].slice(0, 50));
                               getDashboard().then(setData); },
      onScore:       ()   => getDashboard().then(setData),
    });

    const t = autoIngestMs
      ? setInterval(() => ingestNow("eth", 1).catch(console.error), autoIngestMs)
      : undefined;

    return () => { chan.current?.unsubscribe(); if (t) clearInterval(t); };
  }, [autoIngestMs]);

  return { data, feed, alerts, refresh: () => getDashboard().then(setData) };
}
*/

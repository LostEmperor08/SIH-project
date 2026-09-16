// =====================================================================
// Evidence sealing — hash-chained, through the RPC.
//
// Migration 08 revoked direct INSERT on evidence_ledger and made
// add_evidence_link() the only way in, because that function computes the
// SHA-256 chain: each record's hash includes the previous record's hash.
// A direct insert would store a row with no chain_hash, which is exactly
// the hole the chain exists to close — delete row 3 and rows 1,2,4,5 still
// verify individually, so a removal is invisible.
//
// So: never .insert() into evidence_ledger. Always go through the RPC.
// =====================================================================
import { isSupabaseConfigured, supabase } from "./supabase.js";
import { pathEdges } from "./moneyPath.js";

/**
 * Seal one traced hop as a chain-linked evidence record.
 * Returns the sealed row, or throws with a readable reason.
 */
export async function sealEvidence(item, caseRef) {
  if (!isSupabaseConfigured) {
    throw new Error("Supabase is not configured — evidence cannot be sealed.");
  }
  const { data, error } = await supabase.rpc("add_evidence_link", {
    p_id: item.id ?? `EV-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    p_case_ref: caseRef,
    p_chain: item.chain ?? "unknown",
    p_tx_hash: item.tx_hash ?? "",
    p_from: item.from_addr ?? "",
    p_to: item.to_addr ?? "",
    p_value_usdt: Number(item.value_usdt ?? 0),
    p_risk_score: Math.round(Number(item.risk_score ?? 0)),
    p_hop: item.hop ?? 1,
    p_observed_at: item.observed_at ?? new Date().toISOString(),
  });
  if (error) throw new Error(`Evidence seal failed: ${error.message}`);
  return data;
}

/**
 * Seal the traced money path as an evidence chain.
 *
 * Runs sequentially on purpose. Each record's hash depends on the previous
 * one, so sealing in parallel would race and produce a chain that cannot
 * verify.
 */
export { pathEdges };

export async function sealTraceEvidence(graph, caseRef, targetAddress) {
  const ordered = pathEdges(graph, targetAddress).slice(0, 60);
  if (!ordered.length) {
    return { sealed: 0, caseRef, considered: graph?.edges?.length ?? 0, errors: [] };
  }

  const riskOf = new Map((graph?.nodes ?? []).map((n) => [n.id, n.risk ?? 0]));

  let sealed = 0;
  const errors = [];
  for (const e of ordered) {
    try {
      await sealEvidence({
        hop: e.hop,
        chain: e.chain ?? graph.nodes?.[0]?.chain ?? "unknown",
        tx_hash: e.tx_hash,
        from_addr: e.source,
        to_addr: e.target,
        value_usdt: e.amount,
        risk_score: Math.max(riskOf.get(e.source) ?? 0, riskOf.get(e.target) ?? 0),
        observed_at: e.timestamp ?? new Date().toISOString(),
      }, caseRef);
      sealed++;
    } catch (err) {
      errors.push(`hop ${e.hop}: ${err.message}`);
      // One bad row must not abandon the rest of the chain.
      if (errors.length > 5) break;
    }
  }
  return { sealed, caseRef, considered: graph?.edges?.length ?? 0,
           onPath: ordered.length, errors };
}

/** Prove the chain for a case: per item, INTACT or TAMPERED. */
export async function verifyEvidenceChain(caseRef) {
  if (!isSupabaseConfigured) throw new Error("Supabase is not configured.");
  const { data, error } = await supabase.rpc("verify_evidence_chain", { p_case_ref: caseRef });
  if (error) throw new Error(`Verification failed: ${error.message}`);
  return data ?? [];
}

/** Stable case reference from an FIR number, so re-tracing appends to one chain. */
export function caseRefFor(fir, address) {
  if (fir && String(fir).trim()) return String(fir).trim();
  return `TRACE-${String(address ?? "").slice(0, 10)}-${new Date().toISOString().slice(0, 10)}`;
}

// =====================================================================
// Backend <-> UI adapter.
//
// The UI speaks in human labels ("Polygon PoS (USDT)") and a flat
// {address, chain} request. The backend speaks chain codes and a
// {targets:[...]} contract. Neither should change to suit the other, so the
// translation lives here, in one place.
// =====================================================================

// UI label -> backend chain code. Keys are lowercased before lookup, and
// substring matching covers label variations without another mapping table.
const CHAIN_CODE = {
  polygon: "polygon", matic: "polygon",
  ethereum: "eth", eth: "eth", erc: "eth",
  tron: "tron", trc: "tron",
  bitcoin: "btc", btc: "btc",
  bsc: "bsc", binance: "bsc", bnb: "bsc",
};

export function toChainCode(label) {
  const s = String(label ?? "").trim().toLowerCase();
  if (!s) return null;
  if (["btc", "eth", "polygon", "tron", "bsc"].includes(s)) return s;
  for (const [needle, code] of Object.entries(CHAIN_CODE)) {
    if (s.includes(needle)) return code;
  }
  return null;
}

// Backend node types -> the four the graph component renders.
function nodeType(d) {
  if (d.isTarget) return "SUSPECT";
  if (d.entity === "exchange" || d.hopsToExchange === 0) return "VASP";
  if (d.entity === "mixer" || d.entity === "bridge") return "CONTRACT";
  return "INTERMEDIARY";
}

export function normalizeBackendTrace(payload) {
  const g = payload?.graph ?? {};
  const rawNodes = Array.isArray(g.nodes) ? g.nodes : [];
  const rawEdges = Array.isArray(g.edges) ? g.edges : [];

  const nodes = rawNodes.map((n) => {
    const d = n.data ?? {};
    return {
      id: d.address ?? n.id,
      label: d.label ?? d.address ?? n.id,
      type: nodeType(d),
      balance: Number(d.inUsd ?? 0) - Number(d.outUsd ?? 0),
      firstSeen: d.firstSeen ?? null,
      risk: d.riskScore ?? 0,
      riskBand: d.riskBand ?? null,
      txCount: d.degree ?? 0,
      chain: d.chain,
      sanctioned: !!d.sanctioned,
      hop: d.hop,
      // carried through so the detail drawer can show WHY a wallet scored
      factors: d.factors ?? [],
      narrative: d.narrative ?? null,
      recommendedActions: d.recommendedActions ?? [],
      hopsToExchange: d.hopsToExchange ?? null,
      hopsToSanctioned: d.hopsToSanctioned ?? null,
      explorerUrl: d.explorerUrl ?? null,
      inUsd: Number(d.inUsd ?? 0),
      outUsd: Number(d.outUsd ?? 0),
    };
  });

  // node ids are backend "chain:address" keys; the UI keys on address alone
  const idToAddress = new Map(rawNodes.map((n) => [n.id, n.data?.address ?? n.id]));

  const edges = rawEdges.map((e) => {
    const d = e.data ?? {};
    return {
      source: idToAddress.get(e.source) ?? e.source,
      target: idToAddress.get(e.target) ?? e.target,
      amount: Number(d.valueUsd ?? 0),
      token: "USD",
      tx_hash: (d.txHashes && d.txHashes[0]) || "",
      txHashes: d.txHashes ?? [],
      explorerUrls: d.explorerUrls ?? [],
      timestamp: d.lastSeen ?? d.firstSeen ?? null,
      txCount: d.txCount ?? 1,
      label: e.label,
      animated: !!e.animated,
    };
  });

  // The VASP endpoint is the point of the whole trace: it is who a Section
  // 91 notice gets served on. Prefer a wallet the backend put 0 hops from an
  // exchange; fall back to the highest-risk node rather than inventing one.
  const vasp =
    nodes.find((n) => n.type === "VASP") ??
    nodes.filter((n) => n.type !== "SUSPECT").sort((a, b) => (b.risk ?? 0) - (a.risk ?? 0))[0] ??
    null;

  const depositEdge = vasp
    ? edges.filter((e) => e.target === vasp.id).sort((a, b) => b.amount - a.amount)[0]
    : null;

  const attribution = vasp
    ? {
        // No invented exchange name. If the backend could not attribute one,
        // the UI says so — naming the wrong VASP sends the freeze request to
        // the wrong place.
        exchange_name: vasp.label && vasp.label !== vasp.id ? vasp.label : "Unattributed endpoint",
        deposit_address: vasp.id,
        hot_wallet_address: vasp.id,
        tx_hash: depositEdge?.tx_hash ?? "",
        deposit_timestamp: depositEdge?.timestamp ?? "",
        confidence: Math.min(1, Math.max(0, Number(vasp.risk ?? 0) / 100)),
        hops: vasp.hop ?? payload?.hops ?? 0,
        time_to_attribution_ms: payload?.elapsedMs ?? 0,
      }
    : null;

  return {
    nodes,
    edges,
    attribution,
    transactions: payload?.transactions ?? [],
    stats: payload?.stats ?? null,
    prices: payload?.prices ?? null,
    providerErrors: payload?.providerErrors ?? [],
  };
}

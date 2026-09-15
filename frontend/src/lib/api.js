import { isSupabaseConfigured, supabase } from "./supabase.js";

// Set VITE_API_URL=http://localhost:8000 in .env to connect your FastAPI backend.
const API = import.meta.env.VITE_API_URL;

const RPC_CHAIN_BY_LABEL = {
  tron: "TRON",
  "tron (trc-20)": "TRON",
  polygon: "POLYGON",
  "polygon pos": "POLYGON",
  "polygon pos (usdt)": "POLYGON",
  ethereum: "ETHEREUM",
  "ethereum (erc-20)": "ETHEREUM",
  bitcoin: "BITCOIN",
};

function normalizeRpcGraph(payload) {
  const nodes = Array.isArray(payload?.nodes) ? payload.nodes : [];
  const edges = Array.isArray(payload?.edges) ? payload.edges : [];
  const vaspNode = nodes.find((node) => node.entity === "VASP" || node.sanctioned);
  const depositEdge = edges.find((edge) => edge.target === vaspNode?.id) ?? edges.at(-1);

  return {
    nodes: nodes.map((node) => ({
      id: node.id,
      label: node.label ?? node.id,
      type: node.isSeed ? "SUSPECT" : node.entity === "VASP" ? "VASP" : node.entity === "CONTRACT" ? "CONTRACT" : "INTERMEDIARY",
      balance: node.balanceUsd,
      firstSeen: node.firstSeen,
      risk: node.risk,
      txCount: node.txCount,
    })),
    edges: edges.map((edge) => ({
      source: edge.source,
      target: edge.target,
      amount: Number(edge.valueUsd ?? 0),
      token: "USD",
      tx_hash: edge.txHash,
      timestamp: edge.time,
    })),
    attribution: vaspNode
      ? {
          exchange_name: vaspNode.label ?? "Identified VASP",
          deposit_address: depositEdge?.target ?? vaspNode.id,
          hot_wallet_address: vaspNode.id,
          tx_hash: depositEdge?.txHash ?? "",
          deposit_timestamp: depositEdge?.time ?? "",
          confidence: Math.min(1, Math.max(0, Number(vaspNode.risk ?? 0) / 100)),
          hops: edges.length,
          time_to_attribution_ms: 0,
        }
      : null,
  };
}

async function traceWithSupabase(request) {
  const chain = RPC_CHAIN_BY_LABEL[String(request.chain ?? "").trim().toLowerCase()];
  if (!chain) {
    throw new Error(`Unsupported chain for Supabase detection engine: ${request.chain}`);
  }

  const { data, error } = await supabase.rpc("graph_neighbourhood", {
    p_chain: chain,
    p_address: request.address,
    p_hops: 4,
    p_limit: 300,
  });
  if (error) throw error;
  return normalizeRpcGraph(data);
}

async function authHeaders() {
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ? { Authorization: `Bearer ${data.session.access_token}` } : {};
}

export async function traceFunds(req) {
  if (API) {
    const headers = await authHeaders();
    const res = await fetch(`${API}/trace`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers },
      body: JSON.stringify(req),
    });
    if (!res.ok) throw new Error(`Trace failed: ${res.status}`);
    return res.json();
  }

  if (isSupabaseConfigured) {
    try {
      const graph = await traceWithSupabase(req);
      if (graph.nodes.length > 0) return graph;
    } catch (error) {
      console.warn("Supabase detection engine unavailable; trying backend trace", error);
    }
  }

  throw new Error("No live trace provider is configured. Start the backend or deploy the Supabase detection engine.");
}

// Pre-filled Section 94 BNSS / Section 91 CrPC notice body
export function buildNotice(graph, firNo) {
  const a = graph.attribution;
  if (!a) return "No VASP attribution available yet.";
  return [
    `To: ${a.exchange_name} Compliance / Legal Cell`,
    ``,
    `Subject: Request for KYC details, IP logs and account freeze — Case FIR No. ${firNo}`,
    ``,
    `Sir/Madam,`,
    `Under Section 94 of the Bharatiya Nagarik Suraksha Sanhita, 2023 (formerly Section 91 CrPC),`,
    `you are requested to provide the KYC identity, login IP logs, device fingerprints and to`,
    `provisionally freeze the account linked to the following deposit address:`,
    ``,
    `  Receiving Address : ${a.deposit_address}`,
    `  Transaction Hash  : ${a.tx_hash}`,
    `  Deposit Timestamp : ${a.deposit_timestamp}`,
    `  Amount / Token    : traced via chain analytics (see attached dossier)`,
    ``,
    `This address has been attributed to ${a.exchange_name} with ${(a.confidence * 100).toFixed(0)}% confidence`,
    `via sweep-pattern analysis into verified hot wallet ${a.hot_wallet_address}.`,
    ``,
    `Kindly respond within 24 hours to the Investigating Officer.`,
  ].join("\n");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
  }[character]));
}

export function buildDossier(graph, firNo) {
  const attribution = graph?.attribution;
  if (!attribution) return "";
  const rows = (graph.edges ?? []).map((edge) => `<tr><td>${escapeHtml(edge.tx_hash)}</td><td>${escapeHtml(edge.source)}</td><td>${escapeHtml(edge.target)}</td><td>${escapeHtml(`${edge.amount} ${edge.token}`)}</td><td>${escapeHtml(new Date(edge.timestamp).toISOString())}</td></tr>`).join("");
  const issued = new Date().toISOString();
  return `<!doctype html><html><head><meta charset="utf-8"><title>Forensic Attribution Dossier · ${escapeHtml(firNo)}</title><style>
  @page{size:A4;margin:18mm}body{font-family:Arial,Helvetica,sans-serif;color:#17221c;margin:0;line-height:1.5}header{border-bottom:4px solid #b99b3e;padding-bottom:18px;margin-bottom:26px}h1{font-size:25px;letter-spacing:.08em;margin:0 0 4px;text-transform:uppercase}h2{font-size:15px;border-bottom:1px solid #c7d2c8;padding-bottom:7px;margin-top:28px;color:#254b38}p{font-size:11px}.mast{display:flex;justify-content:space-between;align-items:flex-start}.seal{border:2px solid #b99b3e;padding:10px 13px;color:#765e1d;font-weight:bold;font-size:10px;text-align:center}.muted{color:#64746a;font-size:10px}.meta{display:grid;grid-template-columns:1fr 1fr;border:1px solid #ccd7ce;background:#f4f7f3}.meta div{padding:10px;border-bottom:1px solid #dce5de}.meta b{display:block;font-size:9px;color:#627267;text-transform:uppercase;letter-spacing:.08em}.meta span{font-size:11px}table{border-collapse:collapse;width:100%;font-size:9px}th{background:#0c2b1d;color:#fff;text-align:left;padding:8px}td{border:1px solid #d6dfd8;padding:7px;vertical-align:top}.finding{border-left:4px solid #b99b3e;background:#f7f4e8;padding:12px;font-size:11px}.sign{margin-top:46px;border-top:1px solid #829287;width:260px;padding-top:8px;font-size:10px}.footer{margin-top:35px;border-top:1px solid #ccd7ce;padding-top:10px;color:#64746a;font-size:9px}</style></head><body>
  <header><div class="mast"><div><h1>Forensic Attribution Dossier</h1><div class="muted">CHAKRAVYUH I4C · National Crypto Fraud Attribution System</div></div><div class="seal">OFFICIAL<br>INVESTIGATION COPY</div></div></header>
  <p><b>Document purpose:</b> This dossier records the machine-assisted attribution findings for investigative review. It is an evidence summary, not a substitute for the underlying chain records or a signed statutory notice.</p>
  <div class="meta"><div><b>Case / FIR reference</b><span>${escapeHtml(firNo)}</span></div><div><b>Issued (UTC)</b><span>${escapeHtml(issued)}</span></div><div><b>Attributed VASP</b><span>${escapeHtml(attribution.exchange_name)}</span></div><div><b>Confidence</b><span>${(attribution.confidence * 100).toFixed(0)}%</span></div><div><b>Receiving address</b><span>${escapeHtml(attribution.deposit_address)}</span></div><div><b>Attribution transaction</b><span>${escapeHtml(attribution.tx_hash)}</span></div></div>
  <h2>Executive finding</h2><div class="finding">The reported wallet flow resolves to <b>${escapeHtml(attribution.exchange_name)}</b> through ${escapeHtml(attribution.hops)} observed hop(s), with an attribution confidence of ${(attribution.confidence * 100).toFixed(0)}%. The receiving endpoint should be reviewed for preservation, KYC production, and appropriate freeze action under the investigating agency's authority.</div>
  <h2>Verified transaction chain</h2><table><thead><tr><th>Transaction hash</th><th>Source</th><th>Target</th><th>Value</th><th>Timestamp (UTC)</th></tr></thead><tbody>${rows || "<tr><td colspan='5'>No transaction records available.</td></tr>"}</tbody></table>
  <h2>Method and limitations</h2><p>Attribution is generated from graph traversal, exchange-cluster matching, and sweep-pattern analysis in the connected analytics environment. Investigators must independently validate source records, obtain provider disclosures, and preserve original evidence before relying on this document in proceedings.</p>
  <div class="sign">Investigating Officer signature / seal<br><br>Inspector A. Sharma · I4C Operations Division</div>
  <div class="footer">CONFIDENTIAL · Law-enforcement use only · Generated by Chakravyuh frontend evidence workspace</div>
  </body></html>`;
}

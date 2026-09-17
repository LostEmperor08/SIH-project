import { isSupabaseConfigured, supabase } from "./supabase.js";
import { normalizeBackendTrace, toChainCode } from "./apiAdapter.js";

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
          confidence: vaspNode.vaspAttribution?.confidence ?? 0.85,
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
    const chain = toChainCode(req.chain);
    if (!chain) {
      throw new Error(`Unsupported chain: "${req.chain}". Supported: Bitcoin, Ethereum, Polygon, Tron, BSC.`);
    }

    const headers = await authHeaders();
    if (!headers.Authorization) {
      throw new Error("Not signed in. Log in before running a trace.");
    }

    // The backend contract is {targets:[{chain,address}], hops}. The UI
    // speaks {address, chain}; translating here keeps both unchanged.
    const res = await fetch(`${API}/trace`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers },
      body: JSON.stringify({
        targets: [{ chain, address: String(req.address ?? "").trim() }],
        hops: req.hops ?? 2,
        cap_per_address: req.cap ?? 50,
        score: true,
        persist: true,
      }),
    });

    if (!res.ok) {
      // Surface the real reason instead of a bare status code — a 422 that
      // says "not a valid polygon address" is actionable; "Trace failed:
      // 422" costs an hour.
      let detail = "";
      try {
        const body = await res.json();
        if (res.status === 422 && Array.isArray(body.detail)) {
          detail = body.detail.map((d) => `${d.field}: ${d.message}`).join("; ");
        } else if (res.status === 404 && body.detail?.error) {
          detail = `${body.detail.error}. ${body.detail.hint ?? ""}`;
        } else {
          detail = body.detail ?? body.error ?? JSON.stringify(body).slice(0, 200);
        }
      } catch {
        detail = await res.text().catch(() => "");
      }
      throw new Error(`Trace failed (${res.status})${detail ? ": " + detail : ""}`);
    }

    return normalizeBackendTrace(await res.json());
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

// =====================================================================
// Batch 5: Real-Time Alerts & Monitored Wallets API
// =====================================================================
export async function getAlerts(filters = {}) {
  if (!API) return [];
  const headers = await authHeaders();
  const params = new URLSearchParams();
  if (filters.status && filters.status !== "all") params.append("status", filters.status.toUpperCase());
  if (filters.severity) params.append("severity", filters.severity);
  if (filters.chain) params.append("chain", filters.chain);
  params.append("limit", filters.limit || "100");

  const res = await fetch(`${API}/alerts?${params.toString()}`, { headers });
  if (!res.ok) throw new Error(`Failed to fetch alerts (${res.status})`);
  return await res.json();
}

export async function acknowledgeAlert(alertId) {
  if (!API) return null;
  const headers = await authHeaders();
  const res = await fetch(`${API}/alerts/${alertId}/acknowledge`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
  });
  if (!res.ok) throw new Error(`Failed to acknowledge alert (${res.status})`);
  return await res.json();
}

export async function resolveAlert(alertId) {
  if (!API) return null;
  const headers = await authHeaders();
  const res = await fetch(`${API}/alerts/${alertId}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
  });
  if (!res.ok) throw new Error(`Failed to resolve alert (${res.status})`);
  return await res.json();
}

export async function dismissAlert(alertId) {
  if (!API) return null;
  const headers = await authHeaders();
  const res = await fetch(`${API}/alerts/${alertId}/dismiss`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
  });
  if (!res.ok) throw new Error(`Failed to dismiss alert (${res.status})`);
  return await res.json();
}

export async function getMonitoredWallets() {
  if (!API) return [];
  const headers = await authHeaders();
  const res = await fetch(`${API}/monitored-wallets`, { headers });
  if (!res.ok) throw new Error(`Failed to fetch monitored wallets (${res.status})`);
  return await res.json();
}

export async function createMonitoredWallet(data) {
  if (!API) return null;
  const headers = await authHeaders();
  const res = await fetch(`${API}/monitored-wallets`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Failed to add monitored wallet (${res.status})`);
  return await res.json();
}

export async function deleteMonitoredWallet(id) {
  if (!API) return false;
  const headers = await authHeaders();
  const res = await fetch(`${API}/monitored-wallets/${id}`, {
    method: "DELETE",
    headers,
  });
  return res.ok;
}

export function connectAlertsWebSocket(onAlert, onError) {
  if (!API) return null;
  const wsUrl = API.replace(/^http/, "ws") + "/alerts/ws";
  let ws = null;
  try {
    ws = new WebSocket(wsUrl);
    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.event === "NEW_ALERT" && payload.alert) {
          onAlert?.(payload.alert);
        }
      } catch (err) {
        console.warn("WebSocket message parse error:", err);
      }
    };
    ws.onerror = (err) => {
      console.warn("Alerts WebSocket connection error:", err);
      onError?.(err);
    };
  } catch (err) {
    console.warn("WebSocket init error:", err);
  }
  return ws;
}

// =====================================================================
// Batch 6: Case Workspace API Helpers
// =====================================================================
export async function getCases(filters = {}) {
  if (!API) return [];
  const headers = await authHeaders();
  const params = new URLSearchParams();
  if (filters.status) params.append("status", filters.status);
  if (filters.search) params.append("search", filters.search);
  const res = await fetch(`${API}/cases?${params.toString()}`, { headers });
  if (!res.ok) throw new Error(`Failed to fetch cases (${res.status})`);
  return await res.json();
}

export async function getCase(caseId) {
  if (!API) return null;
  const headers = await authHeaders();
  const res = await fetch(`${API}/cases/${encodeURIComponent(caseId)}`, { headers });
  if (!res.ok) throw new Error(`Failed to fetch case details (${res.status})`);
  return await res.json();
}

export async function createCase(data) {
  if (!API) return null;
  const headers = await authHeaders();
  const res = await fetch(`${API}/cases`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Failed to create case (${res.status})`);
  return await res.json();
}

export async function updateCaseStatus(caseId, status, note) {
  if (!API) return null;
  const headers = await authHeaders();
  const res = await fetch(`${API}/cases/${encodeURIComponent(caseId)}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify({ status, note }),
  });
  if (!res.ok) throw new Error(`Failed to update case status (${res.status})`);
  return await res.json();
}

export async function getCaseSummary(caseId) {
  if (!API) return null;
  const headers = await authHeaders();
  const res = await fetch(`${API}/cases/${encodeURIComponent(caseId)}/summary`, { headers });
  if (!res.ok) throw new Error(`Failed to fetch case summary (${res.status})`);
  return await res.json();
}

export async function getCaseWallets(caseId) {
  if (!API) return [];
  const headers = await authHeaders();
  const res = await fetch(`${API}/cases/${encodeURIComponent(caseId)}/wallets`, { headers });
  if (!res.ok) throw new Error(`Failed to fetch case wallets (${res.status})`);
  return await res.json();
}

export async function getCaseTransactions(caseId) {
  if (!API) return [];
  const headers = await authHeaders();
  const res = await fetch(`${API}/cases/${encodeURIComponent(caseId)}/transactions`, { headers });
  if (!res.ok) throw new Error(`Failed to fetch case transactions (${res.status})`);
  return await res.json();
}

export async function getCaseExchanges(caseId) {
  if (!API) return [];
  const headers = await authHeaders();
  const res = await fetch(`${API}/cases/${encodeURIComponent(caseId)}/exchanges`, { headers });
  if (!res.ok) throw new Error(`Failed to fetch case exchanges (${res.status})`);
  return await res.json();
}

export async function getCaseCrossChain(caseId) {
  if (!API) return [];
  const headers = await authHeaders();
  const res = await fetch(`${API}/cases/${encodeURIComponent(caseId)}/cross-chain`, { headers });
  if (!res.ok) throw new Error(`Failed to fetch case cross-chain transfers (${res.status})`);
  return await res.json();
}

export async function getCaseRecommendations(caseId) {
  if (!API) return [];
  const headers = await authHeaders();
  const res = await fetch(`${API}/cases/${encodeURIComponent(caseId)}/recommendations`, { headers });
  if (!res.ok) throw new Error(`Failed to fetch case recommendations (${res.status})`);
  return await res.json();
}

export async function getCaseTimeline(caseId) {
  if (!API) return [];
  const headers = await authHeaders();
  const res = await fetch(`${API}/cases/${encodeURIComponent(caseId)}/timeline`, { headers });
  if (!res.ok) throw new Error(`Failed to fetch case timeline (${res.status})`);
  return await res.json();
}

export async function getCaseNotes(caseId) {
  if (!API) return [];
  const headers = await authHeaders();
  const res = await fetch(`${API}/cases/${encodeURIComponent(caseId)}/notes`, { headers });
  if (!res.ok) throw new Error(`Failed to fetch case notes (${res.status})`);
  return await res.json();
}

export async function addCaseNote(caseId, text, isPinned = false) {
  if (!API) return null;
  const headers = await authHeaders();
  const res = await fetch(`${API}/cases/${encodeURIComponent(caseId)}/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify({ text, is_pinned: isPinned }),
  });
  if (!res.ok) throw new Error(`Failed to add case note (${res.status})`);
  return await res.json();
}

export async function getCaseTasks(caseId) {
  if (!API) return [];
  const headers = await authHeaders();
  const res = await fetch(`${API}/cases/${encodeURIComponent(caseId)}/tasks`, { headers });
  if (!res.ok) throw new Error(`Failed to fetch case tasks (${res.status})`);
  return await res.json();
}

export async function createCaseTask(caseId, data) {
  if (!API) return null;
  const headers = await authHeaders();
  const res = await fetch(`${API}/cases/${encodeURIComponent(caseId)}/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Failed to create case task (${res.status})`);
  return await res.json();
}

// =====================================================================
// Batch 7: Evidence Provenance, Reports & Government Integrations API Helpers
// =====================================================================
export async function getCaseEvidenceRecords(caseId) {
  if (!API) return [];
  const headers = await authHeaders();
  const res = await fetch(`${API}/evidence/case/${encodeURIComponent(caseId)}`, { headers });
  if (!res.ok) throw new Error(`Failed to fetch evidence records (${res.status})`);
  return await res.json();
}

export async function verifyEvidenceChainApi(caseId) {
  if (!API) return null;
  const headers = await authHeaders();
  const res = await fetch(`${API}/evidence/case/${encodeURIComponent(caseId)}/verify-chain`, { headers });
  if (!res.ok) throw new Error(`Failed to verify evidence chain (${res.status})`);
  return await res.json();
}

export async function exportEvidencePackage(caseId) {
  if (!API) return null;
  const headers = await authHeaders();
  const res = await fetch(`${API}/evidence/case/${encodeURIComponent(caseId)}/export-package`, { headers });
  if (!res.ok) throw new Error(`Failed to export evidence package (${res.status})`);
  return await res.json();
}

export async function generateCaseReport(caseId, customNotes = null) {
  if (!API) return null;
  const headers = await authHeaders();
  const res = await fetch(`${API}/reports/generate/${encodeURIComponent(caseId)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify({ custom_notes: customNotes }),
  });
  if (!res.ok) throw new Error(`Failed to generate investigation report (${res.status})`);
  return await res.json();
}

export async function listCaseReports(caseId) {
  if (!API) return [];
  const headers = await authHeaders();
  const res = await fetch(`${API}/reports/case/${encodeURIComponent(caseId)}`, { headers });
  if (!res.ok) throw new Error(`Failed to list case reports (${res.status})`);
  return await res.json();
}

export async function verifyReportPDF(reportId) {
  if (!API) return null;
  const headers = await authHeaders();
  const res = await fetch(`${API}/reports/${encodeURIComponent(reportId)}/verify`, { headers });
  if (!res.ok) throw new Error(`Failed to verify report PDF hash (${res.status})`);
  return await res.json();
}

export async function getIntegrationStatus() {
  if (!API) return { ncrp_mode: "SIMULATION", sahyog_mode: "SIMULATION", ncrp_active: true, sahyog_active: true };
  const headers = await authHeaders();
  const res = await fetch(`${API}/integrations/status`, { headers });
  if (!res.ok) throw new Error(`Failed to fetch integration status (${res.status})`);
  return await res.json();
}

export async function submitNCRPReport(caseId) {
  if (!API) return null;
  const headers = await authHeaders();
  const res = await fetch(`${API}/integrations/ncrp/submit`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify({ case_id: caseId, submit_report: true }),
  });
  if (!res.ok) throw new Error(`Failed to submit NCRP report (${res.status})`);
  return await res.json();
}

export async function submitSahyogAction(caseId, actionType, targetWallet, targetVasp = null) {
  if (!API) return null;
  const headers = await authHeaders();
  const res = await fetch(`${API}/integrations/sahyog/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify({ case_id: caseId, action_type: actionType, target_wallet: targetWallet, target_vasp: targetVasp }),
  });
  if (!res.ok) throw new Error(`Failed to submit SAHYOG action (${res.status})`);
  return await res.json();
}



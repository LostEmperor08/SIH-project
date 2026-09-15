// =====================================================================
// sync-threat-intel — pulls LIVE sanctions & threat feeds
//
// Source 1: OFAC SDN sanctioned digital-currency addresses (auto-updated
//           mirror of the US Treasury SDN list, `lists` branch)
// Source 2: Chainabuse / CryptoScamDB style community feed (optional env)
//
// Schedule this hourly with pg_cron or Supabase Scheduled Functions.
// =====================================================================
import { admin, chunk, CORS, json, safeFetch } from "../_shared/lib.ts";

const OFAC_BASE =
  "https://raw.githubusercontent.com/0xB10C/ofac-sanctioned-digital-currency-addresses/lists";

// asset file -> our chain enum
const OFAC_FILES: Record<string, string> = {
  "sanctioned_addresses_XBT.json": "btc",
  "sanctioned_addresses_ETH.json": "eth",
  "sanctioned_addresses_USDT_TRON.json": "tron",
  "sanctioned_addresses_BSC.json": "bsc",
};

async function syncOfac() {
  const sb = admin();
  let total = 0;
  const perChain: Record<string, number> = {};

  for (const [file, chain] of Object.entries(OFAC_FILES)) {
    let addresses: string[];
    try {
      const res = await safeFetch(`${OFAC_BASE}/${file}`);
      addresses = await res.json();
    } catch (e) {
      console.warn(`skip ${file}: ${e.message}`);
      continue;
    }
    if (!Array.isArray(addresses)) continue;

    const rows = addresses.map((a) => ({
      chain,
      address: chain === "eth" || chain === "bsc" ? a.toLowerCase() : a,
      source: "OFAC_SDN",
      category: "sanctioned",
      entity_name: "OFAC SDN listed",
      severity: 100,
      reference_url: "https://sanctionssearch.ofac.treas.gov/",
      synced_at: new Date().toISOString(),
    }));

    for (const c of chunk(rows, 500)) {
      const { error } = await sb.from("threat_intel")
        .upsert(c, { onConflict: "chain,address,source" });
      if (error) console.error(error.message);
    }
    perChain[chain] = (perChain[chain] ?? 0) + rows.length;
    total += rows.length;
  }

  // propagate the flag onto any wallet we already track
  await sb.rpc("apply_threat_intel");
  return { total, perChain };
}

// Optional extra feed: set THREAT_FEED_URL to any JSON array of
// { address, chain, category, name } objects.
async function syncCustomFeed() {
  const url = Deno.env.get("THREAT_FEED_URL");
  if (!url) return { total: 0 };
  const sb = admin();
  const items = await (await safeFetch(url)).json();
  const rows = (items as any[]).map((i) => ({
    chain: i.chain ?? "eth",
    address: String(i.address).toLowerCase(),
    source: i.source ?? "COMMUNITY",
    category: i.category ?? "scam",
    entity_name: i.name ?? null,
    severity: i.severity ?? 70,
    reference_url: i.url ?? null,
  }));
  for (const c of chunk(rows, 500)) {
    await sb.from("threat_intel").upsert(c, { onConflict: "chain,address,source" });
  }
  await sb.rpc("apply_threat_intel");
  return { total: rows.length };
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  try {
    const t0 = Date.now();
    const ofac = await syncOfac();
    const custom = await syncCustomFeed();
    return json({ ok: true, ofac, custom, elapsedMs: Date.now() - t0 });
  } catch (e) {
    return json({ ok: false, error: String(e.message ?? e) }, 500);
  }
});

// Per-chain block explorer links.
//
// Every explorer link in the UI pointed at polygonscan.com regardless of
// chain, so a Bitcoin or Tron address resolved to a Polygon page showing
// nothing — which reads as "the tool found the wrong address".
const EXPLORERS = {
  btc: (a) => `https://blockstream.info/address/${a}`,
  eth: (a) => `https://etherscan.io/address/${a}`,
  polygon: (a) => `https://polygonscan.com/address/${a}`,
  bsc: (a) => `https://bscscan.com/address/${a}`,
  tron: (a) => `https://tronscan.org/#/address/${a}`,
};

const TX_EXPLORERS = {
  btc: (h) => `https://blockstream.info/tx/${h}`,
  eth: (h) => `https://etherscan.io/tx/${h}`,
  polygon: (h) => `https://polygonscan.com/tx/${h}`,
  bsc: (h) => `https://bscscan.com/tx/${h}`,
  tron: (h) => `https://tronscan.org/#/transaction/${h}`,
};

function codeOf(chain) {
  const s = String(chain ?? "").toLowerCase();
  if (s.includes("polygon") || s.includes("matic")) return "polygon";
  if (s.includes("tron") || s.includes("trc")) return "tron";
  if (s.includes("bitcoin") || s === "btc") return "btc";
  if (s.includes("bsc") || s.includes("binance") || s.includes("bnb")) return "bsc";
  if (s.includes("eth")) return "eth";
  return null;
}

/** Address explorer URL, or null when the chain is unknown — never a wrong link. */
export function addressExplorer(address, chain) {
  const c = codeOf(chain);
  return c && address ? EXPLORERS[c](address) : null;
}

/** Transaction explorer URL, or null. */
export function txExplorer(hash, chain) {
  const c = codeOf(chain);
  return c && hash ? TX_EXPLORERS[c](hash) : null;
}

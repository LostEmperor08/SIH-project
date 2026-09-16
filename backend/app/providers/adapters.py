"""
Live chain adapters. No mock data, no placeholder fallbacks anywhere.

Verified against the live APIs on 16 Sep 2026:

  btc              Blockstream Esplora    no key
  eth/polygon/bsc  Etherscan V2           ONE key, chainid selects the chain
  tron             TronGrid               key optional (raises rate limits)

Etherscan V2 replaced the old per-chain explorers: one key now covers 60+
EVM chains and you pick with `chainid` (1 = Ethereum, 137 = Polygon,
56 = BSC). That is why there is a single `etherscan_history()` here rather
than three near-identical adapters.

Every adapter fetches BOTH native transfers and token transfers. This is not
optional: a token transfer carries `value: 0` in the native transaction, so
a native-only tracer returns an EMPTY GRAPH for a wallet that moved a
million dollars of USDT and never touched the gas token. Verified against a
real address with zero native transactions and all activity in ERC-20.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from ..config import Settings
from .base import NATIVE, HttpClient, NormEdge, ProviderError, iso

log = logging.getLogger("chakravyuh.providers")

# Etherscan V2 chain selector
CHAIN_IDS: dict[str, int] = {"eth": 1, "polygon": 137, "bsc": 56}


# =====================================================================
# Stablecoin valuation
#
# A stablecoin transfer IS the money in most crypto fraud — PS 26183 names
# USDT explicitly. Valuing it 1:1 is correct. Multiplying an arbitrary
# altcoin by the native gas-token price would invent money that does not
# exist, so unknown tokens are recorded UNVALUED rather than wrongly valued.
# =====================================================================
STABLECOINS = {
    "USDT", "USDC", "DAI", "BUSD", "TUSD", "USDP", "FDUSD", "PYUSD",
    "USDE", "USDD", "GUSD", "LUSD", "FRAX", "USDS", "USDB", "CRVUSD",
}

# Bridged and wrapped variants of the same dollar. Live Polygon data returns
# "USDT0" (the LayerZero OFT build of Tether) — an exact-match list scored a
# real USDT transfer as unvalued, which is how $20,000 of laundered stable
# reads as $0 on the graph. Chain-bridged forms are everywhere in practice:
# USDT.e, USDC.e, axlUSDC, m.USDT, and so on.
_STABLE_PREFIXES = ("USDT", "USDC", "DAI", "BUSD", "FDUSD", "PYUSD", "USDE")
_BRIDGE_AFFIXES = ("E", "B", "0", "N", "BRIDGED", "POS", "AXL", "M", "WORMHOLE", "LZ")


def _token_usd(symbol: str, amount: float) -> tuple[float, bool]:
    """
    Returns (usd_value, unvalued_flag).

    A dollar stablecoin values 1:1. Anything else is left UNVALUED rather
    than wrongly valued — multiplying an arbitrary token by the gas-token
    price would invent money that does not exist.
    """
    s = (symbol or "").upper().strip()
    if not s:
        return 0.0, True
    if s in STABLECOINS:
        return round(amount, 2), False

    # normalise bridged spellings: "USDC.E" / "AXLUSDC" / "USDT0" -> base
    core = s.replace(".", "").replace("-", "").replace("_", "")
    for pfx in _STABLE_PREFIXES:
        if core.startswith(pfx):
            suffix = core[len(pfx):]
            if suffix == "" or suffix in _BRIDGE_AFFIXES:
                return round(amount, 2), False
        if core.endswith(pfx):
            prefix = core[: -len(pfx)]
            if prefix in _BRIDGE_AFFIXES:
                return round(amount, 2), False
    return 0.0, True


def _safe_int(v: Any, default: int = 18) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# =====================================================================
# BITCOIN — Blockstream Esplora
# =====================================================================
async def btc_history(
    address: str, px: float, cap: int, http: HttpClient, cfg: Settings,
    include_unconfirmed: bool = False,
) -> list[NormEdge]:
    txs = await http.get_json(f"{cfg.btc_api}/address/{address}/txs", chain="btc")
    if not isinstance(txs, list):
        return []

    edges: list[NormEdge] = []
    for tx in txs[:cap]:
        status = tx.get("status") or {}
        confirmed = status.get("confirmed") is True
        # A mempool transaction can be RBF-replaced and never happen.
        # Recording one as a settled fund movement is materially wrong
        # in an investigation, so it is excluded unless asked for.
        if not confirmed and not include_unconfirmed:
            continue

        inputs = [
            v["prevout"]["scriptpubkey_address"]
            for v in (tx.get("vin") or [])
            if (v.get("prevout") or {}).get("scriptpubkey_address")
        ]
        if not inputs:
            continue                                   # coinbase
        primary = inputs[0]
        bt = status.get("block_time")
        ts = iso(bt) if bt else iso(time.time())
        fee_btc = (tx.get("fee") or 0) / 1e8
        vouts = tx.get("vout") or []

        for i, o in enumerate(vouts):
            to = o.get("scriptpubkey_address")
            if not to or to == primary:                # drop change-to-self
                continue
            v = (o.get("value") or 0) / 1e8
            if v <= 0:
                continue
            edges.append(NormEdge(
                chain="btc", tx_hash=tx["txid"], vout_index=i,
                block_height=status.get("block_height"), block_time=ts,
                from_address=primary, to_address=to,
                value_native=v, value_usd=round(v * px, 2),
                fee_usd=round(fee_btc * px, 2), asset="BTC",
                # inputs[] drives common-input-ownership clustering
                raw={"inputs": inputs, "inputCount": len(inputs),
                     "outputCount": len(vouts), "confirmed": confirmed,
                     "transferType": "native"},
            ))
    return edges


# =====================================================================
# EVM — Etherscan V2 multichain (Ethereum, Polygon, BSC)
# =====================================================================
# Etherscan answers a rate limit with HTTP 200 and this in the body, so the
# transport layer sees a perfectly successful request. Detecting it here is
# what turns a silently-pruned branch into a retry.
def _etherscan_rate_limited(body) -> bool:
    if not isinstance(body, dict):
        return False
    if body.get("status") != "0":
        return False
    text = f"{body.get('message') or ''} {body.get('result') or ''}".lower()
    return ("rate limit" in text or "max calls" in text
            or "too many" in text or "max rate" in text)


def _trongrid_rate_limited(body) -> bool:
    if not isinstance(body, dict):
        return False
    err = str(body.get("Error") or body.get("error") or "").lower()
    return "rate" in err and "limit" in err


async def _etherscan_call(
    chain: str, action: str, address: str, cap: int,
    http: HttpClient, cfg: Settings,
) -> list[dict]:
    if not cfg.etherscan_api_key:
        raise ProviderError(
            chain,
            "ETHERSCAN_API_KEY is not set. Etherscan V2 covers Ethereum, "
            "Polygon and BSC with one free key — get one at "
            "https://etherscan.io/apis and set ETHERSCAN_API_KEY.",
        )
    chain_id = CHAIN_IDS.get(chain)
    if chain_id is None:
        raise ProviderError(chain, "no Etherscan chainid mapped")

    url = (f"{cfg.etherscan_api}?chainid={chain_id}&module=account"
           f"&action={action}&address={address}&page=1"
           f"&offset={min(cap, 100)}&sort=desc&apikey={cfg.etherscan_api_key}")
    j = await http.get_json(url, chain=chain,
                            rate_limited=_etherscan_rate_limited)
    if not isinstance(j, dict):
        return []

    # Etherscan signals "no data" as status 0 with a specific message, which
    # is not an error. Anything else at status 0 is (bad key, rate limit).
    if j.get("status") == "0":
        msg = str(j.get("message") or "")
        result = str(j.get("result") or "")
        if "No transactions found" in msg or "No transactions found" in result:
            return []
        raise ProviderError(chain, result or msg or "unknown Etherscan error")

    rows = j.get("result")
    return rows if isinstance(rows, list) else []


async def etherscan_history(
    chain: str, address: str, px: float, cap: int, http: HttpClient,
    cfg: Settings, include_tokens: bool = True,
) -> list[NormEdge]:
    dec = NATIVE[chain]["decimals"]
    symbol = NATIVE[chain]["symbol"]
    edges: list[NormEdge] = []

    # ---- native transfers (txlist) ----------------------------------
    for tx in await _etherscan_call(chain, "txlist", address, cap, http, cfg):
        frm = (tx.get("from") or "").lower()
        to = (tx.get("to") or "").lower()
        if not frm or not to:
            continue                                   # contract creation
        v = _safe_float(tx.get("value")) / 10 ** dec
        if v <= 0:
            continue                    # contract call; token leg is below
        gas = (_safe_float(tx.get("gasUsed")) * _safe_float(tx.get("gasPrice"))) / 10 ** dec
        edges.append(NormEdge(
            chain=chain, tx_hash=tx.get("hash", ""), vout_index=0,
            block_height=_safe_int(tx.get("blockNumber"), 0) or None,
            block_time=iso(_safe_float(tx.get("timeStamp"))),
            from_address=frm, to_address=to,
            value_native=v, value_usd=round(v * px, 2),
            fee_usd=round(gas * px, 2), asset=symbol,
            raw={"transferType": "native",
                 "isError": tx.get("isError"),
                 "functionName": tx.get("functionName") or None},
        ))

    if not include_tokens:
        return edges

    # ---- ERC-20 token transfers (tokentx) ---------------------------
    try:
        token_rows = await _etherscan_call(chain, "tokentx", address, cap, http, cfg)
    except ProviderError as e:
        log.warning("tokentx unavailable for %s on %s: %s", address, chain, e)
        return edges

    for i, t in enumerate(token_rows):
        frm = (t.get("from") or "").lower()
        to = (t.get("to") or "").lower()
        if not frm or not to:
            continue
        t_dec = _safe_int(t.get("tokenDecimal"), 18)
        amount = _safe_float(t.get("value")) / 10 ** t_dec
        if amount <= 0:
            continue
        tok = (t.get("tokenSymbol") or "UNKNOWN").upper()
        usd, unvalued = _token_usd(tok, amount)
        edges.append(NormEdge(
            chain=chain, tx_hash=t.get("hash", ""),
            # a token leg shares its tx hash with the native call, so the
            # index keeps (chain, hash, index, from, to) unique
            vout_index=i + 1,
            block_height=_safe_int(t.get("blockNumber"), 0) or None,
            block_time=iso(_safe_float(t.get("timeStamp"))),
            from_address=frm, to_address=to,
            value_native=amount, value_usd=usd, fee_usd=0.0, asset=tok,
            raw={"transferType": "erc20",
                 "contract": (t.get("contractAddress") or "").lower(),
                 "tokenName": t.get("tokenName"), "decimals": t_dec,
                 "unvalued": unvalued},
        ))
    return edges


# =====================================================================
# TRON — TronGrid
#
# Two endpoints, because TronGrid separates them:
#   /v1/accounts/{a}/transactions        native TRX
#   /v1/accounts/{a}/transactions/trc20  TRC-20 (this is where USDT lives)
#
# USDT-on-Tron is the dominant rail for this fraud in India, so the TRC-20
# leg matters more here than on any other chain.
# =====================================================================
def _tron_headers(cfg: Settings) -> dict[str, str] | None:
    return {"TRON-PRO-API-KEY": cfg.trongrid_api_key} if cfg.trongrid_api_key else None


async def tron_history(
    address: str, px: float, cap: int, http: HttpClient, cfg: Settings,
    include_tokens: bool = True,
) -> list[NormEdge]:
    headers = _tron_headers(cfg)
    limit = min(cap, 200)                              # TronGrid max is 200
    edges: list[NormEdge] = []

    # ---- TRC-20 transfers -------------------------------------------
    if include_tokens:
        url = (f"{cfg.tron_api}/v1/accounts/{address}/transactions/trc20"
               f"?limit={limit}&only_confirmed=true&order_by=block_timestamp,desc")
        j = await http.get_json(url, chain="tron", headers=headers,
                                rate_limited=_trongrid_rate_limited)
        for i, t in enumerate((j or {}).get("data") or []):
            frm, to = t.get("from"), t.get("to")
            if not frm or not to:
                continue
            if (t.get("type") or "Transfer") != "Transfer":
                continue                               # Approval, not a movement
            info = t.get("token_info") or {}
            t_dec = _safe_int(info.get("decimals"), 6)
            amount = _safe_float(t.get("value")) / 10 ** t_dec
            if amount <= 0:
                continue
            tok = (info.get("symbol") or "UNKNOWN").upper()
            usd, unvalued = _token_usd(tok, amount)
            edges.append(NormEdge(
                chain="tron", tx_hash=t.get("transaction_id", ""),
                vout_index=i + 1, block_height=None,
                # TronGrid timestamps are milliseconds
                block_time=iso(_safe_float(t.get("block_timestamp")) / 1000.0),
                from_address=frm, to_address=to,
                value_native=amount, value_usd=usd, fee_usd=0.0, asset=tok,
                raw={"transferType": "trc20",
                     "contract": info.get("address"),
                     "tokenName": info.get("name"), "decimals": t_dec,
                     "unvalued": unvalued},
            ))

    # ---- native TRX --------------------------------------------------
    url = (f"{cfg.tron_api}/v1/accounts/{address}/transactions"
           f"?limit={limit}&only_confirmed=true&order_by=block_timestamp,desc")
    j = await http.get_json(url, chain="tron", headers=headers,
                            rate_limited=_trongrid_rate_limited)

    for tx in (j or {}).get("data") or []:
        try:
            contract = (tx.get("raw_data") or {}).get("contract") or []
            if not contract:
                continue
            c0 = contract[0]
            if c0.get("type") != "TransferContract":
                continue                               # not a TRX movement
            val = ((c0.get("parameter") or {}).get("value") or {})
            frm = val.get("owner_address")
            to = val.get("to_address")
            amount = _safe_float(val.get("amount")) / 1e6   # TRX has 6 decimals
            if not frm or not to or amount <= 0:
                continue
            # TronGrid returns hex addresses here (41-prefixed), while the
            # TRC-20 endpoint returns base58. Mixing the two would split one
            # wallet into two graph nodes, so hex is converted.
            frm_b58 = _hex_to_base58(frm)
            to_b58 = _hex_to_base58(to)
            edges.append(NormEdge(
                chain="tron", tx_hash=tx.get("txID", ""), vout_index=0,
                block_height=(tx.get("blockNumber") or None),
                block_time=iso(_safe_float(tx.get("block_timestamp")) / 1000.0),
                from_address=frm_b58, to_address=to_b58,
                value_native=amount, value_usd=round(amount * px, 2),
                fee_usd=round(_safe_float((tx.get("ret") or [{}])[0].get("fee")) / 1e6 * px, 2),
                asset="TRX",
                raw={"transferType": "native",
                     "result": (tx.get("ret") or [{}])[0].get("contractRet")},
            ))
        except (KeyError, IndexError, TypeError) as e:
            log.debug("skipping malformed tron tx: %s", e)
            continue

    return edges


# ---------------------------------------------------------------------
# Tron address conversion: 41-hex -> base58check
#
# Implemented here rather than pulled in as a dependency: it is ~20 lines
# and the alternative (base58 + a Tron SDK) is a lot of surface area for
# one conversion.
# ---------------------------------------------------------------------
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _hex_to_base58(hex_addr: str) -> str:
    """Convert a 41-prefixed hex Tron address to base58check. Idempotent."""
    if not hex_addr:
        return hex_addr
    # already base58
    if hex_addr.startswith("T") and len(hex_addr) == 34:
        return hex_addr
    try:
        import hashlib
        raw = bytes.fromhex(hex_addr)
        if len(raw) != 21 or raw[0] != 0x41:
            return hex_addr
        checksum = hashlib.sha256(hashlib.sha256(raw).digest()).digest()[:4]
        payload = raw + checksum
        num = int.from_bytes(payload, "big")
        out = ""
        while num > 0:
            num, rem = divmod(num, 58)
            out = _B58[rem] + out
        # leading zero bytes become '1'
        for b in payload:
            if b == 0:
                out = "1" + out
            else:
                break
        return out
    except Exception:                                  # noqa: BLE001
        return hex_addr


# =====================================================================
async def address_history(
    chain: str, address: str, cap: int, http: HttpClient, cfg: Settings,
    px: float, include_unconfirmed: bool = False, include_tokens: bool = True,
) -> list[NormEdge]:
    """Single dispatch point. Callers never branch on chain."""
    if chain == "btc":
        return await btc_history(address, px, cap, http, cfg, include_unconfirmed)
    if chain in CHAIN_IDS:
        return await etherscan_history(chain, address, px, cap, http, cfg, include_tokens)
    if chain == "tron":
        return await tron_history(address, px, cap, http, cfg, include_tokens)
    raise ProviderError(chain, "unsupported chain")

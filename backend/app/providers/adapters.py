"""
Per-chain adapters. Each returns list[NormEdge].

Provider matrix (verified against the live APIs, 15 Sep 2026):

  btc      Blockstream Esplora   no key
  eth      Blockscout v2         no key
  polygon  Blockscout v2         no key
  tron     TronScan              no key
  bsc      Etherscan V2          FREE KEY (chainid=56)

Two behaviours here exist because the live APIs proved them necessary, not
because they seemed like good ideas:

  * Blockscout's `filter` accepts "to" OR "from" and returns HTTP 422 for
    "to | from". We send no filter at all; unfiltered returns both
    directions, which is what a trace needs.
  * Blockstream returns mempool transactions as status {confirmed: false}
    with NO block_time. Treating one as a settled movement is materially
    wrong — it can be RBF-replaced and never happen. Excluded by default.
"""
from __future__ import annotations

import logging
from typing import Any

from ..config import Settings
from .base import NATIVE, HttpClient, NormEdge, ProviderError, iso

log = logging.getLogger("chakravyuh.providers")


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
        block_time = status.get("block_time")
        ts = iso(block_time) if block_time else iso(__import__("time").time())
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
                # inputs[] is what drives common-input-ownership clustering
                raw={"inputs": inputs, "inputCount": len(inputs),
                     "outputCount": len(vouts), "confirmed": confirmed},
            ))
    return edges


# =====================================================================
# Stablecoin valuation
#
# A stablecoin transfer IS the money in most crypto fraud — PS 26183 names
# USDT explicitly. Valuing it 1:1 is right; multiplying an arbitrary
# altcoin by the native gas-token price would be nonsense, so unknown
# tokens are recorded unvalued rather than wrongly valued.
# =====================================================================
STABLECOINS = {"USDT", "USDC", "DAI", "BUSD", "TUSD", "USDP", "FDUSD", "PYUSD", "USDE"}


def _token_usd(symbol: str, amount: float) -> tuple[float, bool]:
    """Returns (usd_value, unvalued_flag)."""
    s = (symbol or "").upper()
    if s in STABLECOINS:
        return round(amount, 2), False
    return 0.0, True


# =====================================================================
# EVM via Blockscout — Ethereum, Polygon
#
# Fetches BOTH native transfers and ERC-20 token transfers.
#
# Token transfers are not optional. A native-only tracer is blind to the
# way this fraud actually moves: an ERC-20 transfer carries `value: 0` in
# the native transaction, so a wallet that moved a million dollars of USDT
# and never touched ETH returns an EMPTY GRAPH. That was verified against
# two real addresses — one of them had zero native transactions and all of
# its activity in tokens.
# =====================================================================
async def blockscout_history(
    chain: str, address: str, px: float, cap: int, http: HttpClient, cfg: Settings,
    include_tokens: bool = True,
) -> list[NormEdge]:
    base = {"eth": cfg.eth_api, "polygon": cfg.polygon_api}.get(chain)
    if not base:
        raise ProviderError(chain, "no Blockscout endpoint configured")

    edges: list[NormEdge] = []
    dec = NATIVE[chain]["decimals"]

    # ---- native transfers -------------------------------------------
    # deliberately no `filter` param — see module docstring
    j = await http.get_json(f"{base}/addresses/{address}/transactions", chain=chain)
    for tx in ((j or {}).get("items") or [])[:cap]:
        frm = ((tx.get("from") or {}).get("hash") or "").lower()
        to = ((tx.get("to") or {}).get("hash") or "").lower()
        if not frm or not to:
            continue                                   # contract creation
        v = float(tx.get("value") or 0) / 10 ** dec    # value arrives as a string
        if v <= 0:
            continue                # contract call — the token leg is below
        gas = (float(tx.get("gas_used") or 0) * float(tx.get("gas_price") or 0)) / 10 ** dec
        edges.append(NormEdge(
            chain=chain, tx_hash=tx.get("hash", ""), vout_index=0,
            block_height=tx.get("block_number") or tx.get("block"),
            block_time=tx.get("timestamp") or iso(__import__("time").time()),
            from_address=frm, to_address=to,
            value_native=v, value_usd=round(v * px, 2),
            fee_usd=round(gas * px, 2), asset=NATIVE[chain]["symbol"],
            raw={"method": tx.get("method"), "status": tx.get("status"),
                 "transferType": "native"},
        ))

    if not include_tokens:
        return edges

    # ---- ERC-20 token transfers --------------------------------------
    try:
        tj = await http.get_json(
            f"{base}/addresses/{address}/token-transfers?type=ERC-20", chain=chain)
    except ProviderError as e:
        log.warning("token-transfers unavailable for %s: %s", address, e)
        return edges

    for i, t in enumerate(((tj or {}).get("items") or [])[:cap]):
        frm = ((t.get("from") or {}).get("hash") or "").lower()
        to = ((t.get("to") or {}).get("hash") or "").lower()
        if not frm or not to:
            continue
        token = t.get("token") or {}
        symbol = token.get("symbol") or "UNKNOWN"
        try:
            t_dec = int(token.get("decimals") or 18)
        except (TypeError, ValueError):
            t_dec = 18
        raw_amt = (t.get("total") or {}).get("value") or t.get("value") or 0
        amount = float(raw_amt) / 10 ** t_dec
        if amount <= 0:
            continue

        usd, unvalued = _token_usd(symbol, amount)
        edges.append(NormEdge(
            chain=chain, tx_hash=t.get("transaction_hash") or t.get("tx_hash") or "",
            # token legs share a tx hash with the native call, so the index
            # keeps the (chain, hash, index, from, to) key unique
            vout_index=i + 1,
            block_height=t.get("block_number") or t.get("block"),
            block_time=t.get("timestamp") or iso(__import__("time").time()),
            from_address=frm, to_address=to,
            value_native=amount, value_usd=usd, fee_usd=0.0, asset=symbol,
            raw={"transferType": "erc20",
                 "contract": (token.get("address") or "").lower(),
                 "tokenName": token.get("name"), "decimals": t_dec,
                 "unvalued": unvalued},
        ))

    return edges


# =====================================================================
# TRON — TronScan
# =====================================================================
async def tron_history(
    address: str, px: float, cap: int, http: HttpClient, cfg: Settings,
) -> list[NormEdge]:
    url = (f"{cfg.tron_api}/api/transfer?address={address}"
           f"&limit={min(cap, 50)}&start=0&sort=-timestamp")
    headers = {"TRON-PRO-API-KEY": cfg.tronscan_api_key} if cfg.tronscan_api_key else None
    j = await http.get_json(url, chain="tron", headers=headers)

    edges: list[NormEdge] = []
    for t in ((j or {}).get("data") or [])[:cap]:
        frm, to = t.get("transferFromAddress"), t.get("transferToAddress")
        if not frm or not to:
            continue
        info = t.get("tokenInfo") or {}
        decimals = int(info.get("tokenDecimal") or 6)
        v = float(t.get("amount") or 0) / 10 ** decimals
        if v <= 0:
            continue

        symbol = (info.get("tokenAbbr") or "TRX").upper()
        if symbol == "TRX":
            usd = round(v * px, 2)
        elif "USD" in symbol:
            usd = round(v, 2)          # a dollar stablecoin is already USD
        else:
            # Multiplying an arbitrary TRC20 by the TRX price would be
            # nonsense, so it is left unvalued rather than wrong.
            usd = 0.0

        edges.append(NormEdge(
            chain="tron", tx_hash=t.get("transactionHash") or t.get("hash") or "",
            vout_index=0, block_height=t.get("block"),
            block_time=iso(float(t.get("timestamp", 0)) / 1000.0),
            from_address=frm, to_address=to,
            value_native=v, value_usd=usd, fee_usd=0.0, asset=symbol,
            raw={"confirmed": t.get("confirmed"), "contractRet": t.get("contractRet"),
                 "tokenName": info.get("tokenName"),
                 "unvalued": usd == 0.0 and symbol != "TRX"},
        ))
    return edges


# =====================================================================
# BSC — Etherscan V2 multichain (free key)
# =====================================================================
async def bsc_history(
    address: str, px: float, cap: int, http: HttpClient, cfg: Settings,
) -> list[NormEdge]:
    if not cfg.etherscan_api_key:
        raise ProviderError(
            "bsc",
            "BSC requires ETHERSCAN_API_KEY. Every keyless BSC explorer has "
            "closed (bnb/bsc.blockscout.com 404, Routescan rejects chain 56). "
            "One free key at etherscan.io covers BSC and all other EVM chains.",
        )
    url = (f"https://api.etherscan.io/v2/api?chainid=56&module=account&action=txlist"
           f"&address={address}&page=1&offset={min(cap, 100)}&sort=desc"
           f"&apikey={cfg.etherscan_api_key}")
    j = await http.get_json(url, chain="bsc")
    if isinstance(j, dict) and j.get("status") == "0" \
            and j.get("message") != "No transactions found":
        raise ProviderError("bsc", str(j.get("result") or j.get("message")))

    rows = (j or {}).get("result") or []
    if not isinstance(rows, list):
        return []

    edges: list[NormEdge] = []
    for tx in rows:
        frm, to = (tx.get("from") or "").lower(), (tx.get("to") or "").lower()
        if not frm or not to:
            continue
        v = float(tx.get("value") or 0) / 1e18
        if v <= 0:
            continue
        gas = (float(tx.get("gasUsed") or 0) * float(tx.get("gasPrice") or 0)) / 1e18
        edges.append(NormEdge(
            chain="bsc", tx_hash=tx.get("hash", ""), vout_index=0,
            block_height=int(tx["blockNumber"]) if tx.get("blockNumber") else None,
            block_time=iso(float(tx.get("timeStamp", 0))),
            from_address=frm, to_address=to,
            value_native=v, value_usd=round(v * px, 2),
            fee_usd=round(gas * px, 2), asset="BNB",
            raw={"isError": tx.get("isError"), "functionName": tx.get("functionName")},
        ))
    return edges


# =====================================================================
async def address_history(
    chain: str, address: str, cap: int, http: HttpClient, cfg: Settings,
    px: float, include_unconfirmed: bool = False, include_tokens: bool = True,
) -> list[NormEdge]:
    """Single dispatch point. Callers never branch on chain."""
    if chain == "btc":
        return await btc_history(address, px, cap, http, cfg, include_unconfirmed)
    if chain in ("eth", "polygon"):
        return await blockscout_history(chain, address, px, cap, http, cfg,
                                        include_tokens)
    if chain == "tron":
        return await tron_history(address, px, cap, http, cfg)
    if chain == "bsc":
        return await bsc_history(address, px, cap, http, cfg)
    raise ProviderError(chain, "unsupported chain")

"""
On-chain real-time signal source for the esports fade bot.

WHY: the Polymarket data-api /trades feed is ~220s behind real-time (measured
2026-05-29). That lag is 99.7% of our total signal latency and is almost
certainly why the fade edge is ~0 — we arrive minutes after the target's bad
bet, once the market has already absorbed it. The Polygon chain tip is ~2s
behind real-time, so watching on-chain collapses detection latency ~100x.

HOW: target trades settle as ERC-1155 TransferSingle events on the Polymarket
Conditional Tokens contract (0x4d97...6045). The proxy wallet appears as the
`to` (a BUY) or `from` (a SELL) indexed topic, with the position token id and
share amount in the data. We poll eth_getLogs every ~2s filtered to our target
wallets, decode each transfer, resolve price via the CLOB midpoint, and hand a
data-api-shaped trade dict to the bot via a callback. The bot runs it through
the SAME process_trade pipeline (all existing safety gates apply).

SAFETY: we only ever emit a signal when token, market, and a sane price all
resolve; anything ambiguous is dropped. Orders are LIMIT orders at our computed
entry, so a price error cannot make us overpay.
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque

import requests
from eth_abi import decode as abi_decode
from web3 import Web3

# Polymarket Conditional Tokens (ERC-1155) on Polygon. NOT the exchange — this
# is the token contract that emits TransferSingle on every position move.
CTF_CONTRACT = "0x4d97dcd97ec945f40cf65f87097ace5ea0476045"
TRANSFER_SINGLE_TOPIC = Web3.to_hex(
    Web3.keccak(text="TransferSingle(address,address,address,uint256,uint256)")
).lower()

DEFAULT_RPCS = [
    "https://polygon-bor-rpc.publicnode.com",
    "https://polygon-rpc.com",
    "https://rpc.ankr.com/polygon",
    "https://polygon.llamarpc.com",
    "https://polygon.drpc.org",
    "https://1rpc.io/matic",
]

POLL_INTERVAL = 15.0         # seconds between getLogs polls. Raised 3s->15s on
                             # 2026-06-17 after the Alchemy key hit its 30M CU cap
                             # in ~6 days (3s polling 24/7 = ~5M CU/day). At 15s the
                             # burn is ~1M CU/day so 30M lasts a full month, and
                             # detection latency is still ~15s vs the ~220s data-api
                             # it replaced (~15x faster) — a non-issue while the fade
                             # edge is ~0. Drop back toward 3-5s only if the edge
                             # proves real and the CU budget is raised.
MAX_BLOCK_LOOKBACK = 40      # if we fall behind, never scan more than this many blocks
# Addresses per getLogs topic filter. Alchemy (our primary RPC) handles all 300
# wallets in ONE filter, so a poll is just 2 getLogs (to + from) instead of 6 —
# ~3x fewer requests = ~3x less Compute Unit usage. If a query errors (e.g. a
# picky public-RPC fallback rejects a large topic array), we downshift to 120.
WALLET_CHUNK_DEFAULT = 300
WALLET_CHUNK_SAFE = 120


def _pad_addr(addr: str) -> str:
    """0x-address -> 32-byte topic hex."""
    return "0x" + "0" * 24 + addr.lower().replace("0x", "")


class OnChainListener(threading.Thread):
    def __init__(self, wallets: set[str], token_index: dict,
                 on_signal, clob_session: requests.Session | None = None,
                 log=print):
        """
        wallets:      set of lowercased target proxy-wallet addresses
        token_index:  {token_id(str) -> (condition_id, outcome, slug)}
        on_signal:    callback(trade_dict) — bot enqueues for process_trade
        """
        super().__init__(daemon=True, name="onchain-listener")
        self.wallets = set(w.lower() for w in wallets)
        self.token_index = token_index
        self.on_signal = on_signal
        self.clob = clob_session or requests.Session()
        self.log = log
        self.w3: Web3 | None = None
        self._rpc_idx = 0            # rotates across endpoints on failure
        self._consec_errors = 0      # trip a rotation after repeated errors
        self._chunk = WALLET_CHUNK_DEFAULT  # downshifts to SAFE if a query errors
        self.active_rpc = None
        self.last_block = None
        self._seen = deque(maxlen=5000)      # (txhash, logIndex) dedup
        self._seen_set: set = set()
        self._block_ts: dict[int, int] = {}  # block -> timestamp cache
        self._stop = threading.Event()
        # stats (read by the bot heartbeat)
        self.n_detected = 0
        self.n_emitted = 0
        self.n_dropped = 0
        self.last_detect_lag = None
        self.connected = False

    def _rpc_list(self) -> list[str]:
        """Endpoint priority: a configured POLYGON_RPC_URL (e.g. Alchemy/QuickNode
        key) is always tried FIRST, then the public fallbacks."""
        urls = []
        env_url = os.environ.get("POLYGON_RPC_URL", "").strip()
        if env_url:
            urls.append(env_url)
        urls += DEFAULT_RPCS
        return urls

    # ── connection ───────────────────────────────────────────────────────
    def _connect(self) -> bool:
        urls = self._rpc_list()
        # Start from the current rotation index so a flaky endpoint is skipped
        # next time rather than retried first.
        n = len(urls)
        for off in range(n):
            url = urls[(self._rpc_idx + off) % n]
            try:
                w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 10}))
                try:
                    from web3.middleware import ExtraDataToPOAMiddleware
                    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
                except Exception:
                    pass
                if w3.is_connected():
                    self.w3 = w3
                    self.connected = True
                    self.active_rpc = url
                    self._rpc_idx = (self._rpc_idx + off) % n
                    self._consec_errors = 0
                    # Don't leak a full Alchemy key into logs
                    safe = url.split("/v2/")[0] if "/v2/" in url else url
                    self.log(f"[onchain] connected: {safe}")
                    return True
            except Exception as e:
                self.log(f"[onchain] connect failed {url}: {e}")
        self.connected = False
        return False

    def _rotate_rpc(self, why: str):
        """Advance to the next endpoint and force a reconnect."""
        n = len(self._rpc_list())
        self._rpc_idx = (self._rpc_idx + 1) % n
        self.w3 = None
        self.connected = False
        self._consec_errors = 0
        self.log(f"[onchain] rotating RPC ({why}) -> idx {self._rpc_idx}")

    def update_wallets(self, wallets: set[str]):
        self.wallets = set(w.lower() for w in wallets)

    def stop(self):
        self._stop.set()

    # ── helpers ──────────────────────────────────────────────────────────
    def _block_timestamp(self, block_number: int) -> int:
        if block_number in self._block_ts:
            return self._block_ts[block_number]
        try:
            b = self.w3.eth.get_block(block_number)
            ts = int(b["timestamp"])
        except Exception:
            ts = int(time.time())
        # keep cache small
        if len(self._block_ts) > 500:
            self._block_ts.clear()
        self._block_ts[block_number] = ts
        return ts

    def _clob_midpoint(self, token_id: str) -> float | None:
        try:
            r = self.clob.get("https://clob.polymarket.com/midpoint",
                               params={"token_id": token_id}, timeout=4)
            if r.status_code == 200:
                m = r.json().get("mid")
                return float(m) if m is not None else None
        except Exception:
            return None
        return None

    def _get_logs_for(self, from_block, to_block, position):
        """position: 'to' (buys) or 'from' (sells).
        Returns (logs, ok). ok=False if any chunk query errored (caller should
        not advance the cursor so the range is retried)."""
        wallets = list(self.wallets)
        out = []
        ok = True
        for i in range(0, len(wallets), self._chunk):
            chunk = [_pad_addr(w) for w in wallets[i:i + self._chunk]]
            if position == "to":
                topics = [TRANSFER_SINGLE_TOPIC, None, None, chunk]
            else:  # from
                topics = [TRANSFER_SINGLE_TOPIC, None, chunk, None]
            try:
                logs = self.w3.eth.get_logs({
                    "fromBlock": from_block, "toBlock": to_block,
                    "address": Web3.to_checksum_address(CTF_CONTRACT),
                    "topics": topics,
                })
                out.extend((position, lg) for lg in logs)
            except Exception as e:
                ok = False
                # A large topic array can be rejected by some public RPCs;
                # downshift the chunk size so retries (and fallbacks) succeed.
                if self._chunk > WALLET_CHUNK_SAFE:
                    self._chunk = WALLET_CHUNK_SAFE
                    self.log(f"[onchain] downshifting wallet chunk -> {self._chunk}")
                self.log(f"[onchain] get_logs error ({position}) "
                         f"[{from_block}-{to_block}]: {e}")
        return out, ok

    def _topic_addr(self, tp) -> str:
        return "0x" + Web3.to_hex(tp)[-40:]

    # ── main loop ────────────────────────────────────────────────────────
    def run(self):
        while not self._stop.is_set():
            if not self.w3 and not self._connect():
                time.sleep(5)
                continue
            try:
                latest = self.w3.eth.block_number
            except Exception as e:
                self.log(f"[onchain] block_number failed: {e}; rotating")
                self._rotate_rpc("block_number error")
                time.sleep(2)
                continue

            if self.last_block is None:
                self.last_block = latest - 3   # small initial lookback
            # Query up to one block behind the tip — public RPC load-balancers
            # serve slightly different tips, so the very latest block may not yet
            # exist on the node that answers the getLogs call ("invalid block
            # range"). One block of confirmation lag avoids that flapping.
            to_block = latest - 1
            if to_block < self.last_block:
                # tip went backwards (different node) or no new block — wait
                time.sleep(POLL_INTERVAL)
                continue
            from_block = self.last_block + 1
            if from_block > to_block:
                time.sleep(POLL_INTERVAL)
                continue
            # don't scan an unbounded range if we fell behind
            if to_block - from_block > MAX_BLOCK_LOOKBACK:
                from_block = to_block - MAX_BLOCK_LOOKBACK

            if not self.wallets:
                self.last_block = to_block
                time.sleep(POLL_INTERVAL)
                continue

            logs_to, ok1 = self._get_logs_for(from_block, to_block, "to")
            logs_from, ok2 = self._get_logs_for(from_block, to_block, "from")
            for position, lg in (logs_to + logs_from):
                self._handle_log(position, lg)

            # Only advance the cursor if BOTH queries succeeded; otherwise retry
            # the same range next poll so we never silently skip blocks.
            if ok1 and ok2:
                self.last_block = to_block
                self._consec_errors = 0
            else:
                # Repeated getLogs failures on this endpoint -> rotate away from it.
                self._consec_errors += 1
                if self._consec_errors >= 3:
                    self._rotate_rpc("repeated getLogs errors")
            time.sleep(POLL_INTERVAL)

    def _handle_log(self, position, lg):
        try:
            txhash = Web3.to_hex(lg["transactionHash"])
            key = (txhash, lg["logIndex"])
            if key in self._seen_set:
                return
            self._seen.append(key)
            self._seen_set.add(key)
            if len(self._seen_set) > 5000:
                # rebuild from deque
                self._seen_set = set(self._seen)

            if Web3.to_hex(lg["topics"][0]).lower() != TRANSFER_SINGLE_TOPIC:
                return
            frm = self._topic_addr(lg["topics"][2]).lower()
            to = self._topic_addr(lg["topics"][3]).lower()
            wallet = to if (position == "to") else frm
            if wallet not in self.wallets:
                return
            token_id, value = abi_decode(["uint256", "uint256"], bytes(lg["data"]))
            shares = value / 1e6
            if shares <= 0:
                return
            self.n_detected += 1

            side = "BUY" if position == "to" else "SELL"
            tinfo = self.token_index.get(str(token_id))
            if not tinfo:
                self.n_dropped += 1
                return  # unknown token (not an indexed esports market) — skip
            cid, outcome, slug = tinfo

            their_price = self._clob_midpoint(str(token_id))
            if their_price is None or not (0.05 <= their_price <= 0.95):
                self.n_dropped += 1
                return  # no sane price — skip (never fire with bad price)

            block_ts = self._block_timestamp(lg["blockNumber"])
            self.last_detect_lag = time.time() - block_ts

            trade = {
                "transactionHash": txhash,
                "proxyWallet": wallet,
                "timestamp": block_ts,
                "slug": slug,
                "eventSlug": slug,
                "side": side,
                "outcome": outcome,
                "price": round(their_price, 3),
                "size": round(shares, 2),
                "conditionId": cid,
                "_source": "onchain",
                "_detect_lag_s": round(self.last_detect_lag, 1),
            }
            self.n_emitted += 1
            self.on_signal(trade)
        except Exception as e:
            self.log(f"[onchain] handle_log error: {e}")

"""Where the checker gets facts about a receiver.

LiveChain  : NEAR testnet RPC + the keyless FastNEAR transaction index (account age, activity, deploys)
             + the guard contract's on-chain allowlist, blocklist and reports.
ReplayChain: the same answers read from a recorded fixture, so the demo runs offline and gives the same
             output every time. `record()` writes such a fixture from live data.
Both return plain dicts; None for a field means 'could not find out' (the checker treats that as a risk)."""
import json
import time
import urllib.error
import urllib.request

from . import nearlib

TX_API = "https://tx.test.fastnear.com"
ZERO_HASH = "11111111111111111111111111111111"


def _post(url, body, timeout=20):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"content-type": "application/json"})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(1 + i)
    return None


class LiveChain:
    label = "live testnet"

    def __init__(self, guard, rpc=None, tx_api=TX_API):
        self.guard = guard
        self.rpc = rpc or nearlib.Rpc()
        self.tx_api = tx_api

    def now_ns(self):
        return time.time_ns()

    def account(self, account):
        try:
            a = self.rpc.view_account(account)
        except nearlib.RpcError:
            return {"known": False}
        if a is None:
            return {"known": True, "exists": False}
        return {"known": True, "exists": True, "code_hash": None if a["code_hash"] == ZERO_HASH else a["code_hash"],
                "balance_near": int(a["amount"]) / nearlib.NEAR}

    def history(self, account):
        first = _post(f"{self.tx_api}/v0/account", {"account_id": account, "limit": 1, "desc": False})
        last = _post(f"{self.tx_api}/v0/account", {"account_id": account, "limit": 20, "desc": True})
        if first is None or last is None:
            return {"known": False}
        txs = first.get("account_txs") or []
        recent = last.get("account_txs") or []
        out = {"known": True, "tx_count": last.get("txs_count") or first.get("txs_count") or 0,
               "first_tx_ns": int(txs[0]["tx_block_timestamp"]) if txs else None,
               "last_tx_ns": int(recent[0]["tx_block_timestamp"]) if recent else None, "last_deploy_ns": None}
        hashes = [t["transaction_hash"] for t in recent][:20]
        stamp = {t["transaction_hash"]: int(t["tx_block_timestamp"]) for t in recent}
        if hashes:
            full = _post(f"{self.tx_api}/v0/transactions", {"tx_hashes": hashes})
            for t in (full or {}).get("transactions", []):
                for rc in t.get("receipts", []):
                    r = rc.get("receipt", {})
                    acts = (r.get("receipt", {}).get("Action") or {}).get("actions", [])
                    if r.get("receiver_id") == account and any("DeployContract" in a for a in acts if isinstance(a, dict)):
                        ts = stamp.get(t["transaction"]["hash"])
                        if ts and (out["last_deploy_ns"] is None or ts > out["last_deploy_ns"]):
                            out["last_deploy_ns"] = ts
        return out

    def guard_view(self, account):
        """What the guard contract knows: blocklist entry, allowlisted?, reports (with evidence)."""
        try:
            return {"known": True, **self.rpc.view_call(self.guard, "get_receiver", {"account": account})}
        except nearlib.RpcError:
            return {"known": False}

    def allowlist(self):
        try:
            return self.rpc.view_call(self.guard, "get_allowlist") or []
        except nearlib.RpcError:
            return []

    def policy(self):
        return self.rpc.view_call(self.guard, "get_policy")

    def snapshot(self, account):
        return {"account": self.account(account), "history": self.history(account), "guard": self.guard_view(account)}


class ReplayChain:
    """Reads answers from fixtures/chain_snapshot.json (recorded from the live testnet)."""
    def __init__(self, path):
        with open(path) as f:
            doc = json.load(f)
        self.doc = doc
        self.guard = doc.get("guard")
        self.label = f"replay of testnet data recorded {doc['recorded_at']}"
        self._now = int(doc["as_of_ns"])

    def now_ns(self):
        return self._now

    def _get(self, account):
        return self.doc["accounts"].get(account)

    def account(self, account):
        s = self._get(account)
        return s["account"] if s else {"known": True, "exists": False}

    def history(self, account):
        s = self._get(account)
        return s["history"] if s else {"known": True, "tx_count": 0, "first_tx_ns": None, "last_tx_ns": None, "last_deploy_ns": None}

    def allowlist(self):
        return self.doc.get("allowlist", [])

    def policy(self):
        return self.doc["policy"]

    def guard_view(self, account):
        s = self._get(account)
        return s["guard"] if s else {"known": True, "blocked": None, "allowlisted": False, "reports": []}


def record(chain: LiveChain, accounts, path, extra=None):
    doc = {"label": "REAL testnet responses, recorded for offline replay", "guard": chain.guard,
           "recorded_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "as_of_ns": chain.now_ns(),
           "accounts": {a: chain.snapshot(a) for a in accounts}}
    doc.update(extra or {})
    with open(path, "w") as f:
        json.dump(doc, f, indent=1, sort_keys=True)
    return doc

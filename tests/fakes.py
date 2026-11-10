"""Small in-memory stand-ins for the chain, used only by the tests (labelled: not real data)."""
import tempfile

from scambrake.checker import Checker, Store, DAY, HOUR

NOW = 1_800_000_000 * 10**9


class FakeChain:
    label = "fake chain (tests)"

    def __init__(self, accounts=None, allow=(), unknown=False):
        self.accounts = accounts or {}
        self._allow = list(allow)
        self.unknown = unknown
        self.guard = "guard.test.testnet"

    def now_ns(self):
        return NOW

    def account(self, a):
        if self.unknown:
            return {"known": False}
        s = self.accounts.get(a)
        return s["account"] if s else {"known": True, "exists": False}

    def history(self, a):
        if self.unknown:
            return {"known": False}
        s = self.accounts.get(a)
        return s["history"] if s else {"known": True, "tx_count": 0, "first_tx_ns": None, "last_tx_ns": None, "last_deploy_ns": None}

    def guard_view(self, a):
        if self.unknown:
            return {"known": False}
        s = self.accounts.get(a)
        g = (s or {}).get("guard") or {}
        return {"known": True, "blocked": g.get("blocked"), "allowlisted": a in self._allow, "reports": g.get("reports", [])}

    def allowlist(self):
        return self._allow


def acct(age_ns=400 * DAY, txs=50, code=None, last_ago=HOUR, deployed_ago=None, guard=None):
    return {"account": {"known": True, "exists": True, "code_hash": code, "balance_near": 10.0},
            "history": {"known": True, "tx_count": txs, "first_tx_ns": NOW - age_ns, "last_tx_ns": NOW - last_ago,
                        "last_deploy_ns": None if deployed_ago is None else NOW - deployed_ago},
            "guard": guard or {}}


def make(accounts=None, allow=(), blocklist=None, intel=None, unknown=False):
    chain = FakeChain(accounts, allow, unknown)
    store = Store(tempfile.mkdtemp(prefix="sbtest-"))
    return Checker(chain, store, blocklist=blocklist, trusted=allow, intel=intel), chain, store

"""The counterparty check. Ask it about a receiver before paying; it answers allow, warn or block,
with reasons. Every reason says which signal fired, how many risk points it added, and the evidence.

Signals (the data source is in brackets):
  blocklist        shared blocklist with evidence    [guard contract on chain + data/blocklist.json]
  reports          reports from other agents/people  [guard contract `report`]
  account_exists   does the account exist at all     [NEAR RPC view_account]
  age, activity    first transaction, tx count       [FastNEAR transaction index]
  contract         has code? code changed?           [NEAR RPC code_hash, pinned hash, deploy txs]
  prior_payments   have we paid it safely before     [local ledger of this agent's own payments]
  lookalike        name nearly equal to a trusted one [allowlist + edit distance]
  scam_posts       receiver pushed by scam posts     [scanner over crypto-Twitter posts]
  instruction_source  the text that told the agent to pay is itself a prompt injection [scanner]

Risk points add up (0-100). block at 70 or more (or a blocklist hit), warn at 30 or more, else allow.
If a source cannot be reached the answer is 'unknown' and that adds points: a check that cannot see
should not say allow."""
import json
import os
import re
import time

from . import scanner

BLOCK_AT = 70
WARN_AT = 30
DAY = 86_400 * 10**9
HOUR = 3_600 * 10**9
ACCOUNT_RE = re.compile(r"^(([a-z\d]+[-_])*[a-z\d]+\.)*([a-z\d]+[-_])*[a-z\d]+$")
_LOOK = str.maketrans({"0": "o", "1": "l", "3": "e", "4": "a", "5": "s", "7": "t", "-": "", "_": ""})


def edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def ago(ns):
    if ns >= DAY:
        return f"{ns / DAY:.1f} days ago"
    if ns >= HOUR:
        return f"{ns / HOUR:.1f} hours ago"
    return f"{max(1, round(ns / (60 * 10**9)))} minutes ago"


class Store:
    """Small local state: ledger of this agent's own payments, pinned contract hashes."""
    def __init__(self, directory):
        self.dir = directory
        os.makedirs(directory, exist_ok=True)
        self.ledger_path = os.path.join(directory, "ledger.jsonl")
        self.pins_path = os.path.join(directory, "pins.json")

    def payments(self, receiver=None):
        if not os.path.exists(self.ledger_path):
            return []
        with open(self.ledger_path) as f:
            rows = [json.loads(l) for l in f if l.strip()]
        return [r for r in rows if receiver is None or r["receiver"] == receiver]

    def add_payment(self, receiver, amount_near, tx_hash=None, note=""):
        with open(self.ledger_path, "a") as f:
            f.write(json.dumps({"receiver": receiver, "amount_near": amount_near, "tx": tx_hash, "note": note, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}) + "\n")

    def pins(self):
        if not os.path.exists(self.pins_path):
            return {}
        with open(self.pins_path) as f:
            return json.load(f)

    def pin(self, account, code_hash):
        p = self.pins()
        p[account] = code_hash
        json.dump(p, open(self.pins_path, "w"), indent=1)


class Checker:
    def __init__(self, chain, store, blocklist=None, trusted=(), intel=None):
        """blocklist: {account: {'reason','evidence':[...],'reported_by'}} (local shared list)
        trusted: accounts the human owner has approved (also read from the guard allowlist)
        intel: {address: {'posts': [...], 'categories': [...], 'max_score': n}} from scanner.scan_posts"""
        self.chain, self.store = chain, store
        self.blocklist = blocklist or {}
        self.trusted = set(trusted)
        self.intel = intel or {}

    def check(self, receiver, amount_near=None, instruction_text=None):
        reasons = []
        hard_block = False
        self._force_warn = False

        def add(signal, points, text, evidence=None):
            reasons.append({"signal": signal, "points": points, "text": text, "evidence": evidence})

        receiver = receiver.strip()
        if not ACCOUNT_RE.match(receiver) or len(receiver) > 64 or len(receiver) < 2:
            add("account_id", 100, "not a valid NEAR account id")
            return self._result(receiver, reasons, True)

        # 1. blocklists (local shared file, then the guard contract)
        local = self.blocklist.get(receiver)
        if local:
            hard_block = True
            add("blocklist", 100, f"on the shared blocklist: {local['reason']}", local.get("evidence"))
        g = self.chain.guard_view(receiver)
        if g.get("known") is False:
            add("blocklist", 15, "could not read the guard contract's blocklist (unknown)")
        else:
            if g.get("blocked"):
                hard_block = True
                b = g["blocked"]
                add("blocklist", 100, f"blocked on chain by {b['added_by']}: {b['reason']}", b.get("evidence"))
            reps = g.get("reports") or []
            if reps and not g.get("blocked"):
                pts = min(45, 15 * len(reps))
                add("reports", pts, f"{len(reps)} report(s) from other accounts: " + "; ".join(f"{r['reporter']}: {r['reason']}" for r in reps[:3]),
                    [r["evidence"] for r in reps[:3]])
        trusted = receiver in self.trusted or bool(g.get("allowlisted"))

        # 2. does it exist, how old, how active
        acct = self.chain.account(receiver)
        hist = self.chain.history(receiver)
        now = self.chain.now_ns()
        if acct.get("known") is False:
            add("account_exists", 20, "could not look the account up (unknown)")
        elif not acct.get("exists"):
            if re.fullmatch(r"[0-9a-f]{64}", receiver):
                add("account_exists", 20, "implicit account that does not exist yet (the first payment would create it)")
            else:
                add("account_exists", 35, "account does not exist: a payment here would not reach anyone you know")
        if acct.get("exists"):
            if hist.get("known") is False:
                add("age", 20, "could not read the account's history (unknown)")
            else:
                first = hist.get("first_tx_ns")
                if first is None:
                    add("age", 20, "no transactions found for this account")
                else:
                    age = now - first
                    txt = "first seen " + ago(age)
                    if age < HOUR:
                        add("age", 25, "brand new account, " + txt)
                    elif age < DAY:
                        add("age", 15, "very new account, " + txt)
                    elif age < 7 * DAY:
                        add("age", 5, "young account, " + txt)
                n = hist.get("tx_count") or 0
                if n < 3:
                    add("activity", 10, f"almost no activity ({n} transactions)")
                elif n >= 20:
                    add("activity", -5, f"established activity ({n} transactions)")
                last = hist.get("last_tx_ns")
                if last and now - last > 180 * DAY:
                    add("activity", 10, f"dormant: last activity {ago(now - last)}")

            # 3. contract or person, and did the code change
            code = acct.get("code_hash")
            if code:
                add("contract", 15, "receiver is a smart contract, not a person's account")
                pinned = self.store.pins().get(receiver)
                if pinned and pinned != code:
                    add("contract", 50, "contract code CHANGED since you last checked it", f"pinned {pinned[:10]}.. now {code[:10]}..")
                elif not pinned:
                    add("contract", 0, "first time seeing this code (hash will be pinned if you pay)", code[:10] + "..")
                dep = hist.get("last_deploy_ns")
                if dep and now - dep < DAY:
                    add("contract", 40, f"code deployed {ago(now - dep)}")
                elif dep and now - dep < 7 * DAY:
                    add("contract", 25, f"code deployed {ago(now - dep)}")

        # 4. prior interactions
        prior = self.store.payments(receiver)
        if len(prior) >= 3:
            add("prior_payments", -30, f"{len(prior)} earlier payments from this agent")
        elif prior:
            add("prior_payments", -20, f"{len(prior)} earlier payment from this agent", prior[-1].get("tx"))
        else:
            add("prior_payments", 10, "this agent has never paid it before")

        # 5. trusted by the owner / lookalike of something trusted
        if trusted:
            add("allowlist", -40, "on the owner's allowlist")
        else:
            norm = receiver.translate(_LOOK)
            for t in sorted(self.trusted):
                if t == receiver:
                    continue
                if t.translate(_LOOK) == norm:
                    add("lookalike", 80, f"looks like trusted account {t} but is a different account", t)
                    break
                if len(t) > 6 and edit_distance(t, receiver) <= 2:
                    add("lookalike", 40, f"one or two letters away from trusted account {t}", t)
                    break

        # 6. scam posts that push this address
        it = self.intel.get(receiver)
        if it:
            pts = 60 if it["max_score"] >= 60 else 30
            add("scam_posts", pts, f"named in {len(it['posts'])} flagged post(s): {', '.join(it['categories'])}", it["posts"][:3])

        # 7. who told the agent to pay?
        if instruction_text:
            sc = scanner.scan_post(instruction_text)
            if "agent_hijack" in sc["categories"] or sc["verdict"] == "scam":
                add("instruction_source", 40, "the text that asked for this payment is a flagged post (" + ", ".join(sc["categories"]) + "): "
                    "a payment ordered by untrusted text, not by the owner", None)
                self._force_warn = True  # never a silent allow

        return self._result(receiver, reasons, hard_block)

    def pin_if_contract(self, receiver):
        """After a payment that was allowed, remember the receiver's code hash so a later change is noticed."""
        code = self.chain.account(receiver).get("code_hash")
        if code and receiver not in self.store.pins():
            self.store.pin(receiver, code)

    def _result(self, receiver, reasons, hard_block):
        score = max(0, min(100, sum(r["points"] for r in reasons)))
        if hard_block or score >= BLOCK_AT:
            verdict = "block"
        elif score >= WARN_AT or getattr(self, "_force_warn", False):
            verdict = "warn"
        else:
            verdict = "allow"
        return {"receiver": receiver, "verdict": verdict, "risk": 100 if hard_block else score, "reasons": reasons, "source": getattr(self.chain, "label", "")}

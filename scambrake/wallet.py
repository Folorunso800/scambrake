"""The agent-side wrapper (GuardedWallet) and the two places it can pay from.

GuardedWallet.pay():  ask the checker -> block: refuse, sign nothing | warn: ask a human | allow: sign.
Backends:
  OnChainBackend  signs `pay` with the agent's function-call key and sends it to the guard contract on testnet.
  PaperBackend    no network, no key. Mirrors the contract's rules so the demo runs offline. It says 'PAPER'."""
import json
import re
import sys
import time

from . import nearlib

YOCTO = nearlib.NEAR


class Log:
    """Prints a readable log and (optionally) keeps every event as JSON lines."""
    def __init__(self, path=None, out=None):
        self.out = out
        self.f = open(path, "w") if path else None

    def say(self, text, **event):
        print(text, file=self.out or sys.stdout, flush=True)
        if self.f:
            self.f.write(json.dumps({"t": time.strftime("%H:%M:%S"), "text": text, **event}) + "\n")
            self.f.flush()


def short_error(res_or_text):
    """Pull the contract's own refusal text out of a failed NEAR transaction."""
    text = res_or_text if isinstance(res_or_text, str) else json.dumps(res_or_text)
    m = re.search(r"(REFUSED_[A-Z_]+:[^\"\\]*|only the agent key[^\"\\]*|owner only)", text)
    return (m.group(1).strip() if m else text[:300])


class OnChainBackend:
    name = "NEAR testnet"

    def __init__(self, rpc, guard, agent_secret):
        self.rpc, self.guard, self.secret = rpc, guard, agent_secret

    def pay(self, receiver, amount_near, memo=""):
        args = json.dumps({"receiver": receiver, "amount": str(int(round(amount_near * 10**6)) * 10**18), "memo": memo}).encode()
        try:
            res = self.rpc.send(self.guard, self.secret, self.guard, [nearlib.a_call("pay", args, 30 * nearlib.TGAS)])
        except nearlib.RpcError as e:
            return {"ok": False, "error": str(e)[:300], "tx": None}
        fail = nearlib.tx_failure(res)
        link = nearlib.EXPLORER_TX + res["tx_hash"]
        return {"ok": fail is None, "error": short_error(fail) if fail else None, "tx": res["tx_hash"], "link": link}


class PaperBackend:
    """Same rules as the guard contract, kept in memory. For offline runs. Nothing is sent anywhere."""
    name = "PAPER (offline mirror of the guard contract)"

    def __init__(self, policy, allowlist, blocklist):
        self.per_tx = int(policy["per_tx_cap"]) / YOCTO
        self.daily = int(policy["daily_cap"]) / YOCTO
        self.unlisted = int(policy["unlisted_per_tx_cap"]) / YOCTO
        self.allow, self.block = set(allowlist), blocklist
        self.spent, self.n = 0.0, 0

    def pay(self, receiver, amount_near, memo=""):
        def no(msg):
            return {"ok": False, "error": msg, "tx": None}
        if receiver in self.block:
            return no(f"REFUSED_BLOCKLIST: {receiver} is blocked. reason: {self.block[receiver]['reason']}")
        if amount_near > self.per_tx:
            return no(f"REFUSED_PER_TX_CAP: {amount_near} NEAR > {self.per_tx} NEAR")
        if receiver not in self.allow and amount_near > self.unlisted:
            return no(f"REFUSED_NOT_ALLOWLISTED: {receiver} is not allowlisted, cap for unlisted receivers is {self.unlisted} NEAR")
        if self.spent + amount_near > self.daily + 1e-12:
            return no(f"REFUSED_DAILY_CAP: {self.spent} paid today + {amount_near} > {self.daily} NEAR")
        self.spent += amount_near
        self.n += 1
        return {"ok": True, "error": None, "tx": f"paper-{self.n}", "link": None}


class GuardedWallet:
    def __init__(self, checker, backend, store, log, on_warn="deny"):
        """on_warn: 'deny' (default, safe when nobody is watching) | 'approve' | 'ask' (prompt on the terminal)"""
        self.checker, self.backend, self.store, self.log, self.on_warn = checker, backend, store, log, on_warn

    def _ask_human(self, verdict, amount):
        if self.on_warn == "approve":
            self.log.say("  [human] approves (--on-warn approve)", event="human", answer="yes")
            return True
        if self.on_warn == "ask" and sys.stdin.isatty():
            ans = input(f"  [human] allow paying {amount} NEAR to {verdict['receiver']}? type yes to allow: ").strip().lower()
            return ans in ("y", "yes")
        self.log.say("  [human] no approval given -> treated as NO", event="human", answer="no")
        return False

    def pay(self, receiver, amount_near, memo="", instruction_text=None):
        self.log.say(f"[agent ] wants to pay {amount_near} NEAR to {receiver}  ({memo})")
        v = self.checker.check(receiver, amount_near, instruction_text)
        self.log.say(f"[check ] {v['verdict'].upper()}  risk={v['risk']}/100")
        for r in v["reasons"]:
            if r["points"] != 0 or r["signal"] in ("contract",):
                ev = f"  [evidence: {r['evidence']}]" if r.get("evidence") else ""
                self.log.say(f"           {r['points']:+4d}  {r['signal']}: {r['text']}{ev}")
        out = {"receiver": receiver, "amount": amount_near, "verdict": v["verdict"], "risk": v["risk"], "signed": False}
        if v["verdict"] == "block":
            self.log.say("[wallet] REFUSED. The wrapper did not sign anything, no transaction was created.", event="refused", **out)
            out["result"] = "refused_by_checker"
            return out
        if v["verdict"] == "warn" and not self._ask_human(v, amount_near):
            self.log.say("[wallet] NOT SENT. A human did not approve this warning.", event="held", **out)
            out["result"] = "held_for_human"
            return out
        self.log.say(f"[wallet] signing `pay` with the function-call key ({self.backend.name})")
        r = self.backend.pay(receiver, amount_near, memo)
        out["signed"] = True
        out.update(tx=r.get("tx"), link=r.get("link"))
        if r["ok"]:
            self.store.add_payment(receiver, amount_near, r.get("tx"), memo)
            self.checker.pin_if_contract(receiver)
            link = f"  {r['link']}" if r.get("link") else ""
            self.log.say(f"[chain ] PAID {amount_near} NEAR to {receiver}  tx={r['tx']}{link}", event="paid", **out)
            out["result"] = "paid"
        else:
            self.log.say(f"[chain ] the guard contract REFUSED: {r['error']}", event="contract_refused", **out)
            out["result"] = "refused_by_contract"
        return out

    def bypass(self, receiver, amount_near, memo=""):
        """What a compromised agent would do: skip the checker and call the guard directly with its key.
        The contract's own rules still apply."""
        self.log.say(f"[attack] agent SKIPS the checker and calls the guard contract directly: pay {amount_near} NEAR -> {receiver}")
        r = self.backend.pay(receiver, amount_near, memo)
        if r["ok"]:
            self.log.say(f"[chain ] went through (within the contract's rules)  tx={r['tx']} {r.get('link') or ''}", event="bypass_ok")
        else:
            link = f"  {nearlib.EXPLORER_TX}{r['tx']}" if r.get("tx") else ""
            self.log.say(f"[chain ] the guard contract REFUSED: {r['error']}{link}", event="bypass_refused", tx=r.get("tx"))
        return r

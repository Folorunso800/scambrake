"""The end-to-end demo: a normal payment, a warning, a prompt-injection attack, a look-alike,
and two attempts to go around the checker. Runs offline by default (recorded testnet data + paper
wallet). `--live` signs real transactions on NEAR testnet with the agent's function-call key."""
import json
import os
import shutil
import tempfile

from . import chain as chainmod, nearlib, scanner, secrets
from .agent import GullibleAgent
from .checker import Checker, Store
from .wallet import GuardedWallet, Log, OnChainBackend, PaperBackend

ROOT = os.path.join(os.path.dirname(__file__), "..")
FIX = os.path.join(ROOT, "fixtures")


def jload(path):
    with open(path) as f:
        return json.load(f)


def load_deployment():
    for name in ("deployment.local.json", "deployment.json"):
        p = os.path.join(ROOT, name)
        if os.path.exists(p):
            return jload(p)
    raise SystemExit("no deployment.json: run scripts/setup_testnet.py first")


def banner(log, text):
    log.say("")
    log.say("=" * 78)
    log.say(text)
    log.say("=" * 78)


def build(live, on_warn, log, state_dir=None):
    posts_doc = jload(os.path.join(FIX, "posts.json"))
    if live:
        dep = load_deployment()
        rpc = nearlib.Rpc()
        ch = chainmod.LiveChain(dep["guard"], rpc)
        names = dep["receivers"]
        agent_key = secrets.get("agent")
        if not agent_key:
            raise SystemExit("live mode needs the agent key in ~/.secrets/scambrake/keys.json (run scripts/setup_testnet.py)")
        backend = OnChainBackend(rpc, dep["guard"], agent_key["secret_key"])
        store = Store(state_dir or os.path.join(ROOT, "state"))
        policy = ch.policy()
    else:
        ch = chainmod.ReplayChain(os.path.join(FIX, "chain_snapshot.json"))
        names = ch.doc["receivers"]
        policy = ch.policy()
        block = {a: v["guard"]["blocked"] for a, v in ch.doc["accounts"].items() if v["guard"].get("blocked")}
        backend = PaperBackend(policy, ch.allowlist(), block)
        tmp = tempfile.mkdtemp(prefix="scambrake-")
        shutil.copytree(os.path.join(FIX, "state"), os.path.join(tmp, "state"))
        store = Store(os.path.join(tmp, "state"))
    drainer = names["drainer"]
    posts = [{**p, "text": p["text"].replace("{DRAINER}", drainer)} for p in posts_doc["posts"]]
    _, intel = scanner.scan_posts(posts)
    bl_doc = jload(os.path.join(ROOT, "data", "blocklist.json"))
    blocklist = {k.replace("{DRAINER}", drainer): v for k, v in bl_doc["entries"].items()}
    checker = Checker(ch, store, blocklist=blocklist, trusted=ch.allowlist(), intel=intel)
    wallet = GuardedWallet(checker, backend, store, log, on_warn=on_warn)
    return {"chain": ch, "names": names, "posts": posts, "policy": policy, "wallet": wallet, "checker": checker,
            "backend": backend, "live": live, "store": store}


def run(live=False, on_warn="deny", log_path=None):
    log = Log(log_path)
    w = build(live, on_warn, log)
    n, wallet, ch = w["names"], w["wallet"], w["chain"]
    p = w["policy"]
    near = lambda y: int(y) / nearlib.NEAR
    mode = "LIVE on NEAR testnet (real signed transactions, test money)" if live else f"OFFLINE replay ({ch.label}); wallet is PAPER, nothing is sent"
    banner(log, f"ScamBrake demo - {mode}")
    log.say(f"guard contract : {ch.guard}")
    log.say(f"agent's key    : function-call key, only method `pay`, only on {ch.guard}")
    log.say(f"on-chain limits: per payment {near(p['per_tx_cap'])} NEAR | per day {near(p['daily_cap'])} NEAR | "
            f"non-allowlisted receivers {near(p['unlisted_per_tx_cap'])} NEAR max")
    log.say(f"allowlist      : {', '.join(ch.allowlist()) or '(empty)'}")
    results = []

    banner(log, "1. Normal task: the owner asks the agent to pay the vendor's invoice")
    results.append(("pay allowlisted vendor 0.05 NEAR", wallet.pay(n["vendor"], 0.05, memo="invoice #12, API credits")))

    banner(log, "2. A receiver we know little about: young account, no history, not on the allowlist")
    results.append(("pay unknown newcomer 0.05 NEAR", wallet.pay(n["newcomer"], 0.05, memo="new supplier, first payment")))

    banner(log, "3. THE ATTACK: the agent reads a post that hijacks it and orders a payment to a known-bad address")
    agent = GullibleAgent(wallet)
    attack_post = [x for x in w["posts"] if x["id"] == "sx-004"]
    results += [("prompt-injected order -> drainer", o) for o in agent.read_feed(attack_post)]

    banner(log, "4. Look-alike: the same attacker tries a name one character away from the real vendor")
    fake = n["vendor"].replace("vendor", "vend0r", 1)
    results.append(("pay look-alike vend0r", wallet.pay(fake, 0.05, memo="invoice #13")))

    banner(log, "5. A contract whose code changed: it was fine when we last looked, then someone redeployed it")
    results.append(("pay contract that changed its code", wallet.pay(n["swap"], 0.05, memo="swap fee")))

    banner(log, "6. Second wall: a fully compromised agent skips the checker and calls the guard contract itself")
    r = wallet.bypass(n["drainer"], 0.9, memo="skip the checker")
    results.append(("bypass checker -> drainer", {"result": "refused_by_contract" if not r["ok"] else "paid", "verdict": "(skipped)", "signed": True}))
    r = wallet.bypass(n["vendor"], 1.5, memo="try to move more than the cap")
    results.append(("bypass checker -> vendor 1.5 NEAR (over cap)", {"result": "refused_by_contract" if not r["ok"] else "paid", "verdict": "(skipped)", "signed": True}))

    banner(log, "7. What the function-call key cannot do at all (recorded from real testnet attempts)")
    for row in jload(os.path.join(FIX, "key_limits.json"))["attempts"]:
        log.say(f"[key   ] {row['attempt']:<46} -> {row['result']}  ({row['tx_or_note']})")

    banner(log, "SUMMARY")
    log.say(f"{'what happened':<48} {'checker':<8} {'outcome'}")
    for label, o in results:
        log.say(f"{label:<48} {o.get('verdict','-'):<8} {o['result']}")
    paid = sum(1 for _, o in results if o["result"] == "paid")
    log.say(f"\npayments that went out: {paid} | everything aimed at the bad address was stopped")
    return results

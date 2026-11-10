#!/usr/bin/env python3
"""Record what the live testnet says about the demo receivers into fixtures/chain_snapshot.json,
so `./demo.sh` can replay it offline. Also writes fixtures/state (the agent's earlier payment and the pinned code hash)."""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scambrake import chain, nearlib as n  # noqa: E402
from scambrake.demo import load_deployment, ROOT  # noqa: E402


def main():
    dep = load_deployment()
    rpc = n.Rpc()
    ch = chain.LiveChain(dep["guard"], rpc)
    names = dep["receivers"]
    fake = names["vendor"].replace("vendor", "vend0r", 1)
    accounts = list(names.values()) + [fake]
    extra = {"receivers": names, "owner": dep["owner"], "policy": ch.policy(), "allowlist": ch.allowlist(),
             "guard_code_hash": rpc.view_account(dep["guard"])["code_hash"]}
    doc = chain.record(ch, accounts, os.path.join(ROOT, "fixtures", "chain_snapshot.json"), extra)
    for a, s in doc["accounts"].items():
        print(a, "exists" if s["account"].get("exists") else "missing", s["history"].get("tx_count"), "blocked" if s["guard"].get("blocked") else "")
    # state for the replay: only the earlier seed payment and the pinned (old) contract hash
    state = os.path.join(ROOT, "fixtures", "state")
    os.makedirs(state, exist_ok=True)
    seed = dep["txs"].get("seed_payment_vendor")
    with open(os.path.join(state, "ledger.jsonl"), "w") as f:
        f.write(json.dumps({"receiver": names["vendor"], "amount_near": 0.02, "tx": seed, "note": "seed: earlier invoice #11", "at": "recorded"}) + "\n")
    shutil.copy(os.path.join(ROOT, "state", "pins.json"), os.path.join(state, "pins.json"))


if __name__ == "__main__":
    main()

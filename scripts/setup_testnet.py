#!/usr/bin/env python3
"""One-time TESTNET setup. Creates fresh testnet accounts and keys, deploys the guard contract,
and gives the agent a function-call key limited to `pay`. Testnet only, test money only.

Secrets (keys) go to ~/.secrets/scambrake/keys.json. Public facts (account names, public keys,
transaction hashes) go to deployment.json, which is safe to commit.

Run:  python3 scripts/setup_testnet.py [--owner NAME]
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scambrake import nearlib as n, secrets  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
DEPLOY = os.path.join(ROOT, "deployment.json")
WASM = os.path.join(ROOT, "contract", "res", "scambrake_guard.wasm")
FAUCET = "https://helper.nearprotocol.com/account"
GAS = 100 * n.TGAS


def log(msg):
    print(msg, flush=True)


def dep_load():
    return json.load(open(DEPLOY)) if os.path.exists(DEPLOY) else {"txs": {}}


def dep_save(d):
    json.dump(d, open(DEPLOY, "w"), indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", default="scambrake-owner.testnet")
    args = ap.parse_args()
    rpc = n.Rpc()
    keys = secrets.load()
    dep = dep_load()

    owner = args.owner
    # 1. owner account via the testnet faucet (free test NEAR)
    if "owner" not in keys:
        if rpc.view_account(owner) is not None:
            sys.exit(f"{owner} already exists on testnet; pick another with --owner")
        kp = n.new_keypair()
        req = urllib.request.Request(FAUCET, data=json.dumps({"newAccountId": owner, "newAccountPublicKey": kp["public_key"]}).encode(),
                                     headers={"content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                resp = json.load(r)
        except urllib.error.HTTPError as e:
            sys.exit(f"faucet refused: {e.code} {e.read()[:200]!r}")
        keys["owner"] = {"account": owner, **kp}
        secrets.save(keys)
        h = (resp.get("final_execution_outcome") or resp).get("transaction_outcome", {}).get("id")
        dep["txs"]["create_owner_via_faucet"] = h
        log(f"created {owner} through the testnet faucet")
        time.sleep(3)
    ok = keys["owner"]
    owner = ok["account"]
    bal = int(rpc.view_account(owner)["amount"]) / n.NEAR
    log(f"owner balance: {bal:.2f} NEAR (testnet)")

    guard = f"guard.{owner}"
    dep.update({"network": "testnet", "owner": owner, "guard": guard})

    def send(label, signer, key, receiver, actions):
        res = rpc.send(signer["account"], key["secret_key"], receiver, actions)
        fail = n.tx_failure(res)
        dep["txs"][label] = res["tx_hash"]
        dep_save(dep)
        if fail:
            sys.exit(f"{label} FAILED: {fail}")
        log(f"{label}: {n.EXPLORER_TX}{res['tx_hash']}")
        return res

    # 2. guard account + contract + init, one transaction signed by the owner
    if "guard_admin" not in keys:
        gk = n.new_keypair()
        keys["guard_admin"] = {"account": guard, **gk}
        secrets.save(keys)
    ga = keys["guard_admin"]
    if rpc.view_account(guard) is None:
        code = open(WASM, "rb").read()
        init = json.dumps({"owner": owner, "per_tx_cap": str(1 * n.NEAR), "daily_cap": str(2 * n.NEAR),
                           "unlisted_per_tx_cap": str(n.NEAR // 10)}).encode()
        send("create_deploy_init_guard", ok, ok, guard, [
            n.a_create_account(), n.a_transfer(4 * n.NEAR), n.a_add_full_key(ga["public_key"]),
            n.a_deploy(code), n.a_call("new", init, 50 * n.TGAS)])

    # 3. the agent's function-call key: only `pay`, only on the guard, small gas allowance
    if "agent" not in keys:
        ak = n.new_keypair()
        keys["agent"] = {"account": guard, **ak}
        secrets.save(keys)
    ag = keys["agent"]
    if rpc.access_key(guard, ag["public_key"]) is None:
        send("add_agent_function_call_key", ga, ga, guard,
             [n.a_add_fn_key(ag["public_key"], guard, ["pay"], allowance=n.NEAR // 4)])
    dep["agent_public_key"] = ag["public_key"]

    # 4. demo receivers, subaccounts of the owner (owner's key controls them)
    for name in ("vendor", "newcomer", "drainer"):
        acct = f"{name}.{owner}"
        if rpc.view_account(acct) is None:
            send(f"create_{name}", ok, ok, acct, [n.a_create_account(), n.a_transfer(n.NEAR // 2), n.a_add_full_key(ok["public_key"])])
        dep.setdefault("receivers", {})[name] = acct
    dep_save(dep)
    log("setup done")


if __name__ == "__main__":
    main()

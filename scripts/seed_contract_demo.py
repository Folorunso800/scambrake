#!/usr/bin/env python3
"""Demo receiver that is a contract whose code changed (testnet). Creates swap.<owner>, deploys code v1,
pins v1's hash in state/pins.json (as if the agent checked it earlier), then deploys v2 (v1 plus a harmless
custom section, so the hash changes). The checker should then say: code CHANGED, deployed recently."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scambrake import nearlib as n, secrets  # noqa: E402
from scambrake.checker import Store  # noqa: E402
from scambrake.demo import load_deployment, ROOT  # noqa: E402


def leb(x):
    out = b""
    while True:
        b = x & 0x7F
        x >>= 7
        out += bytes([b | (0x80 if x else 0)])
        if not x:
            return out


def main():
    dep = load_deployment()
    owner = secrets.get("owner")
    rpc = n.Rpc()
    swap = f"swap.{owner['account']}"
    v1 = b"\x00asm\x01\x00\x00\x00"  # the smallest valid wasm module: an empty contract (keeps storage cost tiny)
    name = b"scambrake-demo-upgrade"
    payload = b"v2: different bytes, different hash"
    body = leb(len(name)) + name + payload
    v2 = v1 + b"\x00" + leb(len(body)) + body

    def send(label, actions, receiver=swap, signer=None):
        res = rpc.send(signer or owner["account"], owner["secret_key"], receiver, actions)
        fail = n.tx_failure(res)
        if fail:
            sys.exit(f"{label}: {fail}")
        dep.setdefault("txs", {})[label] = res["tx_hash"]
        print(f"{label}: {n.EXPLORER_TX}{res['tx_hash']}")

    acct = rpc.view_account(swap)
    if acct is None:
        send("create_swap_deploy_v1", [n.a_create_account(), n.a_transfer(n.NEAR // 2), n.a_add_full_key(owner["public_key"]), n.a_deploy(v1)])
        v1_hash = rpc.view_account(swap)["code_hash"]
        Store(os.path.join(ROOT, "state")).pin(swap, v1_hash)
        print("pinned v1 hash", v1_hash)
        acct = rpc.view_account(swap)
    if acct["code_hash"] == Store(os.path.join(ROOT, "state")).pins().get(swap):
        send("redeploy_swap_v2", [n.a_deploy(v2)], signer=swap)
    dep.setdefault("receivers", {})["swap"] = swap
    json.dump(dep, open(os.path.join(ROOT, "deployment.local.json"), "w"), indent=2)


if __name__ == "__main__":
    main()

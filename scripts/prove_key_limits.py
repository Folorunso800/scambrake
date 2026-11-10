#!/usr/bin/env python3
"""Try, on real testnet, the things a function-call key must NOT be able to do, and record what NEAR says.
Writes fixtures/key_limits.json (used by the offline demo). Nothing here can move money: every attempt is rejected."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scambrake import nearlib as n, secrets  # noqa: E402
from scambrake.demo import load_deployment, ROOT  # noqa: E402


def brief(text):
    t = str(text)
    for key in ("RequiresFullAccess", "ReceiverMismatch", "MethodNameMismatch", "DepositWithFunctionCall", "NotEnoughAllowance"):
        if key in t:
            return key
    return t[:140]


def main():
    dep = load_deployment()
    ag = secrets.get("agent")
    guard, drainer = dep["guard"], dep["receivers"]["drainer"]
    rpc = n.Rpc()
    other = n.new_keypair()["public_key"]
    tries = [
        ("transfer 0.1 NEAR to another account", drainer, [n.a_transfer(n.NEAR // 10)]),
        ("add a new full-access key to the guard", guard, [n.a_add_full_key(other)]),
        ("call a different method (`set_limits`)", guard, [n.a_call("set_limits", b'{"per_tx_cap":"1","daily_cap":"1","unlisted_per_tx_cap":"1"}', 10 * n.TGAS)]),
        ("call `pay` and attach a deposit", guard, [n.a_call("pay", b"{}", 10 * n.TGAS, 1)]),
        ("call `pay` on a different contract", drainer, [n.a_call("pay", b"{}", 10 * n.TGAS)]),
    ]
    rows = []
    for label, receiver, actions in tries:
        try:
            res = rpc.send(guard, ag["secret_key"], receiver, actions)
            rows.append({"attempt": label, "result": "UNEXPECTEDLY ACCEPTED", "tx_or_note": res["tx_hash"]})
            print("!! accepted:", label)
        except n.RpcError as e:
            rows.append({"attempt": label, "result": "REJECTED by NEAR: " + brief(e), "tx_or_note": "rejected before inclusion, no tx"})
            print(label, "->", brief(e))
    json.dump({"label": "REAL testnet responses to forbidden actions signed with the agent's function-call key",
               "guard": guard, "attempts": rows}, open(os.path.join(ROOT, "fixtures", "key_limits.json"), "w"), indent=1)


if __name__ == "__main__":
    main()

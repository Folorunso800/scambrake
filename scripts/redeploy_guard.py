#!/usr/bin/env python3
"""Re-deploy contract/res/scambrake_guard.wasm to the guard account (needs the guard's full-access key,
which is kept in ~/.secrets/scambrake/). State is kept."""
import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scambrake import nearlib as n, secrets  # noqa: E402
from scambrake.demo import load_deployment, ROOT  # noqa: E402

code = open(os.path.join(ROOT, "contract", "res", "scambrake_guard.wasm"), "rb").read()
dep = load_deployment()
ga = secrets.get("guard_admin")
res = n.Rpc().send(dep["guard"], ga["secret_key"], dep["guard"], [n.a_deploy(code)])
fail = n.tx_failure(res)
print("FAILED " + fail if fail else f"deployed sha256={hashlib.sha256(code).hexdigest()[:16]}.. tx {n.EXPLORER_TX}{res['tx_hash']}")

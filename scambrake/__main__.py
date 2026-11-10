import argparse
import json
import os
import sys

from . import chain as chainmod, demo, scanner
from .checker import Checker, Store


def main(argv=None):
    ap = argparse.ArgumentParser(prog="scambrake", description="Counterparty check and locked wallet for AI agents that pay on NEAR")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="run the attack demo")
    d.add_argument("--live", action="store_true", help="sign real testnet transactions (needs the agent key)")
    d.add_argument("--on-warn", choices=["deny", "approve", "ask"], default="deny")
    d.add_argument("--log", help="also write the log as JSON lines")
    s = sub.add_parser("scan", help="scan posts for scam patterns")
    s.add_argument("--posts", default=os.path.join(demo.FIX, "posts.json"))
    s.add_argument("--x-query", help="read live posts from the X API instead (needs X_BEARER_TOKEN)")
    c = sub.add_parser("check", help="ask the checker about one receiver")
    c.add_argument("account")
    c.add_argument("--amount", type=float)
    c.add_argument("--live", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "demo":
        demo.run(live=a.live, on_warn=a.on_warn, log_path=a.log)
    elif a.cmd == "scan":
        if a.x_query:
            from . import x_source
            doc = {"label": f"LIVE X posts for: {a.x_query}", "posts": x_source.live_posts(a.x_query)}
        else:
            doc = demo.jload(a.posts)
        res, intel = scanner.scan_posts([{**p, "text": p["text"].replace("{DRAINER}", "drainer.example.testnet")} for p in doc["posts"]])
        print(doc.get("label", ""))
        for r in res:
            print(f"{r['post']['id']:<7} {r['verdict']:<10} score={r['score']:<3} {', '.join(r['categories']) or '-'}")
        print(f"\naddresses pushed by flagged posts: {', '.join(intel) or '-'}")
    elif a.cmd == "check":
        log = demo.Log()
        w = demo.build(a.live, "deny", log)
        v = w["checker"].check(a.account, a.amount)
        print(json.dumps(v, indent=2))


if __name__ == "__main__":
    main()

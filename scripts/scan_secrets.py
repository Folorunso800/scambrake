#!/usr/bin/env python3
"""Secret scan to run before every push. Looks in the working tree AND git history for
 (a) any value stored under ~/.secrets (exact match), (b) NEAR secret-key shapes, (c) common token shapes.
Prints file names and counts only, never the secret itself. Exit code 1 if anything is found."""
import glob
import json
import os
import re
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PLAIN_URL = re.compile(r"https?://[\w.\-]+(/[\w.\-/#]*)?")  # a bare public link (no query string, no credentials) is not a secret
patterns = {
    "near_secret_key": re.compile(r"ed25519:[1-9A-HJ-NP-Za-km-z]{80,92}"),
    "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    "api_key_google": re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    "sk_key": re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    "private_key_block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "bearer": re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{30,}"),
}


def secret_values():
    vals = set()
    for path in glob.glob(os.path.expanduser("~/.secrets/**/*"), recursive=True):
        if not os.path.isfile(path):
            continue
        try:
            text = open(path, errors="ignore").read()
        except OSError:
            continue
        if path.endswith(".json"):
            try:
                def walk(o, key=""):
                    if isinstance(o, dict):
                        for k, v in o.items():
                            walk(v, k)
                    elif isinstance(o, list):
                        for v in o:
                            walk(v, key)
                    elif isinstance(o, str) and len(o) >= 24 and key not in ("account", "public_key") and not PLAIN_URL.fullmatch(o):
                        vals.add(o)
                walk(json.loads(text))
                continue
            except ValueError:
                pass
        for line in text.splitlines():
            if "=" in line:
                v = line.split("=", 1)[1].strip().strip("'\"")
                if len(v) >= 12:
                    vals.add(v)
    return vals


def main():
    vals = secret_values()
    hits = []
    files = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    for f in files:
        p = os.path.join(ROOT, f)
        if not os.path.isfile(p) or os.path.getsize(p) > 5_000_000:
            continue
        data = open(p, "rb").read().decode("utf-8", "ignore")
        for v in vals:
            if v in data:
                hits.append((f, "value from ~/.secrets"))
        for name, rx in patterns.items():
            if rx.search(data):
                hits.append((f, name))
    # git history
    if os.path.isdir(os.path.join(ROOT, ".git")) and subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True).returncode == 0:
        hist = subprocess.run(["git", "log", "-p", "--all", "--no-color"], cwd=ROOT, capture_output=True, text=True, errors="ignore").stdout
        for v in vals:
            if v in hist:
                hits.append(("(git history)", "value from ~/.secrets"))
        for name, rx in patterns.items():
            if rx.search(hist):
                hits.append(("(git history)", name))
    print(f"checked {len(files)} files + history against {len(vals)} stored secret values and {len(patterns)} patterns")
    if hits:
        for f, why in sorted(set(hits)):
            print(f"FOUND  {f}  ({why})")
        sys.exit(1)
    print("CLEAN: no secrets found")


if __name__ == "__main__":
    main()

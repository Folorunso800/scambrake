"""Where the testnet keys live: ~/.secrets/scambrake/keys.json (never inside the repo).
Override the folder with SCAMBRAKE_SECRETS. Keys are testnet-only."""
import json
import os
import stat

DIR = os.environ.get("SCAMBRAKE_SECRETS") or os.path.expanduser("~/.secrets/scambrake")
PATH = os.path.join(DIR, "keys.json")


def load():
    if not os.path.exists(PATH):
        return {}
    with open(PATH) as f:
        return json.load(f)


def save(data):
    os.makedirs(DIR, mode=0o700, exist_ok=True)
    tmp = PATH + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, PATH)
    os.chmod(PATH, stat.S_IRUSR | stat.S_IWUSR)


def get(role):
    """role -> {'account': ..., 'secret_key': ..., 'public_key': ...} or None"""
    return load().get(role)

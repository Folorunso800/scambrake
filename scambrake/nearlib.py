"""A small NEAR client with no dependencies: JSON-RPC, borsh, transaction signing.
Only what ScamBrake needs: view calls, access keys, and signing CreateAccount, Transfer,
DeployContract, FunctionCall, AddKey and DeleteKey transactions."""
import base64
import hashlib
import json
import os
import struct
import time
import urllib.error
import urllib.request

from . import ed25519

RPC_TESTNET = os.environ.get("SCAMBRAKE_RPC", "https://rpc.testnet.near.org")
EXPLORER_TX = "https://testnet.nearblocks.io/txns/"
EXPLORER_ACCOUNT = "https://testnet.nearblocks.io/address/"
NEAR = 10**24
TGAS = 10**12

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    out = ""
    while n > 0:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + out


def b58decode(s: str) -> bytes:
    n = 0
    for c in s:
        n = n * 58 + _B58.index(c)
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\0" * (len(s) - len(s.lstrip("1"))) + body


def parse_secret(sk: str):
    """'ed25519:<base58 of 64 bytes seed+pub>' -> (seed, pub)"""
    assert sk.startswith("ed25519:"), "only ed25519 keys are supported"
    raw = b58decode(sk[8:])
    return raw[:32], raw[32:64]


def pub_str(pub: bytes) -> str:
    return "ed25519:" + b58encode(pub)


def new_keypair():
    seed = os.urandom(32)
    pub = ed25519.public_key(seed)
    return {"secret_key": "ed25519:" + b58encode(seed + pub), "public_key": pub_str(pub)}


def public_from_secret(sk: str) -> str:
    seed, pub = parse_secret(sk)
    return pub_str(pub)


# ------------------------------------------------------------------ borsh
def _u8(n): return struct.pack("<B", n)
def _u32(n): return struct.pack("<I", n)
def _u64(n): return struct.pack("<Q", n)
def _u128(n): return int(n).to_bytes(16, "little")
def _str(s): b = s.encode(); return _u32(len(b)) + b
def _bytes(b): return _u32(len(b)) + b
def _pk(pk: str): return _u8(0) + b58decode(pk[8:])


def a_create_account(): return _u8(0)
def a_deploy(code: bytes): return _u8(1) + _bytes(code)
def a_call(method, args: bytes, gas, deposit=0): return _u8(2) + _str(method) + _bytes(args) + _u64(gas) + _u128(deposit)
def a_transfer(yocto): return _u8(3) + _u128(yocto)
def a_add_full_key(pk): return _u8(5) + _pk(pk) + _u64(0) + _u8(1)
def a_delete_key(pk): return _u8(6) + _pk(pk)


def a_add_fn_key(pk, receiver, methods, allowance=None):
    allow = _u8(0) if allowance is None else _u8(1) + _u128(allowance)
    perm = _u8(0) + allow + _str(receiver) + _u32(len(methods)) + b"".join(_str(m) for m in methods)
    return _u8(5) + _pk(pk) + _u64(0) + perm


def build_tx(signer, pub, nonce, receiver, block_hash: bytes, actions):
    return (_str(signer) + _pk(pub) + _u64(nonce) + _str(receiver) + block_hash
            + _u32(len(actions)) + b"".join(actions))


def sign_tx(tx_bytes: bytes, secret_key: str):
    """-> (signed_tx_bytes, tx_hash_b58)"""
    seed, _ = parse_secret(secret_key)
    digest = hashlib.sha256(tx_bytes).digest()
    sig = ed25519.sign(seed, digest)
    return tx_bytes + _u8(0) + sig, b58encode(digest)


# ------------------------------------------------------------------ RPC
class RpcError(Exception):
    pass


class Rpc:
    def __init__(self, url=None, timeout=30):
        self.url = url or RPC_TESTNET
        self.timeout = timeout

    def call(self, method, params, retries=3):
        body = json.dumps({"jsonrpc": "2.0", "id": "sb", "method": method, "params": params}).encode()
        last = None
        for i in range(retries):
            try:
                req = urllib.request.Request(self.url, data=body, headers={"content-type": "application/json"})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    j = json.load(r)
                if "error" in j:
                    err = j["error"]
                    if isinstance(err, str):
                        raise RpcError(err)
                    raise RpcError(json.dumps({"cause": err.get("cause"), "data": err.get("data")})[:600])
                return j["result"]
            except RpcError:
                raise
            except (urllib.error.URLError, OSError, ValueError) as e:
                last = e
                time.sleep(1.5 * (i + 1))
        raise RpcError(f"network error: {last}")

    def view_account(self, account):
        """-> dict, or None if the account does not exist"""
        try:
            res = self.call("query", {"request_type": "view_account", "finality": "final", "account_id": account})
            return None if "error" in res else res
        except RpcError as e:
            if "does not exist" in str(e) or "UNKNOWN_ACCOUNT" in str(e):
                return None
            raise

    def view_call(self, account, method, args=None):
        res = self.call("query", {"request_type": "call_function", "finality": "final", "account_id": account,
                                  "method_name": method, "args_base64": base64.b64encode(json.dumps(args or {}).encode()).decode()})
        raw = bytes(res["result"])
        return json.loads(raw) if raw else None

    def access_key(self, account, pk):
        try:
            res = self.call("query", {"request_type": "view_access_key", "finality": "final", "account_id": account, "public_key": pk})
            return None if "error" in res else res
        except RpcError as e:
            if "does not exist" in str(e) or "UNKNOWN_ACCESS_KEY" in str(e):
                return None
            raise

    def list_keys(self, account):
        return self.call("query", {"request_type": "view_access_key_list", "finality": "final", "account_id": account})["keys"]

    def send(self, signer, secret_key, receiver, actions, wait="FINAL"):
        """Sign and send. Returns the final RPC result (even for failed receipts) plus 'tx_hash'.
        Raises RpcError if the RPC node itself rejects the transaction (for example a key that is not allowed)."""
        pub = public_from_secret(secret_key)
        ak = self.access_key(signer, pub)
        if ak is None:
            raise RpcError(f"key {pub} is not an access key of {signer}")
        tx = build_tx(signer, pub, ak["nonce"] + 1, receiver, b58decode(ak["block_hash"]), actions)
        signed, h = sign_tx(tx, secret_key)
        res = self.call("send_tx", {"signed_tx_base64": base64.b64encode(signed).decode(), "wait_until": wait}, retries=1)
        res["tx_hash"] = h
        return res


def tx_failure(res):
    """Return a short failure text for a send_tx result, or None if everything succeeded."""
    st = res.get("status", {})
    if "Failure" in st:
        return json.dumps(st["Failure"])[:500]
    for o in res.get("receipts_outcome", []):
        s = o["outcome"]["status"]
        if "Failure" in s:
            return json.dumps(s["Failure"])[:500]
    return None

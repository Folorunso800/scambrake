"""Minimal pure-Python Ed25519 (RFC 8032), so the project needs no third-party packages.
Slow (about 10-20 ms per signature) but fine for a handful of transactions.
Checked against the RFC 8032 test vectors in tests/test_nearlib.py."""
import hashlib

_p = 2**255 - 19
_q = 2**252 + 27742317777372353535851937790883648493


def _inv(x):
    return pow(x, _p - 2, _p)


_d = -121665 * _inv(121666) % _p
_I = pow(2, (_p - 1) // 4, _p)


def _xrecover(y):
    xx = (y * y - 1) * _inv(_d * y * y + 1)
    x = pow(xx, (_p + 3) // 8, _p)
    if (x * x - xx) % _p != 0:
        x = (x * _I) % _p
    if x % 2 != 0:
        x = _p - x
    return x


_By = 4 * _inv(5) % _p
_Bx = _xrecover(_By)
_B = (_Bx % _p, _By % _p, 1, (_Bx * _By) % _p)
_ZERO = (0, 1, 1, 0)


def _add(P, Q):
    A = (P[1] - P[0]) * (Q[1] - Q[0]) % _p
    B = (P[1] + P[0]) * (Q[1] + Q[0]) % _p
    C = 2 * P[3] * Q[3] * _d % _p
    D = 2 * P[2] * Q[2] % _p
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F % _p, G * H % _p, F * G % _p, E * H % _p)


def _mul(s, P):
    Q = _ZERO
    while s > 0:
        if s & 1:
            Q = _add(Q, P)
        P = _add(P, P)
        s >>= 1
    return Q


def _compress(P):
    zi = _inv(P[2])
    x, y = P[0] * zi % _p, P[1] * zi % _p
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _h(m):
    return hashlib.sha512(m).digest()


def _clamp(h):
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a


def public_key(seed: bytes) -> bytes:
    assert len(seed) == 32
    return _compress(_mul(_clamp(_h(seed)), _B))


def sign(seed: bytes, msg: bytes) -> bytes:
    h = _h(seed)
    a = _clamp(h)
    A = _compress(_mul(a, _B))
    r = int.from_bytes(_h(h[32:] + msg), "little") % _q
    R = _compress(_mul(r, _B))
    k = int.from_bytes(_h(R + A + msg), "little") % _q
    S = (r + k * a) % _q
    return R + int.to_bytes(S, 32, "little")


def _decompress(s):
    y = int.from_bytes(s, "little")
    sign_bit = y >> 255
    y &= (1 << 255) - 1
    x = _xrecover(y)
    if (x & 1) != sign_bit:
        x = _p - x
    return (x, y, 1, x * y % _p)


def verify(pub: bytes, msg: bytes, sig: bytes) -> bool:
    try:
        A = _decompress(pub)
        R = _decompress(sig[:32])
    except Exception:
        return False
    S = int.from_bytes(sig[32:], "little")
    if S >= _q:
        return False
    k = int.from_bytes(_h(sig[:32] + pub + msg), "little") % _q
    left = _mul(S, _B)
    right = _add(R, _mul(k, A))
    return _compress(left) == _compress(right)

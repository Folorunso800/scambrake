import unittest
from scambrake import ed25519, nearlib


class TestEd25519(unittest.TestCase):
    # RFC 8032 section 7.1 test vectors 1-2
    VECTORS = [
        ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
         "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
         "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
        ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
         "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
         "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    ]

    def test_rfc8032_vectors(self):
        for seed, pub, msg, sig in self.VECTORS:
            seed, msg = bytes.fromhex(seed), bytes.fromhex(msg)
            self.assertEqual(ed25519.public_key(seed).hex(), pub)
            self.assertEqual(ed25519.sign(seed, msg).hex(), sig)
            self.assertTrue(ed25519.verify(bytes.fromhex(pub), msg, bytes.fromhex(sig)))

    def test_bad_signature_rejected(self):
        seed = bytes(range(32))
        pub = ed25519.public_key(seed)
        sig = ed25519.sign(seed, b"hello")
        self.assertTrue(ed25519.verify(pub, b"hello", sig))
        self.assertFalse(ed25519.verify(pub, b"hellp", sig))


class TestNearLib(unittest.TestCase):
    def test_base58_roundtrip(self):
        for b in (b"\0\0abc", bytes(range(32)), b"\xff" * 64):
            self.assertEqual(nearlib.b58decode(nearlib.b58encode(b)), b)

    def test_keypair_roundtrip(self):
        kp = nearlib.new_keypair()
        self.assertEqual(nearlib.public_from_secret(kp["secret_key"]), kp["public_key"])

    def test_function_call_key_borsh_layout(self):
        kp = nearlib.new_keypair()
        a = nearlib.a_add_fn_key(kp["public_key"], "g.testnet", ["pay"], 5 * 10**23)
        # action id 5, key type 0, 32 key bytes, nonce 0, perm 0 (FunctionCall), Some(allowance)
        self.assertEqual(a[0], 5)
        self.assertEqual(a[1], 0)
        self.assertEqual(a[2 + 32:2 + 32 + 8], bytes(8))
        self.assertEqual(a[2 + 32 + 8], 0)
        self.assertEqual(a[2 + 32 + 8 + 1], 1)

    def test_known_tx_hash_is_deterministic(self):
        kp = nearlib.new_keypair()
        tx = nearlib.build_tx("a.testnet", kp["public_key"], 1, "b.testnet", bytes(32), [nearlib.a_transfer(1)])
        s1, h1 = nearlib.sign_tx(tx, kp["secret_key"])
        s2, h2 = nearlib.sign_tx(tx, kp["secret_key"])
        self.assertEqual((s1, h1), (s2, h2))
        self.assertEqual(len(s1), len(tx) + 1 + 64)


if __name__ == "__main__":
    unittest.main()

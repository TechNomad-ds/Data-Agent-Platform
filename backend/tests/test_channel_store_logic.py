"""隔离单测：渠道 store 的纯逻辑部分（加解密往返）

不依赖 DB / pytest-asyncio / jose / bcrypt / 真实 settings。
只需 cryptography（stdlib 级别，已安装）。
用 python3 直接执行，或 pytest 跑。
"""
import base64
import hashlib
import json
import unittest


# ---------------------------------------------------------------------------
# 内联 security.py 中唯一被 store 使用的两个函数（decrypt 只是 encrypt 的逆）
# 测试的是「相同密钥派生逻辑 + Fernet 往返」——与生产代码字面量一致
# ---------------------------------------------------------------------------

_TEST_SECRET = "test-secret-key-for-unit-test-only-32chars!!"


def _get_fernet_key(secret: str = _TEST_SECRET) -> bytes:
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _encrypt(plain: str, secret: str = _TEST_SECRET) -> str:
    from cryptography.fernet import Fernet
    return Fernet(_get_fernet_key(secret)).encrypt(plain.encode()).decode()


def _decrypt(encrypted: str, secret: str = _TEST_SECRET) -> str:
    from cryptography.fernet import Fernet
    return Fernet(_get_fernet_key(secret)).decrypt(encrypted.encode()).decode()


# ---------------------------------------------------------------------------
# store.py 的两个纯函数（等价复刻，用于隔离测试）
# ---------------------------------------------------------------------------

def _encrypt_creds(creds: dict) -> str:
    return _encrypt(json.dumps(creds, ensure_ascii=False))


def _decrypt_creds(encrypted: str) -> dict:
    return json.loads(_decrypt(encrypted))


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------

class TestCredRoundtrip(unittest.TestCase):
    """凭据加解密往返——飞书 / 微信两套格式。"""

    def _roundtrip(self, creds: dict) -> None:
        encrypted = _encrypt_creds(creds)
        self.assertIsInstance(encrypted, str)
        # 明文值不应出现在密文里
        if creds:
            sample = list(creds.values())[0]
            self.assertNotIn(sample, encrypted)
        recovered = _decrypt_creds(encrypted)
        self.assertEqual(recovered, creds)

    def test_feishu_basic(self):
        self._roundtrip({"app_id": "cli_abc123", "app_secret": "super-secret-feishu"})

    def test_feishu_with_optional(self):
        self._roundtrip({
            "app_id": "cli_abc123",
            "app_secret": "super-secret-feishu",
            "encrypt_key": "optional-key",
            "verification_token": "optional-token",
        })

    def test_weixin(self):
        self._roundtrip({"bot_token": "wx-bot-token-789", "account_id": "wxid_123456"})

    def test_empty_creds(self):
        self._roundtrip({})

    def test_unicode_values(self):
        self._roundtrip({
            "note": "测试用例 — <>&\"'",
            "token": "abc中文xyz",
        })

    def test_two_encryptions_differ(self):
        """Fernet 随机 IV：同明文两次密文不同，解密后相等。"""
        creds = {"app_id": "same", "app_secret": "same"}
        ct1 = _encrypt_creds(creds)
        ct2 = _encrypt_creds(creds)
        self.assertNotEqual(ct1, ct2)
        self.assertEqual(_decrypt_creds(ct1), _decrypt_creds(ct2))

    def test_wrong_key_raises(self):
        """用不同密钥解密必须 raise（禁 fallback）。"""
        encrypted = _encrypt_creds({"k": "v"})
        with self.assertRaises(Exception):
            _decrypt(encrypted, secret="wrong-secret-key-totally-different!!")

    def test_tampered_ciphertext_raises(self):
        """篡改密文必须 raise。"""
        encrypted = _encrypt_creds({"k": "v"})
        suffix = "XXXX" if not encrypted.endswith("XXXX") else "YYYY"
        tampered = encrypted[:-4] + suffix
        with self.assertRaises(Exception):
            _decrypt_creds(tampered)


class TestDecryptInvalidInput(unittest.TestCase):
    """非法输入必须 raise，不兜底。"""

    def test_garbage_string(self):
        with self.assertRaises(Exception):
            _decrypt_creds("not-valid-fernet-token")

    def test_empty_string(self):
        with self.assertRaises(Exception):
            _decrypt_creds("")

    def test_non_json_plaintext_encrypted(self):
        """能解密但内容不是 JSON → JSON 解析失败，应 raise。"""
        non_json_ct = _encrypt("not-a-json-value")
        with self.assertRaises(Exception):
            _decrypt_creds(non_json_ct)


if __name__ == "__main__":
    unittest.main()

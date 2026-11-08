"""표준 라이브러리 scrypt와 개별 무작위 소금으로 비밀번호를 단방향 저장한다."""

import hashlib
import hmac
import secrets


class ScryptPasswordSecurity:
    # OWASP scrypt 권장 조합 중 32MiB 메모리 조합. 해시마다 새 소금을 쓴다.
    def _derive(self, password: str, salt: bytes) -> bytes:
        return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**15, r=8, p=3, dklen=64, maxmem=64 * 1024 * 1024)

    def hash(self, password: str) -> str:
        salt = secrets.token_bytes(16)
        return f"scrypt$32768$8$3${salt.hex()}${self._derive(password, salt).hex()}"

    def verify(self, password: str, encoded: str | None) -> bool:
        # 없는 계정도 같은 비용으로 계산하고 로그인 실패 메시지도 동일하게 반환한다.
        salt, expected, valid = bytes(16), bytes(64), False
        if encoded:
            try:
                algorithm, n, r, p, raw_salt, raw_hash = encoded.split("$")
                if (algorithm, n, r, p) == ("scrypt", "32768", "8", "3"):
                    salt, expected = bytes.fromhex(raw_salt), bytes.fromhex(raw_hash)
                    valid = len(salt) == 16 and len(expected) == 64
            except (ValueError, TypeError):
                pass
        actual = self._derive(password, salt)
        return hmac.compare_digest(actual, expected) and valid

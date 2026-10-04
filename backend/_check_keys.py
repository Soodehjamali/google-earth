"""One-off diagnostic: test each EE key file against Google's token endpoint.

Prints only pass/fail and error classes — never key material or tokens.
"""

import json
import time
from pathlib import Path

import requests

KEY_FILES = [
    Path("credentials/gee-key.json"),
]

TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/earthengine.readonly"


def b64url(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def test_key(path: Path) -> None:
    print(f"--- {path}")
    if not path.exists():
        print("    MISSING")
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    key_id = data.get("private_key_id", "?")
    email = data.get("client_email", "?")

    try:
        from authlib.jose import jwt as authlib_jwt  # noqa: F401

        raise RuntimeError("skip")
    except Exception:
        pass

    # Build the JWT with cryptography (available via earthengine-api deps).
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except Exception as exc:
        print(f"    cannot load cryptography: {exc}")
        return

    try:
        private_key = serialization.load_pem_private_key(
            data["private_key"].encode(), password=None
        )
    except Exception as exc:
        print(f"    INVALID PRIVATE KEY (does not parse): {type(exc).__name__}")
        return

    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT", "kid": key_id}
    claims = {
        "iss": email,
        "scope": SCOPE,
        "aud": TOKEN_URL,
        "iat": now,
        "exp": now + 3600,
    }
    signing_input = f"{b64url(json.dumps(header).encode())}.{b64url(json.dumps(claims).encode())}"
    signature = private_key.sign(
        signing_input.encode(), padding.PKCS1v15(), hashes.SHA256()
    )
    assertion = f"{signing_input}.{b64url(signature)}"

    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        },
        timeout=20,
    )
    if resp.status_code == 200:
        print(f"    key_id={key_id[:12]}..  =>  VALID (Google accepted the key)")
    else:
        err = resp.json()
        desc = err.get("error_description", "")
        print(f"    key_id={key_id[:12]}..  =>  REJECTED: {err.get('error')}: {desc[:80]}")


if __name__ == "__main__":
    for kf in KEY_FILES:
        test_key(kf)

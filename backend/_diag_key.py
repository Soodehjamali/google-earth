"""Temporary diagnostic: check EE key files vs .env config without leaking secrets."""

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
KEY_PATHS = [
    BACKEND / "credentials" / "gee-key.json",
]


def fingerprint(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode()).hexdigest()[:16]


def load_env(path: Path) -> dict:
    env = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def describe(path: Path) -> dict | None:
    print(f"--- {path}")
    if not path.exists():
        print("    MISSING")
        return None
    raw = path.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        print(f"    NOT VALID JSON: {type(exc).__name__}: {exc}")
        return None

    pem = data.get("private_key", "")
    has_crlf = raw.count(b"\r\n") > 0
    backslash_n = (chr(92) + "n") in pem
    print(f"  fields             : {sorted(data.keys())}")
    print(f"  type               : {data.get('type')}")
    print(f"  project_id         : {data.get('project_id')}")
    print(f"  client_email       : {data.get('client_email')}")
    print(f"  private_key_id     : {str(data.get('private_key_id'))[:12]}..")
    print(f"  CRLF in file       : {has_crlf}")
    print(f"  pem length         : {len(pem)} chars")
    print(f"  real newlines      : {pem.count(chr(10))}")
    print(f"  literal backslash-n: {backslash_n}")
    print(f"  starts ok          : {pem.startswith('-----BEGIN PRIVATE KEY-----')}")
    print(f"  ends ok            : {pem.rstrip().endswith('-----END PRIVATE KEY-----')}")
    print(f"  pem fingerprint    : {fingerprint(pem)}")

    try:
        from cryptography.hazmat.primitives import serialization

        key = serialization.load_pem_private_key(pem.encode(), password=None)
        pub = key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        print(f"  PEM parses         : True (pub sha256={fingerprint(pub.decode('latin-1'))})")
    except Exception as exc:
        print(f"  PEM parses         : False -> {type(exc).__name__}: {exc}")

    return data


def main() -> None:
    env = load_env(BACKEND / ".env")
    print("=== .env EE_* keys ===")
    for k in ("EE_PROJECT_ID", "EE_SERVICE_ACCOUNT", "EE_PRIVATE_KEY_FILE"):
        v = env.get(k)
        print(f"  {k}: {'SET' if v else 'UNSET'}" + (f" -> {v}" if v else ""))

    sa = env.get("EE_SERVICE_ACCOUNT", "")
    loaded = {}
    for p in KEY_PATHS:
        loaded[p] = describe(p)

    print("\n=== cross-check ===")
    for p, data in loaded.items():
        if not data:
            continue
        email = data.get("client_email", "")
        print(f"  {p.name}: EE_SERVICE_ACCOUNT matches client_email -> {bool(sa) and sa == email}")
        print(f"  {p.name}: EE_PROJECT_ID matches key project_id     -> {env.get('EE_PROJECT_ID', '') == data.get('project_id')}")


if __name__ == "__main__":
    sys.exit(main())

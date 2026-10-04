"""S.6 E2E scaffolding: split-routing proxy fix for the local sandbox.

The sandbox network requires split routing for Google's endpoints:

* ``oauth2.googleapis.com`` (auth/token) works on a DIRECT connection but
  is broken through the 127.0.0.1:8080 sandbox proxy (TLS EOF).
* ``earthengine.googleapis.com`` (discovery + compute) works only through
  the sandbox proxy; a DIRECT connection receives Google's IP-block 403.

Library behaviour in this venv (verified): the Earth Engine Python API 1.x
performs all HTTP through ``requests`` sessions (``ee.data._session``), so
the whole ee path — discovery and compute — follows urllib's proxy
detection. google-auth also uses requests for the token exchange.

This launcher therefore:

1. Makes urllib report the sandbox proxy for http/https (so the ee path
   reaches Earth Engine).
2. Patches ``requests``' ``should_bypass_proxies`` so the auth host is
   always bypassed (direct), because the sandbox proxy breaks that host.

Application code, production configuration and credentials are untouched.
This file is temporary E2E scaffolding and can be deleted afterwards.
"""

import urllib.request

_PROXY = "http://127.0.0.1:8080"
_BYPASS_MARKER = "oauth2.googleapis.com"

# 1. Proxy the Earth Engine path through the sandbox.
urllib.request.getproxies = lambda: {"http": _PROXY, "https": _PROXY}

# 2. Keep the auth host direct.
import requests.sessions
import requests.utils

_orig_should_bypass = requests.utils.should_bypass_proxies


def _should_bypass_proxies(url, no_proxy=None):
    if _BYPASS_MARKER in (url or ""):
        return True
    return _orig_should_bypass(url, no_proxy=no_proxy)


requests.utils.should_bypass_proxies = _should_bypass_proxies
requests.sessions.should_bypass_proxies = _should_bypass_proxies


def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8001)


if __name__ == "__main__":
    main()

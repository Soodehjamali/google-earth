"""Phase A1 regression tests — TASK 2 (Earth Engine error misclassification).

D2: ``_classify_error`` used to match broad substrings such as
"does not have permission" anywhere in the error text. Google's
IP-block 403 block page embeds that phrase in its boilerplate, so a
network-layer refusal was misreported as an IAM failure and served
IAM remediation instructions.

These tests use the exact reproduced failure forms from the audit:

  A. IP-block 403 HTML  -> network, never IAM instructions
  B. SSL EOF / retries  -> network, never IAM instructions
  C. invalid JWT        -> authentication / credential failure
  D. genuine IAM denial -> authorization failure

Messages stay sanitized: no raw exception text reaches the user.
"""

from __future__ import annotations

import pytest

from app.services.earth_engine import authentication as auth


# Exact reproduced failure forms from the Phase A1 acceptance audit.
IP_BLOCK_403_HTML = (
    "<HTML><HEAD><TITLE>Your client does not have permission to get "
    "URL /from this server.</TITLE></HEAD><BODY>"
    "<H1>403 Forbidden</H1>"
    "Your client does not have permission to get URL /v1/values from "
    "this server. That&#39;s all we know."
    "</BODY></HTML>"
)

SSL_EOF = (
    "HTTPSConnectionPool(host='earthengine.googleapis.com', port=443): "
    "Max retries exceeded with url: /v1/value (Caused by "
    "SSLError(SSLEOFError(8, 'EOF occurred in violation of protocol (_ssl.c:1131)')))"
)

INVALID_JWT = (
    "google.auth.exceptions.RefreshError: "
    "('invalid_grant: Invalid JWT Signature.', "
    "{'error': 'invalid_grant', 'error_description': 'Invalid JWT Signature.'})"
)

GENUINE_IAM = (
    "Caller does not have permission "
    "(['earthengine.googleapis.com/values:get']) or the resource may not "
    "exist. Permission 'earthengine.assets.get' denied on resource."
)

DNS_FAILURE = (
    "HTTPSConnectionPool(host='earthengine.googleapis.com', port=443): "
    "Max retries exceeded with url: /v1/value "
    "(Caused by NameResolutionError(\"Failed to resolve "
    "'earthengine.googleapis.com'\"))"
)


class TestIpBlockHtmlIsNetworkNotIam:
    def test_ip_block_403_html_classifies_as_connection_failure(self) -> None:
        code, message = auth._classify_error(Exception(IP_BLOCK_403_HTML))
        assert code == auth.CODE_CONNECTION_FAILED
        assert code != auth.CODE_PERMISSION_DENIED

    def test_ip_block_403_html_message_has_no_iam_instructions(self) -> None:
        code, message = auth._classify_error(Exception(IP_BLOCK_403_HTML))
        assert "roles/earthengine.viewer" not in message
        assert "IAM role" not in message
        assert "Resource Viewer" not in message

    def test_ip_block_html_message_is_connection_guidance(self) -> None:
        _, message = auth._classify_error(Exception(IP_BLOCK_403_HTML))
        assert "could not be reached" in message


class TestSslEofIsNetworkNotIam:
    def test_ssl_eof_classifies_as_connection_failure(self) -> None:
        code, message = auth._classify_error(Exception(SSL_EOF))
        assert code == auth.CODE_CONNECTION_FAILED

    def test_ssl_eof_message_has_no_iam_instructions(self) -> None:
        _, message = auth._classify_error(Exception(SSL_EOF))
        assert "roles/earthengine.viewer" not in message
        assert "IAM role" not in message

    def test_ssl_eof_via_typed_requests_exception(self) -> None:
        import requests.exceptions

        exc = requests.exceptions.SSLError(SSL_EOF)
        code, _ = auth._classify_error(exc)
        assert code == auth.CODE_CONNECTION_FAILED

    def test_dns_failure_classifies_as_connection_failure(self) -> None:
        code, _ = auth._classify_error(Exception(DNS_FAILURE))
        assert code == auth.CODE_CONNECTION_FAILED


class TestInvalidJwtIsAuthFailure:
    def test_invalid_grant_classifies_as_auth_failed(self) -> None:
        code, _ = auth._classify_error(Exception(INVALID_JWT))
        assert code == auth.CODE_AUTH_FAILED
        assert code != auth.CODE_PERMISSION_DENIED

    def test_invalid_jwt_message_has_no_iam_instructions(self) -> None:
        _, message = auth._classify_error(Exception(INVALID_JWT))
        assert "roles/earthengine.viewer" not in message

    def test_invalid_jwt_message_is_credential_guidance(self) -> None:
        _, message = auth._classify_error(Exception(INVALID_JWT))
        assert "service-account credentials" in message

    def test_bare_invalid_grant(self) -> None:
        code, _ = auth._classify_error(Exception("invalid_grant"))
        assert code == auth.CODE_AUTH_FAILED


class TestGenuineIamDenialStaysIam:
    def test_caller_does_not_have_permission_classifies_as_permission_denied(
        self,
    ) -> None:
        code, _ = auth._classify_error(Exception(GENUINE_IAM))
        assert code == auth.CODE_PERMISSION_DENIED

    def test_permission_denied_message_carries_iam_guidance(self) -> None:
        _, message = auth._classify_error(Exception(GENUINE_IAM))
        assert "earthengine.viewer" in message


class TestMessagesAreSanitized:
    @pytest.mark.parametrize(
        "raw",
        [IP_BLOCK_403_HTML, SSL_EOF, INVALID_JWT, GENUINE_IAM, DNS_FAILURE],
        ids=["ip_block_html", "ssl_eof", "invalid_jwt", "genuine_iam", "dns"],
    )
    def test_raw_exception_text_never_reaches_user(self, raw: str) -> None:
        _, message = auth._classify_error(Exception(raw))
        # None of the audit failure forms echoes raw internals; each
        # maps to one of the fixed sanitized guidance strings.
        assert message == auth._USER_MESSAGES[
            auth._classify_error(Exception(raw))[0]
        ]
        assert "<HTML>" not in message
        assert "earthengine.googleapis.com/v1" not in message

    def test_classify_always_returns_a_known_code(self) -> None:
        for raw in (IP_BLOCK_403_HTML, SSL_EOF, INVALID_JWT, GENUINE_IAM, "x"):
            code, _ = auth._classify_error(Exception(raw))
            assert code in set(auth._USER_MESSAGES)

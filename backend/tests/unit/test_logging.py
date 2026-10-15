"""Unit tests for logging filters and log masking."""

import logging
import pytest
from app.core.logging import TileTokenMaskingFilter


def test_mask_text_path_token():
    text = "/api/v1/agriculture/tiles/eyJhbGciOiJIUzI1NiJ9.payload.sig/10/681/412.png"
    masked = TileTokenMaskingFilter.mask_text(text)
    assert masked == "/api/v1/agriculture/tiles/***MASKED***/10/681/412.png"
    assert "eyJhbGciOiJIUzI1NiJ9" not in masked


def test_mask_text_query_param_token():
    text = "/api/v1/agriculture/frost/risk?token=sensitive_query_token_123&other=val"
    masked = TileTokenMaskingFilter.mask_text(text)
    assert masked == "/api/v1/agriculture/frost/risk?token=***MASKED***&other=val"
    assert "sensitive_query_token_123" not in masked


def test_mask_text_both_path_and_query_param():
    text = "/api/v1/agriculture/tiles/path_token_abc/10/681/412.png?token=query_token_xyz&foo=bar"
    masked = TileTokenMaskingFilter.mask_text(text)
    assert masked == "/api/v1/agriculture/tiles/***MASKED***/10/681/412.png?token=***MASKED***&foo=bar"
    assert "path_token_abc" not in masked
    assert "query_token_xyz" not in masked


def test_mask_text_short_path():
    text = "/tiles/bare_token_here"
    masked = TileTokenMaskingFilter.mask_text(text)
    assert masked == "/tiles/***MASKED***"
    assert "bare_token_here" not in masked


def test_uvicorn_access_logrecord_filtering():
    """Verify that TileTokenMaskingFilter properly sanitizes uvicorn.access LogRecord args."""
    filter_obj = TileTokenMaskingFilter()
    raw_path = "/api/v1/agriculture/tiles/secret.jwt.token/10/681/412.png?token=param_secret&x=1"
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:54321", "GET", raw_path, "1.1", 200),
        exc_info=None,
    )

    allowed = filter_obj.filter(record)
    assert allowed is True

    # Check sanitized args
    masked_url = record.args[2]
    assert "secret.jwt.token" not in masked_url
    assert "param_secret" not in masked_url
    assert masked_url == "/api/v1/agriculture/tiles/***MASKED***/10/681/412.png?token=***MASKED***&x=1"

    # Check formatted log message
    formatted_msg = record.getMessage()
    assert '127.0.0.1:54321 - "GET /api/v1/agriculture/tiles/***MASKED***/10/681/412.png?token=***MASKED***&x=1 HTTP/1.1" 200' == formatted_msg


def test_logrecord_dict_and_list_args():
    filter_obj = TileTokenMaskingFilter()
    dict_record = logging.LogRecord(
        name="app.tiles",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Tile requested: %(url)s",
        args=({"url": "/tiles/token_in_dict/1/2/3.png?token=dict_query"},),
        exc_info=None,
    )
    filter_obj.filter(dict_record)
    assert "token_in_dict" not in dict_record.args["url"]
    assert "dict_query" not in dict_record.args["url"]
    assert dict_record.args["url"] == "/tiles/***MASKED***/1/2/3.png?token=***MASKED***"
    assert "Tile requested: /tiles/***MASKED***/1/2/3.png?token=***MASKED***" == dict_record.getMessage()

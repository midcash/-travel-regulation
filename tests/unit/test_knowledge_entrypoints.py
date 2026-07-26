from __future__ import annotations

import json

import pytest

from src.config import Settings
from src.tool import knowledge
from tests.support.fakes import FakeHTTPResponse


def test_amap_entrypoint_fails_explicitly_when_key_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    result = knowledge._exec_amap_geocode('深圳', Settings())

    assert result == {'error': 'AMAP_API_KEY 未配置'}


def test_amap_entrypoint_parses_explicit_fake_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = json.dumps(
        {
            'status': '1',
            'geocodes': [
                {'location': '114.05,22.55', 'formatted_address': '深圳市'}
            ],
        }
    ).encode()
    monkeypatch.setattr(
        knowledge.urllib.request,
        'urlopen',
        lambda request, timeout: FakeHTTPResponse(body),
    )

    result = knowledge._exec_amap_geocode('深圳', Settings(amap_api_key='fake-amap-key'))

    assert result['lat'] == 22.55
    assert result['lng'] == 114.05
    assert result['display_name'] == '深圳市'


def test_tuniu_entrypoint_parses_json_rpc_text_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        'jsonrpc': '2.0',
        'result': {'content': [{'type': 'text', 'text': json.dumps({'price': 300})}]},
    }
    monkeypatch.setattr(
        knowledge.urllib.request,
        'urlopen',
        lambda request, timeout: FakeHTTPResponse(json.dumps(payload).encode()),
    )

    result = knowledge._tuniu_mcp_call(
        'hotel',
        'tuniuHotelSearch',
        {'city': '深圳'},
        Settings(tuniu_api_key='fake-tuniu-key'),
    )

    assert result == {'price': 300}


def test_tuniu_entrypoint_returns_parse_failure_without_empty_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        knowledge.urllib.request,
        'urlopen',
        lambda request, timeout: FakeHTTPResponse(b'not-json'),
    )

    result = knowledge._tuniu_mcp_call(
        'hotel',
        'tuniuHotelSearch',
        {'city': '深圳'},
        Settings(tuniu_api_key='fake-tuniu-key'),
    )

    assert result['error'] == '途牛响应解析失败'
    assert 'raw' in result


def test_tool_registry_is_allowlisted() -> None:
    assert set(knowledge.TOOL_EXECUTORS) == knowledge.ALLOWED_TOOLS

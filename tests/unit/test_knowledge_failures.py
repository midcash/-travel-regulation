from __future__ import annotations

import pytest

from src.config import Settings
from src.tool import knowledge
from tests.support.fakes import FakeHTTPResponse


def test_amap_timeout_is_explicit_failure_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def timeout(request: object, timeout: float) -> FakeHTTPResponse:
        raise TimeoutError('amap timeout')

    monkeypatch.setattr(knowledge.urllib.request, 'urlopen', timeout)

    result = knowledge._exec_amap_geocode(
        '杭州',
        Settings(amap_api_key='fake-amap-key'),
    )

    assert 'error' in result
    assert 'fallback' not in result


def test_tuniu_empty_result_is_explicit_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        knowledge.urllib.request,
        'urlopen',
        lambda request, timeout: FakeHTTPResponse(b'{"jsonrpc":"2.0","result":null}'),
    )

    result = knowledge._tuniu_mcp_call(
        'hotel',
        'tuniuHotelSearch',
        {'city': '杭州'},
        Settings(tuniu_api_key='fake-tuniu-key'),
    )

    assert result['error']

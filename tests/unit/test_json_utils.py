from __future__ import annotations

import json

import pytest

from src.gateway.json_utils import JsonResponseError, parse_json_object, sanitize_json


def test_sanitize_json_extracts_markdown_wrapped_object() -> None:
    assert sanitize_json('说明\n```json\n{ok: true}\n```\n') == '{ok: true}'


def test_parse_json_object_accepts_nested_json() -> None:
    raw = json.dumps({'items': [1, {'name': 'x'}]})
    assert parse_json_object(raw) == {
        'items': [1, {'name': 'x'}]
    }


@pytest.mark.parametrize('raw', ['', 'not-json', '[]', 'null'])
def test_parse_json_object_rejects_empty_invalid_or_non_object(raw: str) -> None:
    with pytest.raises(JsonResponseError):
        parse_json_object(raw)


def test_parse_json_object_does_not_treat_trailing_text_as_valid_json() -> None:
    with pytest.raises(JsonResponseError):
        parse_json_object('{ok: true} trailing')

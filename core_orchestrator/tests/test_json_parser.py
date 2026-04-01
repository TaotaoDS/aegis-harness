"""Tests for robust LLM JSON parser — handles markdown fences and malformed output."""

import json
import pytest

from core_orchestrator.json_parser import parse_llm_json


class TestCleanJSON:
    """Standard JSON strings should parse normally."""

    def test_plain_json_object(self):
        assert parse_llm_json('{"key": "value"}') == {"key": "value"}

    def test_plain_json_array(self):
        assert parse_llm_json('[1, 2, 3]') == [1, 2, 3]

    def test_nested_json(self):
        raw = json.dumps({"a": {"b": [1, 2]}, "c": True})
        assert parse_llm_json(raw) == {"a": {"b": [1, 2]}, "c": True}


class TestMarkdownFences:
    """JSON wrapped in markdown code fences should be extracted and parsed."""

    def test_json_fence(self):
        raw = '```json\n{"key": "value"}\n```'
        assert parse_llm_json(raw) == {"key": "value"}

    def test_plain_fence(self):
        raw = '```\n{"key": "value"}\n```'
        assert parse_llm_json(raw) == {"key": "value"}

    def test_fence_with_leading_text(self):
        raw = 'Here is the result:\n```json\n{"status": "ok"}\n```'
        assert parse_llm_json(raw) == {"status": "ok"}

    def test_fence_with_trailing_text(self):
        raw = '```json\n{"a": 1}\n```\nThat is the answer.'
        assert parse_llm_json(raw) == {"a": 1}

    def test_fence_with_extra_whitespace(self):
        raw = '```json\n  {"key": "value"}  \n```'
        assert parse_llm_json(raw) == {"key": "value"}

    def test_multiple_fences_uses_first(self):
        raw = '```json\n{"first": true}\n```\n```json\n{"second": true}\n```'
        assert parse_llm_json(raw) == {"first": True}


class TestLeadingTrailingGarbage:
    """JSON preceded or followed by non-JSON text should still parse."""

    def test_leading_text(self):
        raw = 'Sure, here is the JSON:\n{"result": 42}'
        assert parse_llm_json(raw) == {"result": 42}

    def test_trailing_text(self):
        raw = '{"result": 42}\nHope that helps!'
        assert parse_llm_json(raw) == {"result": 42}

    def test_both_sides(self):
        raw = 'Output:\n{"a": 1}\nDone.'
        assert parse_llm_json(raw) == {"a": 1}


class TestMalformedInput:
    """Completely unparseable input should return fallback dict, not crash."""

    def test_returns_empty_dict_on_garbage(self):
        assert parse_llm_json("this is not json at all") == {}

    def test_returns_empty_dict_on_empty_string(self):
        assert parse_llm_json("") == {}

    def test_returns_custom_fallback(self):
        fallback = {"error": "parse_failed"}
        assert parse_llm_json("bad", fallback=fallback) == {"error": "parse_failed"}

    def test_returns_empty_dict_on_partial_json(self):
        assert parse_llm_json('{"key": "val') == {}

    def test_returns_empty_dict_on_fence_with_bad_content(self):
        raw = '```json\nnot valid json\n```'
        assert parse_llm_json(raw) == {}

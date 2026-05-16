"""Tests for the entity/relation extraction service."""

from __future__ import annotations

import json

from app.services.extraction import (
    ALLOWED_ENTITY_TYPES,
    Entity,
    Relation,
    extract,
)
from tests.conftest import FakeClaude, _FakeBlock, _FakeMessage


def _scripted(json_payload: dict) -> _FakeMessage:
    """Wrap a structured payload as Claude would return it in JSON mode."""
    return _FakeMessage(
        content=[_FakeBlock(type="text", text=json.dumps(json_payload))]
    )


def test_extract_parses_valid_payload(fake_claude: FakeClaude):
    fake_claude.responses = [
        _scripted(
            {
                "entities": [
                    {"name": "Anthropic", "type": "Organization"},
                    {"name": "Claude", "type": "Product"},
                ],
                "relations": [
                    {"head": "Anthropic", "relation": "develops", "tail": "Claude"}
                ],
            }
        )
    ]
    result = extract("Anthropic develops Claude, an AI assistant.")
    assert result.entities == [
        Entity(name="Anthropic", type="Organization"),
        Entity(name="Claude", type="Product"),
    ]
    assert result.relations == [Relation(head="Anthropic", relation="develops", tail="Claude")]


def test_extract_sends_schema_via_output_config(fake_claude: FakeClaude):
    fake_claude.responses = [_scripted({"entities": [], "relations": []})]
    extract("Boring paragraph.")
    call = fake_claude.calls[0]
    assert call["output_config"]["format"]["type"] == "json_schema"
    schema = call["output_config"]["format"]["schema"]
    # Schema must enforce both arrays and entity-type enum.
    assert set(schema["required"]) == {"entities", "relations"}
    type_enum = schema["properties"]["entities"]["items"]["properties"]["type"]["enum"]
    assert set(type_enum) == set(ALLOWED_ENTITY_TYPES)


def test_extract_drops_unknown_entity_types(fake_claude: FakeClaude):
    # Claude shouldn't return out-of-enum types thanks to the schema, but
    # defend in depth — filter at parse time too.
    fake_claude.responses = [
        _scripted(
            {
                "entities": [
                    {"name": "Bob", "type": "Pokemon"},  # invalid
                    {"name": "Anthropic", "type": "Organization"},
                ],
                "relations": [],
            }
        )
    ]
    result = extract("…")
    assert [e.name for e in result.entities] == ["Anthropic"]


def test_extract_drops_relations_with_missing_endpoints(fake_claude: FakeClaude):
    fake_claude.responses = [
        _scripted(
            {
                "entities": [{"name": "Alice", "type": "Person"}],
                "relations": [
                    {"head": "Alice", "relation": "knows", "tail": "Bob"},  # Bob unknown
                    {"head": "Alice", "relation": "works at", "tail": "Alice"},  # self-rel OK
                ],
            }
        )
    ]
    result = extract("…")
    assert len(result.relations) == 1
    assert result.relations[0].tail == "Alice"


def test_extract_returns_empty_on_invalid_json(fake_claude: FakeClaude):
    fake_claude.responses = [
        _FakeMessage(content=[_FakeBlock(type="text", text="not json at all")])
    ]
    result = extract("…")
    assert result.entities == []
    assert result.relations == []


def test_extract_returns_empty_on_empty_arrays(fake_claude: FakeClaude):
    fake_claude.responses = [_scripted({"entities": [], "relations": []})]
    result = extract("This paragraph contains no named entities.")
    assert result.entities == []
    assert result.relations == []

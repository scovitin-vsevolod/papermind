"""Entity and relation extraction via Claude's structured-output mode.

Given a chunk of document text, Claude returns a JSON object describing:

- **Entities** — distinct named things (people, organisations, concepts,
  products, technologies, places). Each has a canonical ``name`` and a
  ``type`` from a small fixed set.
- **Relations** — directed (head → relation → tail) edges between
  entities mentioned in the SAME chunk. The relation label is a short
  verb phrase the model picks.

Why structured output instead of regex / tool_use
-------------------------------------------------
The output is small and uniform — a known schema. Asking Claude to
write text and then parsing it would waste tokens and invite parsing
bugs. The Messages API's ``output_config.format`` enforces a JSON
schema, so we get back valid JSON or a refusal — no flaky regex.

Why same-chunk relations only
-----------------------------
Cross-chunk linking is a second-pass problem: it requires a global
entity-resolution step (e.g. coreference of "the company" → "Anthropic"
across paragraphs). That belongs in Phase 4+. Phase 3 sticks to the
straightforward "what's stated in this paragraph" reading.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.config import settings
from app.services.claude import _client  # reuse the singleton/swap

# Allowed entity types. Keeping the set small forces consistent labelling
# across chunks — `Person` here always means a human, never a fictional
# character — and lets the graph viewer colour-code reliably.
ALLOWED_ENTITY_TYPES = [
    "Person",
    "Organization",
    "Location",
    "Concept",
    "Technology",
    "Product",
    "Event",
    "Other",
]

EXTRACTION_SYSTEM_PROMPT = (
    "You extract entities and the relations between them from a single "
    "paragraph of text. You always return a JSON object matching the "
    "provided schema — no prose, no markdown. "
    "Be conservative: only include entities and relations that are "
    "EXPLICITLY stated in the text. Skip ambiguous or implied references."
)

# JSON schema attached to output_config so Claude returns validated JSON.
_EXTRACTION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": (
                            "Canonical name. For people use 'Firstname Lastname'. "
                            "For organisations use the official short name."
                        ),
                    },
                    "type": {
                        "type": "string",
                        "enum": ALLOWED_ENTITY_TYPES,
                    },
                },
                "required": ["name", "type"],
                "additionalProperties": False,
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "head": {"type": "string", "description": "Name of source entity"},
                    "relation": {
                        "type": "string",
                        "description": "Short verb phrase, e.g. 'founded', 'works at'",
                    },
                    "tail": {"type": "string", "description": "Name of target entity"},
                },
                "required": ["head", "relation", "tail"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["entities", "relations"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Entity:
    name: str
    type: str


@dataclass(frozen=True)
class Relation:
    head: str
    relation: str
    tail: str


@dataclass(frozen=True)
class ExtractionResult:
    entities: list[Entity]
    relations: list[Relation]


def extract(text: str, *, max_tokens: int = 1024) -> ExtractionResult:
    """Run Claude on one chunk of text; return the parsed entities + relations.

    Returns empty lists if Claude finds nothing rather than raising —
    plenty of paragraphs are pure prose with no named entities, and that
    isn't an error.
    """
    response = _client().messages.create(
        model=settings.claude_model,
        max_tokens=max_tokens,
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text}],
        output_config={"format": {"type": "json_schema", "schema": _EXTRACTION_SCHEMA}},
    )

    raw = "".join(
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    ).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Schema enforcement should make this impossible, but degrade
        # gracefully: an empty graph is better than crashing ingestion.
        return ExtractionResult(entities=[], relations=[])

    entities = [
        Entity(name=e["name"].strip(), type=e["type"])
        for e in data.get("entities", [])
        if e.get("name") and e.get("type") in ALLOWED_ENTITY_TYPES
    ]
    # Filter out relations whose endpoints aren't in the entities list — the
    # graph stays consistent: every edge has both vertices in the same chunk.
    names = {e.name for e in entities}
    relations = [
        Relation(head=r["head"].strip(), relation=r["relation"].strip(), tail=r["tail"].strip())
        for r in data.get("relations", [])
        if r.get("head") in names and r.get("tail") in names and r.get("relation")
    ]
    return ExtractionResult(entities=entities, relations=relations)

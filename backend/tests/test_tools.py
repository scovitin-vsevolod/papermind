"""Tests for the tool_use surface — calculator (custom, client-side) and
the server-side web_search / web_fetch enablement."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services.tools import (
    ALL_TOOLS,
    CalculatorError,
    evaluate_expression,
    execute_custom_tool,
)
from tests.conftest import (
    FakeClaude,
    _FakeBlock,
    _FakeMessage,
    make_text_message,
    make_tool_use_message,
)

# ── Pure calculator unit tests ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("1 + 1", 2),
        ("12 * (3 + 4) / 2", 42),
        ("2 ** 10", 1024),
        ("-7 + 3", -4),
        ("17 % 5", 2),
        ("7 // 2", 3),
        ("0.1 + 0.2", 0.3),
    ],
)
def test_evaluate_expression(expression: str, expected: float):
    assert evaluate_expression(expression) == pytest.approx(expected)


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('rm -rf /')",  # name + call
        "open('/etc/passwd')",                  # name + call
        "x + 1",                                # bare name
        "list()",                               # call
        "1 + 'a'",                              # nope — string constant rejected
        "1 +",                                  # syntax error
        "import os",                            # statement, not expression
    ],
)
def test_calculator_rejects_unsafe_input(expression: str):
    with pytest.raises(CalculatorError):
        evaluate_expression(expression)


def test_execute_custom_tool_returns_string():
    assert execute_custom_tool("calculator", {"expression": "2 + 2"}) == "4"
    assert execute_custom_tool("calculator", {"expression": "1 / 4"}) == "0.25"


def test_execute_custom_tool_packages_error_text():
    # Errors come back as "ERROR: ..." rather than raising, so Claude can
    # see what went wrong via the tool_result block and retry.
    out = execute_custom_tool("calculator", {"expression": "1 +"})
    assert out.startswith("ERROR:")


def test_execute_unknown_tool_raises():
    with pytest.raises(ValueError, match="unknown custom tool"):
        execute_custom_tool("ftp_upload", {})


# ── End-to-end /ask?use_tools=true flow ──────────────────────────────────────


def _upload(client: TestClient, name: str, body: bytes):
    return client.post("/documents", files={"file": (name, body, "text/plain")})


def test_use_tools_false_does_not_send_tools_to_claude(
    client: TestClient, fake_claude: FakeClaude
):
    _upload(client, "x.txt", b"some context")
    fake_claude.calls.clear()  # ignore extraction calls during upload
    client.post("/ask", json={"question": "q?"})  # default use_tools=False
    call = fake_claude.calls[0]
    assert "tools" not in call


def test_use_tools_true_sends_full_tool_list(
    client: TestClient, fake_claude: FakeClaude
):
    _upload(client, "x.txt", b"some context")
    fake_claude.calls.clear()  # ignore extraction calls during upload
    client.post("/ask", json={"question": "q?", "use_tools": True})
    call = fake_claude.calls[0]
    assert "tools" in call
    names = {t["name"] for t in call["tools"]}
    assert names == {"web_search", "web_fetch", "calculator"}


def test_calculator_loop_executes_and_feeds_result_back(
    client: TestClient, fake_claude: FakeClaude
):
    _upload(client, "x.txt", b"context about math")
    # The upload also calls Claude (entity extraction per chunk). Reset
    # so the scripted responses below are consumed only by /ask.
    fake_claude.calls.clear()

    # Claude's first response: "I need the calculator" + tool_use(2+2)
    # Claude's second response (after we feed back "4"): final text answer.
    fake_claude.responses = [
        make_tool_use_message(
            tool_use_id="toolu_abc",
            tool_name="calculator",
            tool_input={"expression": "2 + 2"},
            leading_text="Let me compute that.",
        ),
        make_text_message("The answer is 4 [chunk:1]."),
    ]

    r = client.post("/ask", json={"question": "What is 2+2?", "use_tools": True})
    assert r.status_code == 200, r.text

    body = r.json()
    assert "4" in body["answer"]
    # Two API calls: initial + after tool_result
    assert len(fake_claude.calls) == 2
    # Second call's messages should include our tool_result block
    second_call_messages = fake_claude.calls[1]["messages"]
    assert second_call_messages[-1]["role"] == "user"
    assert second_call_messages[-1]["content"][0]["type"] == "tool_result"
    assert second_call_messages[-1]["content"][0]["content"] == "4"

    # And the response surfaces the tool invocation for transparency.
    tool_uses = body["tool_uses"]
    assert len(tool_uses) == 1
    assert tool_uses[0]["name"] == "calculator"
    assert tool_uses[0]["input"] == {"expression": "2 + 2"}
    assert tool_uses[0]["result"] == "4"


def test_server_tool_use_is_recorded_without_extra_round_trip(
    client: TestClient, fake_claude: FakeClaude
):
    _upload(client, "x.txt", b"context")
    fake_claude.calls.clear()  # ignore extraction calls during upload

    # Claude's single response contains a server_tool_use block (web_search)
    # alongside the final text. We don't run anything client-side; we just
    # record the call.
    fake_claude.responses = [
        _FakeMessage(
            content=[
                _FakeBlock(
                    type="server_tool_use",
                    name="web_search",
                    input={"query": "latest paper on retrieval-augmented generation"},
                ),
                _FakeBlock(type="text", text="Recent work shows… [chunk:1]"),
            ],
            stop_reason="end_turn",
        )
    ]

    r = client.post("/ask", json={"question": "What's new in RAG?", "use_tools": True})
    body = r.json()
    assert body["tool_uses"] == [
        {
            "name": "web_search",
            "input": {"query": "latest paper on retrieval-augmented generation"},
            "result": "(server-handled)",
        }
    ]
    # Only one API call — no loop for server tools.
    assert len(fake_claude.calls) == 1


def test_all_tools_list_has_three_entries():
    # Sanity: the public surface advertises exactly three tools.
    assert len(ALL_TOOLS) == 3
    assert {t["name"] for t in ALL_TOOLS} == {"web_search", "web_fetch", "calculator"}


def test_tool_loop_hard_caps_at_max_iterations(
    client: TestClient, fake_claude: FakeClaude
):
    # If Claude keeps emitting tool_use forever (bug or hostile), the loop
    # must bail rather than burn budget. Cap is _MAX_TOOL_ITERATIONS=5.
    _upload(client, "x.txt", b"context")
    fake_claude.calls.clear()

    # Scripted: every response is "use the calculator" — never a final
    # text answer. Should hit the cap after 5 invocations and return
    # what's there (empty answer from the last response's text blocks).
    looping = make_tool_use_message(
        tool_use_id="toolu_loop",
        tool_name="calculator",
        tool_input={"expression": "1 + 1"},
    )
    fake_claude.responses = [looping] * 10  # more than the cap

    r = client.post("/ask", json={"question": "loop?", "use_tools": True})
    assert r.status_code == 200
    # 1 initial call + 5 loop iterations = 6 calls total; the cap held.
    # Without the cap, 10 scripted responses would all be consumed.
    assert len(fake_claude.calls) == 6

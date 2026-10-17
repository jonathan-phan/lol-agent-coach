import json

import pytest

import agent
from tool_registry import TOOLS_SCHEMA, run_tool


def _reply(content=None, tool_calls=None):
    message = {"content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message}]}


def _tool_call(name, arguments, call_id="c1"):
    return {"id": call_id, "function": {"name": name, "arguments": json.dumps(arguments)}}


class SeenMessages(list):
    """Messages received at each LLM call; `.keys` holds the api_key passed to each call."""

    keys: list


@pytest.fixture
def scripted_llm(monkeypatch):
    """Replay a list of LLM replies; expose the messages received at each call."""
    def install(replies):
        seen = SeenMessages()
        seen.keys = []
        queue = iter(replies)

        def fake(messages, api_key=None):
            seen.append([dict(m) for m in messages])
            seen.keys.append(api_key)
            return next(queue)

        monkeypatch.setattr(agent, "call_llm", fake)
        return seen
    return install


def test_visitor_key_is_forwarded_and_never_stored_in_messages(scripted_llm):
    seen = scripted_llm([_reply("Hello")])
    _, messages = agent.agent_loop("yo", [], api_key="sk-visitor-secret")
    assert seen.keys == ["sk-visitor-secret"]
    assert "sk-visitor-secret" not in json.dumps(messages)


def test_missing_llm_key_raises_a_clear_error(monkeypatch):
    monkeypatch.setattr(agent, "LLM_API_KEY", None)
    with pytest.raises(RuntimeError, match="No LLM key"):
        agent.call_llm([], api_key=None)


def test_visitor_key_is_sent_as_bearer_token(monkeypatch):
    sent = {}

    class Resp:
        status_code, ok = 200, True

        def json(self):
            return {"choices": []}

    def fake_post(url, headers, json, timeout):
        sent.update(headers)
        return Resp()

    monkeypatch.setattr(agent.requests, "post", fake_post)
    agent.call_llm([], api_key="sk-visitor-secret")
    assert sent["Authorization"] == "Bearer sk-visitor-secret"


@pytest.mark.parametrize("status,fragment", [(401, "Invalid LLM key"), (429, "quota")])
def test_llm_errors_are_explained(monkeypatch, status, fragment):
    class Resp:
        status_code, ok, text = status, False, ""

    monkeypatch.setattr(agent.requests, "post", lambda *a, **k: Resp())
    with pytest.raises(RuntimeError, match=fragment):
        agent.call_llm([], api_key="k")


def test_invalid_tool_arguments_are_reported_to_the_llm(scripted_llm):
    bad_call = {"id": "c1", "function": {"name": "analyze_last_game", "arguments": "{not json"}}
    seen = scripted_llm([_reply(tool_calls=[bad_call]), _reply("Recovered")])
    answer, _ = agent.agent_loop("q", [])
    assert answer == "Recovered"
    assert "Invalid JSON arguments" in seen[1][-1]["content"]


def test_tools_used_lists_calls_in_order(scripted_llm):
    args = {"game_name": "A", "tag_line": "B"}
    scripted_llm([
        _reply(tool_calls=[_tool_call("analyze_last_game", args)]),
        _reply(tool_calls=[_tool_call("compute_stats", args, "c2")]),
        _reply("Done"),
    ])
    _, messages = agent.agent_loop("q", [])
    assert agent.tools_used(messages) == ["analyze_last_game", "compute_stats"]


def test_direct_answer_is_returned_and_conversation_kept(scripted_llm):
    scripted_llm([_reply("Hello")])
    answer, messages = agent.agent_loop("yo", [])
    assert answer == "Hello"
    assert [m["role"] for m in messages] == ["system", "user", "assistant"]


def test_tool_call_result_is_sent_back_to_llm(scripted_llm, monkeypatch):
    monkeypatch.setattr(agent, "run_tool", lambda name, args: {"echo": args})
    seen = scripted_llm([
        _reply(tool_calls=[_tool_call("analyze_last_game", {"game_name": "A", "tag_line": "B"})]),
        _reply("Fini"),
    ])
    answer, messages = agent.agent_loop("question", [])
    assert answer == "Fini"
    tool_msg = seen[1][-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "c1"
    assert json.loads(tool_msg["content"]) == {"echo": {"game_name": "A", "tag_line": "B"}}


def test_invented_spell_details_trigger_one_retry(scripted_llm):
    seen = scripted_llm([_reply("You missed your (Q)"), _reply("Clean answer")])
    answer, _ = agent.agent_loop("q", [])
    assert answer == "Clean answer"
    assert "spells" in seen[1][-1]["content"]


def test_retry_happens_only_once(scripted_llm):
    scripted_llm([_reply("ward"), _reply("encore une ward")])
    answer, _ = agent.agent_loop("q", [])
    assert answer == "encore une ward"


def test_gives_up_after_max_steps(scripted_llm):
    call = _tool_call("analyze_last_game", {"game_name": "A", "tag_line": "B"})
    scripted_llm([_reply(tool_calls=[call])] * agent.MAX_STEPS)
    answer, _ = agent.agent_loop("q", [])
    assert "Too many tool steps" in answer


def test_run_tool_unknown_name():
    assert run_tool("nope", {}) == {"error": "Unknown tool: nope"}


def test_run_tool_wraps_exceptions():
    result = run_tool("analyze_last_game", {"wrong": 1})
    assert "Error while running analyze_last_game" in result["error"]


def test_run_tool_dispatches_with_default_count(monkeypatch):
    import tool_registry
    seen = {}
    monkeypatch.setattr(tool_registry, "get_match_history", lambda g, t, count: seen.update(count=count) or [])
    run_tool("get_match_history", {"game_name": "A", "tag_line": "B"})
    assert seen["count"] == 10


def test_schemas_expose_count_only_for_multi_game_tools():
    params = {s["function"]["name"]: s["function"]["parameters"] for s in TOOLS_SCHEMA}
    assert set(params) == {"get_match_history", "compute_stats", "analyze_last_game", "analyze_last_game_by_phase"}
    for name, p in params.items():
        assert p["required"] == ["game_name", "tag_line"]
        assert ("count" in p["properties"]) == (name in ("get_match_history", "compute_stats"))

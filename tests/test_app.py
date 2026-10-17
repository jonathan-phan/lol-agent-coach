import json
import os

import pytest
from streamlit.testing.v1 import AppTest

import agent
import riot_client

APP = os.path.join(os.path.dirname(__file__), "..", "app.py")
NAME, TAG = riot_client.DEMO_PLAYER


def _tool_call_then_answer(monkeypatch, sent):
    call = {"id": "c1", "function": {"name": "analyze_last_game",
                                     "arguments": json.dumps({"game_name": NAME, "tag_line": TAG})}}
    replies = iter([
        {"choices": [{"message": {"content": "", "tool_calls": [call]}}]},
        {"choices": [{"message": {"content": "You farmed well."}}]},
    ])

    def fake_llm(messages, api_key=None):
        sent.append((messages[-1]["role"], api_key))
        return next(replies)

    monkeypatch.setattr(agent, "call_llm", fake_llm)


def test_app_starts_in_demo_mode_without_any_input():
    at = AppTest.from_file(APP).run()
    assert not at.exception
    assert "Demo mode" in at.sidebar.info[0].value
    assert not at.sidebar.text_input[0].value  # first field is the LLM key, not a Riot name


def test_question_is_answered_and_tools_are_displayed(monkeypatch):
    sent = []
    _tool_call_then_answer(monkeypatch, sent)
    at = AppTest.from_file(APP).run()
    at.sidebar.text_input[0].set_value("sk-visitor").run()
    at.chat_input[0].set_value("How did I do?").run()

    assert not at.exception
    assert [m.name for m in at.chat_message] == ["user", "assistant"]
    assert at.chat_message[1].markdown[0].value == "You farmed well."
    assert "analyze_last_game" in at.chat_message[1].caption[0].value
    assert sent[0][1] == "sk-visitor"


def test_missing_llm_key_is_shown_as_a_message_not_a_crash(monkeypatch):
    monkeypatch.setattr(agent, "LLM_API_KEY", None)
    at = AppTest.from_file(APP).run()
    at.chat_input[0].set_value("Hello").run()
    assert not at.exception
    assert "No LLM key" in at.chat_message[1].markdown[0].value


def test_session_limit_refuses_further_questions(monkeypatch):
    monkeypatch.setattr(agent, "LLM_API_KEY", None)
    at = AppTest.from_file(APP)
    at.session_state["questions_asked"] = 20
    at.session_state["conversation"] = []
    at.session_state["display"] = []
    at.run()
    at.chat_input[0].set_value("one more").run()
    assert "Session limit" in at.warning[0].value


def test_invalid_mode_is_reported(monkeypatch):
    monkeypatch.setenv("RIOT_MODE", "prod")
    at = AppTest.from_file(APP).run()
    assert "RIOT_MODE" in at.error[0].value

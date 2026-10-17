import json

import pytest

import agent
import riot_client
from conftest import load_demo, load_fixture
from tool_registry import run_tool
from tools.last_game import analyze_last_game
from tools.phase_analysis import analyze_last_game_by_phase
from tools.stats import compute_stats

GOLDEN = load_fixture("golden.json")
NAME, TAG = riot_client.DEMO_PLAYER


def test_demo_is_the_default_mode():
    assert riot_client.mode() == "demo"


def test_unknown_mode_is_rejected(monkeypatch):
    monkeypatch.setenv("RIOT_MODE", "prod")
    with pytest.raises(riot_client.RiotAPIError, match="RIOT_MODE"):
        riot_client.mode()


def test_tools_work_in_demo_mode_without_any_network_or_riot_key(monkeypatch):
    monkeypatch.setattr(riot_client, "RIOT_API_KEY", None)
    assert riot_client.get_match_history(NAME, TAG, count=1) == GOLDEN["history"]
    assert analyze_last_game(NAME, TAG) == GOLDEN["last_game"]
    assert analyze_last_game_by_phase(NAME, TAG) == GOLDEN["phase"]
    assert compute_stats(riot_client.get_match_history(NAME, TAG, count=1)) == GOLDEN["stats"]


def test_demo_ignores_the_requested_player():
    assert analyze_last_game("Someone", "ELSE") == analyze_last_game(NAME, TAG)


def test_demo_player_is_the_sample_match_player():
    me = riot_client.get_match_history(NAME, TAG)[0]["me"]
    assert me["summoner_name"] == NAME


def test_demo_honours_count_zero_and_single_match():
    assert riot_client.get_match_history(NAME, TAG, count=0) == []
    assert len(riot_client.get_match_history(NAME, TAG, count=10)) == 1


def test_live_mode_without_riot_key_explains_what_to_do(monkeypatch):
    monkeypatch.setenv("RIOT_MODE", "live")
    monkeypatch.setattr(riot_client, "RIOT_API_KEY", None)
    riot_client.get_puuid.cache_clear()
    with pytest.raises(riot_client.RiotAPIError, match="RIOT_API_KEY.*RIOT_MODE=demo"):
        riot_client.get_match_history("A", "B")


def test_registry_runs_tools_on_demo_data():
    result = run_tool("analyze_last_game", {"game_name": NAME, "tag_line": TAG})
    assert result == GOLDEN["last_game"]


def test_agent_answers_from_demo_data_end_to_end(monkeypatch):
    call = {"id": "c1", "function": {"name": "analyze_last_game_by_phase",
                                     "arguments": json.dumps({"game_name": NAME, "tag_line": TAG})}}
    replies = iter([
        {"choices": [{"message": {"content": "", "tool_calls": [call]}}]},
        {"choices": [{"message": {"content": "Done"}}]},
    ])
    seen = []

    def fake_llm(messages, api_key=None):
        seen.append(messages[-1])
        return next(replies)

    monkeypatch.setattr(agent, "call_llm", fake_llm)
    answer, _ = agent.agent_loop("Analyze my last game", [])
    tool_result = json.loads(seen[1]["content"])
    assert answer == "Done"
    assert tool_result["match_id"] == load_demo("match")["metadata"]["matchId"]
    assert [m["minute"] for m in tool_result["milestones"]] == [10, 15, 20]

import re

from conftest import load_demo
from limits import MAX_QUESTION_CHARS, MAX_QUESTIONS_PER_SESSION, check_question


def _values_for_key(node, key):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                yield v
            yield from _values_for_key(v, key)
    elif isinstance(node, list):
        for v in node:
            yield from _values_for_key(v, key)


def test_demo_data_contains_no_real_player_identifiers():
    match, timeline = load_demo("match"), load_demo("timeline")
    for data in (match, timeline):
        assert all(re.fullmatch(r"demo-puuid-\d+", v) for v in _values_for_key(data, "puuid"))
        assert set(_values_for_key(data, "gameId")) <= {1}
    participants = match["info"]["participants"]
    assert all(re.fullmatch(r"DemoPlayer|Player\d+", p["riotIdGameName"]) for p in participants)
    assert {p["riotIdTagline"] for p in participants} == {"DEMO"}
    assert all(re.fullmatch(r"demo-summoner-\d+", p["summonerId"]) for p in participants)
    assert match["metadata"]["matchId"] == "DEMO_1" == timeline["metadata"]["matchId"]


def test_question_within_limits_is_allowed():
    assert check_question("Analyze my last game", 0) is None


def test_question_is_refused_after_the_session_limit():
    assert "Session limit" in check_question("hi", MAX_QUESTIONS_PER_SESSION)
    assert check_question("hi", MAX_QUESTIONS_PER_SESSION - 1) is None


def test_overlong_question_is_refused():
    assert "too long" in check_question("x" * (MAX_QUESTION_CHARS + 1), 0)
    assert check_question("x" * MAX_QUESTION_CHARS, 0) is None

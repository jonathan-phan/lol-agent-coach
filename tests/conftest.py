import json
import os
import sys

import pytest
import requests

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import riot_client  # noqa: E402


def load_fixture(name: str):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


def load_demo(name: str):
    """Fresh copy of the anonymized sample match ("match" or "timeline")."""
    with open(os.path.join(riot_client.DEMO_DIR, f"{name}.json"), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(autouse=True)
def demo_mode_without_network(monkeypatch):
    """Default mode is demo, and no test may reach the network."""
    monkeypatch.delenv("RIOT_MODE", raising=False)

    def no_network(*args, **kwargs):
        raise AssertionError("unexpected network call")

    monkeypatch.setattr(requests, "get", no_network)
    monkeypatch.setattr(requests, "post", no_network)


@pytest.fixture
def riot(monkeypatch, tmp_path):
    """Live mode where only the Riot HTTP call is replaced, serving the sample match."""
    match = load_demo("match")
    state = {
        "game_name": "Tester", "tag_line": "EUW", "match_id": match["metadata"]["matchId"],
        "match_ids": [match["metadata"]["matchId"]],
        "match": match, "timeline": load_demo("timeline"),
    }
    puuid = match["info"]["participants"][0]["puuid"]

    def fake_get(url, params=None, _retries=3):
        if "by-riot-id" in url:
            return {"puuid": puuid}
        if url.endswith("/ids"):
            return state["match_ids"]
        if url.endswith("/timeline"):
            return state["timeline"]
        return state["match"]

    monkeypatch.setenv("RIOT_MODE", "live")
    monkeypatch.setattr(riot_client, "_get", fake_get)
    monkeypatch.setattr(riot_client, "CACHE_DIR", str(tmp_path))
    riot_client.get_puuid.cache_clear()
    return state

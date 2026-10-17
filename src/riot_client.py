"""
Riot match data for the tools, from one of two sources chosen by RIOT_MODE:

- demo (default): an anonymized sample match replayed from disk; needs no
  Riot key and never touches the network.
- live: the Riot Games API (needs RIOT_API_KEY, a dev key expires every 24h).

Interface for the tools: get_match_history(), get_last_match(), mode() and
DEMO_PLAYER. The rest (sources, HTTP, retry, disk cache, PUUID) is implementation.

Riot uses two kinds of base URLs: "platform" routing (e.g. euw1.api.riotgames.com,
region-bound data) and "regional" routing (e.g. europe.api.riotgames.com,
cross-region data such as match history). Only regional routing is used here.

Official docs: https://developer.riotgames.com/apis
"""
import os
import json
import time
from functools import lru_cache
from urllib.parse import quote
import requests
from dotenv import load_dotenv

load_dotenv()

RIOT_API_KEY = os.getenv("RIOT_API_KEY")
REGIONAL = os.getenv("RIOT_REGIONAL", "europe")    # europe, americas, asia

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "cache")
DEMO_DIR = os.path.join(os.path.dirname(__file__), "demo_data")
DEMO_PLAYER = ("DemoPlayer", "DEMO")
MIN_GAME_SECONDS = 300  # below this: remake, stats unusable


class RiotAPIError(Exception):
    pass


def mode() -> str:
    """"demo" (default) or "live", read from RIOT_MODE at each call."""
    value = os.getenv("RIOT_MODE", "demo").strip().lower()
    if value not in ("demo", "live"):
        raise RiotAPIError(f"RIOT_MODE must be 'demo' or 'live', got '{value}'")
    return value


def _url(path: str) -> str:
    return f"https://{REGIONAL}.api.riotgames.com/{path}"


def _get(url: str, params: dict | None = None, _retries: int = 3) -> dict:
    """GET wrapper with timeout, bounded retry on 429 and clear error messages."""
    if not RIOT_API_KEY:
        raise RiotAPIError("RIOT_API_KEY not found: check your .env file, or use RIOT_MODE=demo")

    resp = requests.get(url, headers={"X-Riot-Token": RIOT_API_KEY}, params=params or {}, timeout=15)

    if resp.status_code == 429 and _retries > 0:
        time.sleep(int(resp.headers.get("Retry-After", 1)))
        return _get(url, params, _retries - 1)

    if resp.status_code in (401, 403):
        raise RiotAPIError(
            f"{resp.status_code} — invalid or expired Riot key (24h for dev keys). "
            "Regenerate it at https://developer.riotgames.com"
        )
    if resp.status_code == 404:
        raise RiotAPIError("404 — not found (wrong name/tag, or game not available yet).")
    if resp.status_code == 429:
        raise RiotAPIError("429 — Riot quota exceeded, retry in 2 minutes.")
    if not resp.ok:
        raise RiotAPIError(f"Riot API error {resp.status_code}: {resp.text}")

    return resp.json()


def _get_cached(key: str, url: str) -> dict:
    """A finished match never changes: store it on disk."""
    path = os.path.join(CACHE_DIR, f"{key}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    data = _get(url)
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


@lru_cache(maxsize=32)
def get_puuid(game_name: str, tag_line: str) -> str:
    """Fetch the PUUID (stable identifier) from the Riot ID (name#tag)."""
    url = _url(f"riot/account/v1/accounts/by-riot-id/{quote(game_name)}/{quote(tag_line)}")
    return _get(url)["puuid"]


class _LiveSource:
    def puuid(self, game_name: str, tag_line: str) -> str:
        return get_puuid(game_name, tag_line)

    def match_ids(self, puuid: str, count: int, queue: int = 420) -> list[str]:
        """IDs of the latest matches (Solo/Duo by default; 440 = Flex)."""
        return _get(_url(f"lol/match/v5/matches/by-puuid/{puuid}/ids"), {"count": count, "queue": queue})

    def match_detail(self, match_id: str) -> dict:
        return _get_cached(match_id, _url(f"lol/match/v5/matches/{match_id}"))

    def match_timeline(self, match_id: str) -> dict:
        return _get_cached(f"{match_id}_timeline", _url(f"lol/match/v5/matches/{match_id}/timeline"))


@lru_cache(maxsize=2)
def _load_demo(name: str) -> dict:
    with open(os.path.join(DEMO_DIR, f"{name}.json"), encoding="utf-8") as f:
        return json.load(f)


class _DemoSource:
    """One anonymized sample match; the requested name/tag is ignored."""

    def puuid(self, game_name: str, tag_line: str) -> str:
        return _load_demo("match")["metadata"]["participants"][0]

    def match_ids(self, puuid: str, count: int) -> list[str]:
        return [_load_demo("match")["metadata"]["matchId"]][:max(count, 0)]

    def match_detail(self, match_id: str) -> dict:
        return _load_demo("match")

    def match_timeline(self, match_id: str) -> dict:
        return _load_demo("timeline")


def _source():
    return _LiveSource() if mode() == "live" else _DemoSource()


def simplify_participant(p: dict) -> dict:
    """Extract the useful stats from a raw API participant (used for the
    player AND the 9 other players of the game)."""
    return {
        "summoner_name": p.get("riotIdGameName", p.get("summonerName", "?")),
        "champion": p["championName"],
        "team": "BLUE" if p["teamId"] == 100 else "RED",
        "win": p["win"],
        "role": p.get("teamPosition", "UNKNOWN"),
        "kills": p["kills"],
        "deaths": p["deaths"],
        "assists": p["assists"],
        "cs": p["totalMinionsKilled"] + p["neutralMinionsKilled"],
        "gold_earned": p["goldEarned"],
        "damage_to_champions": p["totalDamageDealtToChampions"],
        "vision_score": p["visionScore"],
        "items": [p.get(f"item{i}", 0) for i in range(7)],
    }


def _find_me(participants: list[dict], puuid: str) -> dict:
    return next(p for p in participants if p["puuid"] == puuid)


def get_last_match(game_name: str, tag_line: str) -> dict | None:
    """
    Latest game with its timeline, for detailed analyses. Returns None if
    there is no game, else {match_id, me (raw participant), participants, timeline}.
    """
    source = _source()
    puuid = source.puuid(game_name, tag_line)
    match_ids = source.match_ids(puuid, count=1)
    if not match_ids:
        return None
    participants = source.match_detail(match_ids[0])["info"]["participants"]
    return {
        "match_id": match_ids[0],
        "me": _find_me(participants, puuid),
        "participants": participants,
        "timeline": source.match_timeline(match_ids[0]),
    }


def get_match_history(game_name: str, tag_line: str, count: int = 10) -> list[dict]:
    """
    High-level "tool" function the agent will call.

    Returns, for each game:
    - "me": the player's stats
    - "opponent": stats of the opposing player in the same role (opposing
      team) — lets you compare "you vs your lane opponent"
    - "all_players": the 10 players of the game (both teams), for a broader
      analysis if needed (comps, who snowballed the game, etc.)
    """
    source = _source()
    puuid = source.puuid(game_name, tag_line)

    results = []
    for mid in source.match_ids(puuid, count=count):
        detail = source.match_detail(mid)
        participants = detail["info"]["participants"]

        if detail["info"]["gameDuration"] < MIN_GAME_SECONDS:
            continue

        me_raw = _find_me(participants, puuid)

        # direct opponent = same role, opposing team
        opponent_raw = next(
            (p for p in participants
             if p["teamId"] != me_raw["teamId"]
             and p.get("teamPosition") == me_raw.get("teamPosition")),
            None,
        )

        results.append({
            "match_id": mid,
            "game_duration_min": round(detail["info"]["gameDuration"] / 60, 1),
            "me": simplify_participant(me_raw),
            "opponent": simplify_participant(opponent_raw) if opponent_raw else None,
            "all_players": [simplify_participant(p) for p in participants],
        })

    return results

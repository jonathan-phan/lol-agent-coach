"""
Client léger pour l'API Riot Games.

Deux bases d'URL différentes chez Riot, c'est le premier piège à connaître :
- "platform" routing (ex: euw1.api.riotgames.com) -> données liées à une région
  précise (summoner, league, etc.)
- "regional" routing (ex: europe.api.riotgames.com) -> données transverses
  (match history, account par riot ID), regroupe plusieurs plateformes

Doc officielle : https://developer.riotgames.com/apis
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
PLATFORM = os.getenv("RIOT_REGION", "euw1")       # euw1, na1, kr, ...
REGIONAL = os.getenv("RIOT_REGIONAL", "europe")    # europe, americas, asia

HEADERS = {"X-Riot-Token": RIOT_API_KEY}

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "cache")


class RiotAPIError(Exception):
    pass


def _get(url: str, params: dict | None = None, _retries: int = 3) -> dict:
    """Wrapper GET avec timeout, retry borné sur 429 et messages d'erreur clairs."""
    if not RIOT_API_KEY:
        raise RiotAPIError("RIOT_API_KEY introuvable : vérifie ton fichier .env")

    resp = requests.get(url, headers=HEADERS, params=params or {}, timeout=15)

    if resp.status_code == 429 and _retries > 0:
        time.sleep(int(resp.headers.get("Retry-After", 1)))
        return _get(url, params, _retries - 1)

    if resp.status_code in (401, 403):
        raise RiotAPIError(
            f"{resp.status_code} — clé Riot invalide ou expirée (24h en dev). "
            "Régénère-la sur https://developer.riotgames.com"
        )
    if resp.status_code == 404:
        raise RiotAPIError("404 — introuvable (pseudo/tag incorrect, ou game pas encore disponible).")
    if resp.status_code == 429:
        raise RiotAPIError("429 — quota Riot dépassé, réessaie dans 2 minutes.")
    if not resp.ok:
        raise RiotAPIError(f"Riot API error {resp.status_code}: {resp.text}")

    return resp.json()


def _get_cached(key: str, url: str) -> dict:
    """Un match terminé ne change jamais : on le stocke sur disque."""
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
    """Récupère le PUUID (identifiant stable) à partir du Riot ID (pseudo#tag)."""
    url = f"https://{REGIONAL}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{quote(game_name)}/{quote(tag_line)}"
    data = _get(url)
    return data["puuid"]

def get_match_timeline(match_id: str) -> dict:
    """Détail minute par minute d'une game."""
    url = f"https://{REGIONAL}.api.riotgames.com/lol/match/v5/matches/{match_id}/timeline"
    return _get_cached(f"{match_id}_timeline", url)


def get_match_ids(puuid: str, count: int = 20, queue: int | None = 420) -> list[str]:
    """Liste les IDs des derniers matchs joués (Solo/Duo par défaut ; 440 = Flex)."""
    url = f"https://{REGIONAL}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids"
    params = {"count": count}
    if queue:
        params["queue"] = queue
    return _get(url, params)


def get_match_detail(match_id: str) -> dict:
    """Détail complet d'un match (tous les joueurs, toutes les stats)."""
    url = f"https://{REGIONAL}.api.riotgames.com/lol/match/v5/matches/{match_id}"
    return _get_cached(match_id, url)


def _simplify_participant(p: dict) -> dict:
    """Extrait les stats utiles d'un participant brut de l'API (utilisé pour
    toi ET pour les 9 autres joueurs de la game)."""
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


def get_match_history(game_name: str, tag_line: str, count: int = 10) -> list[dict]:
    """
    Fonction "outil" de haut niveau que l'agent appellera.

    Retourne, pour chaque game :
    - "me" : tes stats
    - "opponent" : les stats du joueur adverse à ton poste (même rôle, équipe
      d'en face) — c'est lui qui te permet de comparer "toi vs ton lane"
    - "all_players" : les 10 joueurs de la game (les deux équipes), pour une
      analyse plus large si besoin (compo, qui a explosé la game, etc.)
    """
    puuid = get_puuid(game_name, tag_line)
    match_ids = get_match_ids(puuid, count=count)

    results = []
    for mid in match_ids:
        detail = get_match_detail(mid)
        participants = detail["info"]["participants"]

        # remakes : stats inexploitables
        if detail["info"]["gameDuration"] < 300:
            continue

        me_raw = next(p for p in participants if p["puuid"] == puuid)
        me = _simplify_participant(me_raw)

        # adversaire direct = même rôle, équipe adverse
        opponent_raw = next(
            (p for p in participants
             if p["teamId"] != me_raw["teamId"]
             and p.get("teamPosition") == me_raw.get("teamPosition")),
            None,
        )
        opponent = _simplify_participant(opponent_raw) if opponent_raw else None

        all_players = [_simplify_participant(p) for p in participants]

        results.append({
            "match_id": mid,
            "game_duration_min": round(detail["info"]["gameDuration"] / 60, 1),
            "me": me,
            "opponent": opponent,
            "all_players": all_players,
        })

    return results


if __name__ == "__main__":
    # Test rapide en ligne de commande :
    # python src/riot_client.py "TonPseudo" "TAG"
    import sys
    import json

    if len(sys.argv) != 3:
        print("Usage: python riot_client.py <game_name> <tag_line>")
        sys.exit(1)

    history = get_match_history(sys.argv[1], sys.argv[2], count=5)
    print(json.dumps(history, indent=2, ensure_ascii=False))
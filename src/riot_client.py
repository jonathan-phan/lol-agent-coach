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
import time
import requests
from dotenv import load_dotenv

load_dotenv()

RIOT_API_KEY = os.getenv("RIOT_API_KEY")
PLATFORM = os.getenv("RIOT_REGION", "euw1")       # euw1, na1, kr, ...
REGIONAL = os.getenv("RIOT_REGIONAL", "europe")    # europe, americas, asia

HEADERS = {"X-Riot-Token": RIOT_API_KEY}


class RiotAPIError(Exception):
    pass


def _get(url: str, params: dict | None = None) -> dict:
    """Wrapper GET avec gestion basique du rate limit (429)."""
    resp = requests.get(url, headers=HEADERS, params=params or {})

    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", 1))
        time.sleep(retry_after)
        return _get(url, params)

    if resp.status_code == 403:
        raise RiotAPIError(
            "403 Forbidden — ta clé API a probablement expiré (valable 24h "
            "en dev). Régénère-la sur https://developer.riotgames.com"
        )
    if not resp.ok:
        raise RiotAPIError(f"Riot API error {resp.status_code}: {resp.text}")

    return resp.json()


def get_puuid(game_name: str, tag_line: str) -> str:
    """Récupère le PUUID (identifiant stable) à partir du Riot ID (pseudo#tag)."""
    url = f"https://{REGIONAL}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}"
    data = _get(url)
    return data["puuid"]

def get_match_timeline(match_id: str) -> dict:
    """Détail minute par minute d'une game."""
    url = f"https://{REGIONAL}.api.riotgames.com/lol/match/v5/matches/{match_id}/timeline"
    return _get(url)


def get_match_ids(puuid: str, count: int = 20, queue: int | None = None) -> list[str]:
    """Liste les IDs des derniers matchs joués.

    queue=420 -> Solo/Duo ranked, 440 -> Flex ranked (utile pour filtrer plus tard)
    """
    url = f"https://{REGIONAL}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids"
    params = {"count": count}
    if queue:
        params["queue"] = queue
    return _get(url, params)


def get_match_detail(match_id: str) -> dict:
    """Détail complet d'un match (tous les joueurs, toutes les stats)."""
    url = f"https://{REGIONAL}.api.riotgames.com/lol/match/v5/matches/{match_id}"
    return _get(url)


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
        time.sleep(1.2)  # rate limit dev key : 20 req/1s, 100 req/2min -> on reste safe

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
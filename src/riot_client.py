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


def get_match_history(game_name: str, tag_line: str, count: int = 10) -> list[dict]:
    """
    Fonction "outil" de haut niveau que l'agent appellera.
    Retourne une liste simplifiée des dernières games du joueur.
    """
    puuid = get_puuid(game_name, tag_line)
    match_ids = get_match_ids(puuid, count=count)

    results = []
    for mid in match_ids:
        detail = get_match_detail(mid)
        participant = next(
            p for p in detail["info"]["participants"] if p["puuid"] == puuid
        )
        results.append({
            "match_id": mid,
            "champion": participant["championName"],
            "win": participant["win"],
            "kills": participant["kills"],
            "deaths": participant["deaths"],
            "assists": participant["assists"],
            "cs": participant["totalMinionsKilled"] + participant["neutralMinionsKilled"],
            "game_duration_min": round(detail["info"]["gameDuration"] / 60, 1),
            "gold_earned": participant["goldEarned"],
            "role": participant.get("teamPosition", "UNKNOWN"),
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

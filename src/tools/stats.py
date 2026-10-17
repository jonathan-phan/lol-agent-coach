"""
Aggregates the raw data of get_match_history() into statistics usable by the
agent: per-champion winrate, average KDA, comparison against direct
opponents, detection of "bad games".

This module makes no network call — it only transforms data already fetched.
That is deliberate: "fetching the data" (riot_client.py) is separated from
"analyzing the data" (stats.py).
"""
from collections import defaultdict


def _safe_div(a: float, b: float) -> float:
    return round(a / b, 2) if b else 0.0


def _kda(player: dict) -> float:
    return (player["kills"] + player["assists"]) / (player["deaths"] or 1)


def _by_champion(match_history: list[dict]) -> dict:
    games_by_champ = defaultdict(list)
    for m in match_history:
        games_by_champ[m["me"]["champion"]].append(m["me"])
    return {
        champ: {
            "games": len(games),
            "winrate": _safe_div(sum(g["win"] for g in games), len(games)),
            "avg_kda": _safe_div(
                sum(g["kills"] + g["assists"] for g in games),
                sum(g["deaths"] for g in games) or 1,
            ),
        }
        for champ, games in games_by_champ.items()
    }


def _vs_opponent(match_history: list[dict]) -> dict:
    duels = [m for m in match_history if m.get("opponent")]
    if not duels:
        return {"games_with_opponent_data": 0}
    n = len(duels)
    return {
        "games_with_opponent_data": n,
        "gold_diff_avg": round(sum(m["me"]["gold_earned"] - m["opponent"]["gold_earned"] for m in duels) / n, 0),
        "cs_diff_avg": round(sum(m["me"]["cs"] - m["opponent"]["cs"] for m in duels) / n, 1),
        "kda_diff_avg": round(sum(_kda(m["me"]) - _kda(m["opponent"]) for m in duels) / n, 2),
    }


def _likely_reasons(m: dict) -> list[str]:
    me, opp = m["me"], m.get("opponent")
    reasons = []
    if me["deaths"] >= 7:
        reasons.append("many deaths")
    if opp and me["cs"] < opp["cs"] - 20:
        reasons.append("CS behind the direct opponent")
    if opp and me["gold_earned"] < opp["gold_earned"] - 1500:
        reasons.append("gold behind the direct opponent")
    return reasons or ["needs manual review"]


def _worst_games(match_history: list[dict]) -> list[dict]:
    # (win, kda): False < True, so defeats come first
    worst = sorted(match_history, key=lambda m: (m["me"]["win"], _kda(m["me"])))[:3]
    return [
        {
            "match_id": m["match_id"],
            "champion": m["me"]["champion"],
            "win": m["me"]["win"],
            "kda": f"{m['me']['kills']}/{m['me']['deaths']}/{m['me']['assists']}",
            "likely_reasons": _likely_reasons(m),
        }
        for m in worst
    ]


def compute_stats(match_history: list[dict]) -> dict:
    """
    Takes the output of get_match_history() and returns an aggregated summary:

    {
        "overall": { winrate, games_played, avg_kda, avg_cs_per_min, ... },
        "by_champion": { "Ezreal": { winrate, games, avg_kda }, ... },
        "vs_opponent_avg": { "gold_diff_avg", "cs_diff_avg", "kda_diff_avg" },
        "worst_games": [ ... the 3 worst games (by KDA, defeats first) with likely reasons ... ]
    }
    """
    if not match_history:
        return {"error": "No game in the provided history."}

    n = len(match_history)
    wins = sum(1 for m in match_history if m["me"]["win"])

    total_kills = sum(m["me"]["kills"] for m in match_history)
    total_deaths = sum(m["me"]["deaths"] for m in match_history)
    total_assists = sum(m["me"]["assists"] for m in match_history)
    total_cs = sum(m["me"]["cs"] for m in match_history)
    total_minutes = sum(m["game_duration_min"] for m in match_history)

    overall = {
        "games_played": n,
        "winrate": _safe_div(wins, n),
        "avg_kda": _safe_div(total_kills + total_assists, total_deaths or 1),
        "avg_kills": _safe_div(total_kills, n),
        "avg_deaths": _safe_div(total_deaths, n),
        "avg_assists": _safe_div(total_assists, n),
        "avg_cs_per_min": _safe_div(total_cs, total_minutes),
    }

    return {
        "overall": overall,
        "by_champion": _by_champion(match_history),
        "vs_opponent_avg": _vs_opponent(match_history),
        "worst_games": _worst_games(match_history),
    }
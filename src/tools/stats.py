"""
Agrège les données brutes de get_match_history() en statistiques exploitables
par l'agent : winrate par champion, KDA moyen, comparaison vs adversaires
directs, détection de "games ratées".

Ce module ne fait aucun appel réseau — il transforme juste des données déjà
récupérées. C'est volontaire : on sépare "aller chercher la donnée" (riot_client.py)
de "analyser la donnée" (stats.py), pour que l'agent puisse appeler ces deux
outils indépendamment selon la question posée.
"""
from collections import defaultdict


def _safe_div(a: float, b: float) -> float:
    return round(a / b, 2) if b else 0.0


def compute_stats(match_history: list[dict]) -> dict:
    """
    Prend la sortie de get_match_history() et retourne un résumé agrégé :

    {
        "overall": { winrate, games_played, avg_kda, avg_cs_per_min, ... },
        "by_champion": { "Ezreal": { winrate, games, avg_kda, ... }, ... },
        "vs_opponent_avg": { "gold_diff_avg", "cs_diff_avg", "kda_diff_avg" },
        "worst_games": [ ... les 3 pires games (par KDA) avec le pourquoi ... ]
    }
    """
    if not match_history:
        return {"error": "Aucune game dans l'historique fourni."}

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

    # --- Stats par champion ---
    by_champion_raw = defaultdict(list)
    for m in match_history:
        by_champion_raw[m["me"]["champion"]].append(m)

    by_champion = {}
    for champ, games in by_champion_raw.items():
        g_wins = sum(1 for g in games if g["me"]["win"])
        g_kills = sum(g["me"]["kills"] for g in games)
        g_deaths = sum(g["me"]["deaths"] for g in games)
        g_assists = sum(g["me"]["assists"] for g in games)
        by_champion[champ] = {
            "games": len(games),
            "winrate": _safe_div(g_wins, len(games)),
            "avg_kda": _safe_div(g_kills + g_assists, g_deaths or 1),
        }

    # --- Comparaison vs adversaire direct (uniquement games où on a l'opponent) ---
    duels = [m for m in match_history if m.get("opponent")]
    if duels:
        gold_diffs = [m["me"]["gold_earned"] - m["opponent"]["gold_earned"] for m in duels]
        cs_diffs = [m["me"]["cs"] - m["opponent"]["cs"] for m in duels]
        my_kda = [
            (m["me"]["kills"] + m["me"]["assists"]) / (m["me"]["deaths"] or 1)
            for m in duels
        ]
        opp_kda = [
            (m["opponent"]["kills"] + m["opponent"]["assists"]) / (m["opponent"]["deaths"] or 1)
            for m in duels
        ]
        vs_opponent_avg = {
            "games_with_opponent_data": len(duels),
            "gold_diff_avg": round(sum(gold_diffs) / len(duels), 0),
            "cs_diff_avg": round(sum(cs_diffs) / len(duels), 1),
            "kda_diff_avg": round(
                sum(my_kda) / len(duels) - sum(opp_kda) / len(duels), 2
            ),
        }
    else:
        vs_opponent_avg = {"games_with_opponent_data": 0}

    # --- Pires games (les 3 plus mauvais KDA, priorité aux défaites) ---
    def game_score(m):
        kda = (m["me"]["kills"] + m["me"]["assists"]) / (m["me"]["deaths"] or 1)
        return (m["me"]["win"], kda)  # False < True donc les défaites sortent en premier

    worst = sorted(match_history, key=game_score)[:3]
    worst_games = []
    for m in worst:
        me = m["me"]
        reasons = []
        if me["deaths"] >= 7:
            reasons.append("beaucoup de morts")
        if m.get("opponent") and me["cs"] < m["opponent"]["cs"] - 20:
            reasons.append("CS en retard sur l'adversaire direct")
        if m.get("opponent") and me["gold_earned"] < m["opponent"]["gold_earned"] - 1500:
            reasons.append("gold en retard sur l'adversaire direct")
        worst_games.append({
            "match_id": m["match_id"],
            "champion": me["champion"],
            "win": me["win"],
            "kda": f"{me['kills']}/{me['deaths']}/{me['assists']}",
            "likely_reasons": reasons or ["à examiner manuellement"],
        })

    return {
        "overall": overall,
        "by_champion": by_champion,
        "vs_opponent_avg": vs_opponent_avg,
        "worst_games": worst_games,
    }


if __name__ == "__main__":
    # Test rapide : enchaîne get_match_history() -> compute_stats()
    # python src/tools/stats.py "TonPseudo" "TAG"
    import sys
    import json
    import os

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from riot_client import get_match_history

    if len(sys.argv) != 3:
        print("Usage: python stats.py <game_name> <tag_line>")
        sys.exit(1)

    history = get_match_history(sys.argv[1], sys.argv[2], count=10)
    stats = compute_stats(history)
    print(json.dumps(stats, indent=2, ensure_ascii=False))
"""
Analyse UNE seule game (la dernière par défaut) — pensé pour un usage rapide
entre deux games d'une session, contrairement à compute_stats() qui regarde
des tendances sur plusieurs games.

Usage direct :
    python src/tools/last_game.py "TonPseudo" "TAG"
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from riot_client import get_match_history  # noqa: E402


def analyze_last_game(game_name: str, tag_line: str) -> dict:
    """Récupère et diagnostique uniquement la toute dernière game jouée."""
    history = get_match_history(game_name, tag_line, count=1)
    if not history:
        return {"error": "Aucune game trouvée."}

    match = history[0]
    me = match["me"]
    opponent = match.get("opponent")

    diagnosis = []

    if not me["win"]:
        diagnosis.append("Défaite.")
    else:
        diagnosis.append("Victoire.")

    if me["deaths"] >= 7:
        diagnosis.append(
            f"Beaucoup de morts ({me['deaths']}) — regarde si elles sont "
            "groupées à un moment précis (teamfight raté ? gank subi répété ?)."
        )

    if opponent:
        gold_diff = me["gold_earned"] - opponent["gold_earned"]
        cs_diff = me["cs"] - opponent["cs"]

        if gold_diff < -1000:
            diagnosis.append(
                f"Tu as terminé {abs(gold_diff)} gold derrière ton adversaire "
                f"direct ({opponent['champion']}) — écart significatif."
            )
        elif gold_diff > 1000:
            diagnosis.append(
                f"Tu as terminé {gold_diff} gold devant ton adversaire direct "
                f"({opponent['champion']}) — bon signe côté lane/farm."
            )

        if cs_diff < -15:
            diagnosis.append(
                f"CS en retard de {abs(cs_diff)} sur ton adversaire — "
                "possible souci de farm ou trop de temps hors lane."
            )

    if not diagnosis or len(diagnosis) == 1:
        diagnosis.append("Rien d'alarmant détecté automatiquement — regarde le détail ci-dessous.")

    return {
        "match_id": match["match_id"],
        "champion": me["champion"],
        "role": me["role"],
        "win": me["win"],
        "kda": f"{me['kills']}/{me['deaths']}/{me['assists']}",
        "cs": me["cs"],
        "game_duration_min": match["game_duration_min"],
        "opponent_champion": opponent["champion"] if opponent else None,
        "diagnosis": diagnosis,
    }


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python last_game.py <game_name> <tag_line>")
        sys.exit(1)

    result = analyze_last_game(sys.argv[1], sys.argv[2])
    print(json.dumps(result, indent=2, ensure_ascii=False))
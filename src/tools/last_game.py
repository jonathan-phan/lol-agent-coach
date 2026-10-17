"""
Analyze ONE game (the latest) — meant for quick use between two games of a
session, unlike compute_stats() which looks at trends over several games.
"""
from riot_client import get_match_history


def _diagnose(me: dict, opponent: dict | None) -> list[str]:
    diagnosis = ["Victory." if me["win"] else "Defeat."]

    if me["deaths"] >= 7:
        diagnosis.append(
            f"Many deaths ({me['deaths']}) — check whether they cluster at a "
            "specific moment (failed teamfight? repeated ganks?)."
        )

    if opponent:
        gold_diff = me["gold_earned"] - opponent["gold_earned"]
        cs_diff = me["cs"] - opponent["cs"]

        if gold_diff < -1000:
            diagnosis.append(
                f"You finished {abs(gold_diff)} gold behind your direct "
                f"opponent ({opponent['champion']}) — significant gap."
            )
        elif gold_diff > 1000:
            diagnosis.append(
                f"You finished {gold_diff} gold ahead of your direct "
                f"opponent ({opponent['champion']}) — good sign for lane/farm."
            )

        if cs_diff < -15:
            diagnosis.append(
                f"CS behind by {abs(cs_diff)} against your opponent — "
                "possible farming issue or too much time away from lane."
            )

    if len(diagnosis) == 1:
        diagnosis.append("Nothing alarming detected automatically — see the details below.")
    return diagnosis


def analyze_last_game(game_name: str, tag_line: str) -> dict:
    """Fetch and diagnose only the very last game played."""
    history = get_match_history(game_name, tag_line, count=1)
    if not history:
        return {"error": "No game found."}

    match = history[0]
    me = match["me"]
    opponent = match["opponent"]

    return {
        "match_id": match["match_id"],
        "champion": me["champion"],
        "role": me["role"],
        "win": me["win"],
        "kda": f"{me['kills']}/{me['deaths']}/{me['assists']}",
        "cs": me["cs"],
        "game_duration_min": match["game_duration_min"],
        "opponent_champion": opponent["champion"] if opponent else None,
        "diagnosis": _diagnose(me, opponent),
    }

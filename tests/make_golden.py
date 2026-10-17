"""Regenerate golden.json from the current code (demo data): python tests/make_golden.py. Review the diff!"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

if __name__ == "__main__":
    os.environ["RIOT_MODE"] = "demo"
    import riot_client
    from tools.last_game import analyze_last_game
    from tools.phase_analysis import analyze_last_game_by_phase
    from tools.stats import compute_stats

    name, tag = riot_client.DEMO_PLAYER
    history = riot_client.get_match_history(name, tag, count=1)
    out = {
        "history": history,
        "last_game": analyze_last_game(name, tag),
        "phase": analyze_last_game_by_phase(name, tag),
        "stats": compute_stats(history),
    }
    with open(os.path.join(FIXTURES, "golden.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)

from conftest import load_fixture
from tools.last_game import analyze_last_game
from tools.phase_analysis import analyze_last_game_by_phase
from tools.stats import compute_stats
import riot_client

GOLDEN = load_fixture("golden.json")


def test_match_history_matches_golden(riot):
    history = riot_client.get_match_history(riot["game_name"], riot["tag_line"], count=1)
    assert history == GOLDEN["history"]


def test_match_history_skips_remakes(riot):
    riot["match"]["info"]["gameDuration"] = 120
    assert riot_client.get_match_history(riot["game_name"], riot["tag_line"]) == []


def test_analyze_last_game_matches_golden(riot):
    assert analyze_last_game(riot["game_name"], riot["tag_line"]) == GOLDEN["last_game"]


def test_analyze_last_game_without_games(riot):
    riot["match_ids"].clear()
    assert analyze_last_game(riot["game_name"], riot["tag_line"]) == {"error": "No game found."}


def test_phase_analysis_matches_golden(riot):
    assert analyze_last_game_by_phase(riot["game_name"], riot["tag_line"]) == GOLDEN["phase"]


def test_phase_analysis_without_games(riot):
    riot["match_ids"].clear()
    assert analyze_last_game_by_phase(riot["game_name"], riot["tag_line"]) == {"error": "No game found."}


def test_stats_matches_golden(riot):
    history = riot_client.get_match_history(riot["game_name"], riot["tag_line"], count=1)
    assert compute_stats(history) == GOLDEN["stats"]


def test_stats_empty_history():
    assert "error" in compute_stats([])


def _game(champion, win, kills, deaths, assists, opponent=None):
    me = {"champion": champion, "win": win, "kills": kills, "deaths": deaths,
          "assists": assists, "cs": 100, "gold_earned": 10000}
    return {"match_id": champion, "game_duration_min": 20.0, "me": me, "opponent": opponent}


def test_stats_zero_deaths_does_not_divide_by_zero():
    stats = compute_stats([_game("Ezreal", True, 5, 0, 5)])
    assert stats["overall"]["avg_kda"] == 10.0
    assert stats["vs_opponent_avg"] == {"games_with_opponent_data": 0}


def test_stats_worst_games_puts_defeats_first_with_reasons():
    opponent = {"kills": 0, "deaths": 1, "assists": 0, "cs": 200, "gold_earned": 15000}
    games = [
        _game("Win", True, 1, 1, 1),
        _game("Loss", False, 1, 8, 1, opponent),
    ]
    worst = compute_stats(games)["worst_games"]
    assert worst[0]["champion"] == "Loss"
    assert worst[0]["likely_reasons"] == [
        "many deaths",
        "CS behind the direct opponent",
        "gold behind the direct opponent",
    ]
    assert worst[1]["likely_reasons"] == ["needs manual review"]

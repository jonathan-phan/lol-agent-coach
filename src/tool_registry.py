"""
Tool registry: each tool is defined ONCE (description seen by the LLM +
Python function) and the function-calling schema is derived from it.

Interface: TOOLS_SCHEMA (what the LLM reads) and run_tool(name, args).
"""
from riot_client import get_match_history
from tools.last_game import analyze_last_game
from tools.phase_analysis import analyze_last_game_by_phase
from tools.stats import compute_stats

DEFAULT_COUNT = 10

_TOOLS = {
    "get_match_history": {
        "description": (
            "Fetches the player's last N games, with for each game: their own "
            "stats, those of their direct opponent (same role, opposing team), "
            "and those of all 10 players. Useful for a raw overview, but prefer "
            "compute_stats for already-aggregated trends."
        ),
        "count_description": "Number of games to fetch (default 10)",
        "run": lambda game_name, tag_line, count=DEFAULT_COUNT: get_match_history(game_name, tag_line, count=count),
    },
    "compute_stats": {
        "description": (
            "Aggregates several games into statistics: overall winrate, average "
            "KDA, per-champion stats, average comparison against direct "
            "opponents, and the 3 worst games. Use it for questions about "
            "TRENDS ('why am I losing lately', 'am I better on a given "
            "champion'), not for one specific game."
        ),
        "count_description": "Number of games to analyze (default 10)",
        "run": lambda game_name, tag_line, count=DEFAULT_COUNT: compute_stats(
            get_match_history(game_name, tag_line, count=count)
        ),
    },
    "analyze_last_game": {
        "description": (
            "Quick diagnosis of the very last game played only: result, KDA, "
            "gold/CS comparison with the direct opponent. Use it for questions "
            "like 'what happened in my last game', right after finishing a match."
        ),
        "run": analyze_last_game,
    },
    "analyze_last_game_by_phase": {
        "description": (
            "Splits the very last game into 5 phases (laning 0-10min, early "
            "10-14min, mid 14-25min, late 25-30min, ultra_late 30min+), with "
            "kills/deaths/assists/gold gained for all 10 players in each phase. "
            "Also provides milestones: total CS, gold and level of the player and "
            "of the direct opponent at 10, 15 and 20 minutes, with the gap between "
            "them (use it for laning questions such as 'was I ahead at 10 min'; "
            "minutes the game never reached are absent). "
            "Also provides my_kill_events and my_death_events: for EACH "
            "death/kill of the player, the exact timestamp, the opposing "
            "champion involved, and an APPROXIMATE map zone (e.g. 'river or mid "
            "lane (approximate)'). These zones are coordinate-based estimates, "
            "not certain data: never present them as absolute certainty. Each "
            "death also includes other_kills_within_15s (other KILLS within 15s, "
            "to tell a skirmish from a 1v1). WARNING: an ally missing from that "
            "list does NOT prove they were physically absent: there is no "
            "presence data, only kills. Never invent details beyond what is "
            "provided (no spell used, no fight description). Use it to "
            "understand WHEN and where exactly a game turned, not just the "
            "final result. Slower than the other tools (fetches the full "
            "timeline)."
        ),
        "run": analyze_last_game_by_phase,
    },
}


def _schema(name: str, tool: dict) -> dict:
    properties = {
        "game_name": {"type": "string", "description": "Riot name (before the #)"},
        "tag_line": {"type": "string", "description": "Riot tag (after the #)"},
    }
    if "count_description" in tool:
        properties["count"] = {"type": "integer", "description": tool["count_description"]}
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": tool["description"],
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": ["game_name", "tag_line"],
            },
        },
    }


TOOLS_SCHEMA = [_schema(name, tool) for name, tool in _TOOLS.items()]


def run_tool(name: str, tool_input: dict) -> dict:
    """Run the tool requested by the LLM; errors are returned to the LLM, not raised."""
    if name not in _TOOLS:
        return {"error": f"Unknown tool: {name}"}
    try:
        return _TOOLS[name]["run"](**tool_input)
    except Exception as e:
        return {"error": f"Error while running {name}: {e}"}

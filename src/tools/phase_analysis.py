"""
Split the last game into phases and show where it turned — unlike
last_game.py, which only gives the final result.

Phases (classic LoL split, adjustable):
- laning_phase: 0 to 10 min
- early:        10 to 14 min
- mid:          14 to 25 min
- late:         25 to 30 min
- ultra_late:   30 min and beyond

Also gives milestones: CS/gold/level at 10, 15 and 20 min against the direct opponent.
"""
from riot_client import get_last_match, simplify_participant

PHASE_ENDS_MIN = (("laning_phase", 10), ("early", 14), ("mid", 25), ("late", 30))
LAST_PHASE = "ultra_late"
PHASE_NAMES = [name for name, _ in PHASE_ENDS_MIN] + [LAST_PHASE]
SKIRMISH_WINDOW_MS = 15000
MILESTONE_MINUTES = (10, 15, 20)
CS_LAG_AT_10 = 10  # CS behind at 10 min worth flagging
GOLD_GAP_SHIFT = 1000  # change of the gold gap between first and last milestone worth flagging


def _approximate_zone(x: int, y: int) -> str:
    """
    APPROXIMATE map zone from raw coordinates (0 to ~14800 on each axis, ally
    base bottom-left, enemy base top-right). A simple threshold heuristic, not
    Riot data: "approximate" stays in the result so the agent does not present
    it as a certainty.
    """
    diag = x - y  # close to 0 -> close to the diagonal (mid/river)
    if -2000 < diag < 2000:
        if 6000 < x < 9000 and 6000 < y < 9000:
            return "river (near mid)"
        return "river or mid lane (approximate)"
    if diag >= 2000:
        return "bot lane / lower jungle (approximate)"
    return "top lane / upper jungle (approximate)"


def _zone(position: dict) -> str:
    if not position:
        return "unknown"
    return _approximate_zone(position.get("x", 0), position.get("y", 0))


def _format_timestamp(ms: int) -> str:
    minutes, seconds = divmod(ms // 1000, 60)
    return f"{minutes}:{seconds:02d}"


def _phase_for_timestamp(ms: int) -> str:
    minute = ms / 60000
    for name, end in PHASE_ENDS_MIN:
        if minute < end:
            return name
    return LAST_PHASE


def _tally_phases(frames: list[dict], participant_ids) -> tuple[dict, list[dict]]:
    """Kills/deaths/assists/gold per player and phase, plus every kill of the game."""
    phases = {
        phase: {
            pid: {"kills": 0, "deaths": 0, "assists": 0, "gold_start": None, "gold_end": None}
            for pid in participant_ids
        }
        for phase in PHASE_NAMES
    }
    kill_events = []

    for frame in frames:
        phase = _phase_for_timestamp(frame["timestamp"])
        for pid_str, pframe in frame["participantFrames"].items():
            bucket = phases[phase][int(pid_str)]
            if bucket["gold_start"] is None:
                bucket["gold_start"] = pframe["totalGold"]
            bucket["gold_end"] = pframe["totalGold"]

        for event in frame.get("events", []):
            if event.get("type") != "CHAMPION_KILL":
                continue
            event_phase = _phase_for_timestamp(event["timestamp"])
            killer, victim = event.get("killerId"), event.get("victimId")
            assists = event.get("assistingParticipantIds", [])
            bucket = phases[event_phase]

            if killer in bucket:
                bucket[killer]["kills"] += 1
            if victim in bucket:
                bucket[victim]["deaths"] += 1
            for a in assists:
                if a in bucket:
                    bucket[a]["assists"] += 1

            kill_events.append({
                "timestamp_ms": event["timestamp"],
                "phase": event_phase,
                "killer": killer,
                "victim": victim,
                "assists": assists,
                "position": event.get("position", {}),
            })

    return phases, kill_events


def _my_events(kill_events: list[dict], me_id: int, info: dict) -> tuple[list[dict], list[dict]]:
    """Detail of each of the player's kills and deaths, with skirmish context."""
    champions = {pid: i["champion"] for pid, i in info.items()}
    kills, deaths = [], []

    for e in kill_events:
        killer, victim = e["killer"], e["victim"]
        assisted_by = [champions[a] for a in e["assists"] if a in champions]
        where = {
            "timestamp": _format_timestamp(e["timestamp_ms"]),
            "phase": e["phase"],
            "position_raw": e["position"],
            "approximate_zone": _zone(e["position"]),
        }
        if killer == me_id and victim in champions:
            kills.append({**where, "victim_champion": champions[victim], "assisted_by": assisted_by})
        if victim == me_id and killer in champions:
            nearby = [
                {
                    "timestamp": _format_timestamp(o["timestamp_ms"]),
                    "killer_champion": champions.get(o["killer"], "?"),
                    "victim_champion": champions.get(o["victim"], "?"),
                }
                for o in kill_events
                if abs(o["timestamp_ms"] - e["timestamp_ms"]) <= SKIRMISH_WINDOW_MS
                and not (o["timestamp_ms"] == e["timestamp_ms"] and o["victim"] == me_id)
            ]
            deaths.append({
                **where,
                "killer_champion": champions[killer],
                "killer_assisted_by": assisted_by,
                "other_kills_within_15s": nearby,
                "was_skirmish": len(nearby) > 0,
            })

    return kills, deaths


def _snapshot(pframe: dict) -> dict:
    return {
        "cs": pframe["minionsKilled"] + pframe["jungleMinionsKilled"],
        "gold": pframe["totalGold"],
        "level": pframe["level"],
    }


def _milestones(frames: list[dict], info: dict, me_id: int) -> list[dict]:
    """Total CS/gold/level at fixed minutes, for the player and the direct opponent.
    Minutes the game never reached are omitted."""
    opponent_id = next(
        (pid for pid, i in info.items()
         if i["role"] == info[me_id]["role"] and i["team"] != info[me_id]["team"]),
        None,
    )
    milestones = []
    for minute in MILESTONE_MINUTES:
        frame = next((f for f in frames if f["timestamp"] >= minute * 60000), None)
        if frame is None:
            break
        pframes = frame["participantFrames"]
        entry = {"minute": minute, "me": _snapshot(pframes[str(me_id)])}
        if opponent_id is not None:
            entry["opponent_champion"] = info[opponent_id]["champion"]
            entry["opponent"] = _snapshot(pframes[str(opponent_id)])
            entry["diff"] = {k: entry["me"][k] - entry["opponent"][k] for k in entry["me"]}
        milestones.append(entry)
    return milestones


def _diagnose_milestones(milestones: list[dict]) -> list[str]:
    with_diff = [m for m in milestones if "diff" in m]
    diagnosis = []

    at_10 = next((m for m in with_diff if m["minute"] == 10), None)
    if at_10 and at_10["diff"]["cs"] <= -CS_LAG_AT_10:
        diagnosis.append(
            f"At 10 min you were {abs(at_10['diff']['cs'])} CS behind your direct opponent "
            f"({at_10['opponent_champion']}) — the laning phase is a priority to work on."
        )

    if len(with_diff) >= 2:
        first, last = with_diff[0], with_diff[-1]
        shift = last["diff"]["gold"] - first["diff"]["gold"]
        gap = f"{first['diff']['gold']:+d} gold at {first['minute']} min to {last['diff']['gold']:+d} at {last['minute']} min"
        if shift <= -GOLD_GAP_SHIFT:
            diagnosis.append(f"Your gold gap against your opponent widened: {gap}.")
        elif shift >= GOLD_GAP_SHIFT:
            diagnosis.append(f"Your gold gap against your opponent improved: {gap}.")

    return diagnosis


def _summarize(phases: dict, info: dict, me_id: int) -> dict:
    by_phase = {}
    for phase, players in phases.items():
        by_phase[phase] = []
        for pid, data in players.items():
            has_gold = data["gold_start"] is not None and data["gold_end"] is not None
            by_phase[phase].append({
                "summoner_name": info[pid]["summoner_name"],
                "champion": info[pid]["champion"],
                "role": info[pid]["role"],
                "team": info[pid]["team"],
                "is_me": pid == me_id,
                "kills": data["kills"],
                "deaths": data["deaths"],
                "assists": data["assists"],
                "gold_gained": data["gold_end"] - data["gold_start"] if has_gold else None,
            })
    return by_phase


def _diagnose(by_phase: dict, milestones: list[dict], me: dict) -> list[str]:
    mine = {phase: next(p for p in players if p["is_me"]) for phase, players in by_phase.items()}
    worst = max(mine, key=lambda phase: mine[phase]["deaths"])
    diagnosis = _diagnose_milestones(milestones)

    if mine[worst]["deaths"] >= 2:
        diagnosis.append(
            f"Your costliest phase is {worst} ({mine[worst]['deaths']} deaths)."
        )
    if mine["laning_phase"]["deaths"] == 0 and mine[LAST_PHASE]["deaths"] >= 3:
        diagnosis.append(
            "Clean laning phase (0 deaths) but a big drop-off late in the game — "
            "possible teamfight positioning issue rather than a laning issue."
        )

    opponent = next(
        (p for p in by_phase[worst] if p["role"] == me["role"] and p["team"] != me["team"]),
        None,
    )
    if opponent and opponent["gold_gained"] is not None and mine[worst]["gold_gained"] is not None:
        gold_diff = mine[worst]["gold_gained"] - opponent["gold_gained"]
        if gold_diff < -500:
            diagnosis.append(
                f"In the {worst} phase, your direct opponent ({opponent['champion']}) "
                f"gained {abs(gold_diff)} more gold than you — a significant gap in that specific phase."
            )

    return diagnosis or ["No clear turning point detected automatically — see the per-phase details below."]


def analyze_last_game_by_phase(game_name: str, tag_line: str) -> dict:
    match = get_last_match(game_name, tag_line)
    if not match:
        return {"error": "No game found."}

    me_raw = match["me"]
    me_id = me_raw["participantId"]
    info = {p["participantId"]: simplify_participant(p) for p in match["participants"]}
    my_team = info[me_id]["team"]

    frames = match["timeline"]["info"]["frames"]
    phases, kill_events = _tally_phases(frames, info)
    milestones = _milestones(frames, info, me_id)
    my_kill_events, my_death_events = _my_events(kill_events, me_id, info)
    by_phase = _summarize(phases, info, me_id)

    def teammate(i: dict) -> dict:
        return {"summoner_name": i["summoner_name"], "champion": i["champion"], "role": i["role"]}

    # Explicit teams: the LLM would otherwise cross-check each player's "team" field itself.
    return {
        "match_id": match["match_id"],
        "champion": me_raw["championName"],
        "win": me_raw["win"],
        "my_team_color": my_team,
        "teams": {
            "my_allies": [teammate(i) for pid, i in info.items() if i["team"] == my_team and pid != me_id],
            "enemy_team": [teammate(i) for i in info.values() if i["team"] != my_team],
        },
        "milestones": milestones,
        "by_phase": by_phase,
        "my_kill_events": my_kill_events,
        "my_death_events": my_death_events,
        "diagnosis": _diagnose(by_phase, milestones, info[me_id]),
    }

import copy

from tools.phase_analysis import analyze_last_game_by_phase


def _frame_at(timeline, minute):
    return next(f for f in timeline["info"]["frames"] if f["timestamp"] >= minute * 60000)


def _ids(riot):
    """(my participantId, direct opponent participantId) in the fixture match."""
    participants = riot["match"]["info"]["participants"]
    me = participants[0]
    opponent = next(p for p in participants
                    if p["teamId"] != me["teamId"] and p["teamPosition"] == me["teamPosition"])
    return str(me["participantId"]), str(opponent["participantId"])


def test_milestones_report_cs_gold_level_and_gap(riot):
    me_id, opp_id = _ids(riot)
    result = analyze_last_game_by_phase(riot["game_name"], riot["tag_line"])

    assert [m["minute"] for m in result["milestones"]] == [10, 15, 20]
    at_10 = result["milestones"][0]
    frame = _frame_at(riot["timeline"], 10)["participantFrames"]
    assert at_10["me"]["cs"] == frame[me_id]["minionsKilled"] + frame[me_id]["jungleMinionsKilled"]
    assert at_10["opponent"]["gold"] == frame[opp_id]["totalGold"]
    assert at_10["diff"]["gold"] == frame[me_id]["totalGold"] - frame[opp_id]["totalGold"]
    assert at_10["diff"]["level"] == frame[me_id]["level"] - frame[opp_id]["level"]


def test_milestones_omit_minutes_the_game_never_reached(riot):
    riot["timeline"] = copy.deepcopy(riot["timeline"])
    riot["timeline"]["info"]["frames"] = riot["timeline"]["info"]["frames"][:12]
    result = analyze_last_game_by_phase(riot["game_name"], riot["tag_line"])
    assert [m["minute"] for m in result["milestones"]] == [10]


def test_diagnosis_flags_cs_lag_at_10_min(riot):
    me_id, opp_id = _ids(riot)
    riot["timeline"] = copy.deepcopy(riot["timeline"])
    pframes = _frame_at(riot["timeline"], 10)["participantFrames"]
    pframes[me_id]["minionsKilled"] = pframes[opp_id]["minionsKilled"] + pframes[opp_id]["jungleMinionsKilled"] - 25 - pframes[me_id]["jungleMinionsKilled"]
    result = analyze_last_game_by_phase(riot["game_name"], riot["tag_line"])
    assert any("25 CS behind" in line for line in result["diagnosis"])


def test_diagnosis_flags_widening_gold_gap(riot):
    me_id, opp_id = _ids(riot)
    riot["timeline"] = copy.deepcopy(riot["timeline"])
    first = _frame_at(riot["timeline"], 10)["participantFrames"]
    last = _frame_at(riot["timeline"], 20)["participantFrames"]
    first[me_id]["totalGold"] = first[opp_id]["totalGold"]
    last[me_id]["totalGold"] = last[opp_id]["totalGold"] - 2000
    result = analyze_last_game_by_phase(riot["game_name"], riot["tag_line"])
    assert any("gold gap against your opponent widened: +0 gold at 10 min to -2000 at 20 min" in line
               for line in result["diagnosis"])

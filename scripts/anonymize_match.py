"""
Anonymize a real match + timeline (Riot API JSON) into demo data.

Usage: python scripts/anonymize_match.py <match.json> <timeline.json> [out_dir]

Every player identifier (PUUID, Riot ID, summoner ID) is replaced by a neutral
placeholder; participant 1 becomes the demo player. The raw input files must
never be committed.
"""
import json
import os
import sys

DEMO_TAG = "DEMO"
DEMO_MATCH_ID = "DEMO_1"
DEFAULT_OUT = os.path.join(os.path.dirname(__file__), "..", "src", "demo_data")


def _replace_strings(node, mapping: dict):
    if isinstance(node, dict):
        return {k: 1 if k == "gameId" else _replace_strings(v, mapping) for k, v in node.items()}
    if isinstance(node, list):
        return [_replace_strings(v, mapping) for v in node]
    if isinstance(node, str):
        return mapping.get(node, node)
    return node


def anonymize(match: dict, timeline: dict) -> tuple[dict, dict]:
    mapping = {match["metadata"]["matchId"]: DEMO_MATCH_ID}
    for p in match["info"]["participants"]:
        n = p["participantId"]
        mapping[p["puuid"]] = f"demo-puuid-{n}"
        if p.get("summonerId"):
            mapping[p["summonerId"]] = f"demo-summoner-{n}"

    match, timeline = _replace_strings(match, mapping), _replace_strings(timeline, mapping)

    for p in match["info"]["participants"]:
        n = p["participantId"]
        p["riotIdGameName"] = "DemoPlayer" if n == 1 else f"Player{n}"
        p["riotIdTagline"] = DEMO_TAG
        p["summonerName"] = ""
    match["info"]["gameName"] = "demo"
    return match, timeline


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        print(__doc__)
        sys.exit(1)

    with open(sys.argv[1], encoding="utf-8") as f:
        raw_match = json.load(f)
    with open(sys.argv[2], encoding="utf-8") as f:
        raw_timeline = json.load(f)

    out_dir = sys.argv[3] if len(sys.argv) == 4 else DEFAULT_OUT
    os.makedirs(out_dir, exist_ok=True)
    for name, data in zip(("match.json", "timeline.json"), anonymize(raw_match, raw_timeline)):
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    print(f"Demo data written to {os.path.abspath(out_dir)}")

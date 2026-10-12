"""
Découpe la dernière game en 3 phases (early/mid/late) et montre où ça a
basculé — contrairement à last_game.py qui ne donne que le résultat final.

Phases (découpage classique LoL, ajustable) :
- EARLY : 0 à 14 min (laning phase)
- MID   : 14 à 25 min (rotations, premiers objectifs majeurs)
- LATE  : 25 min et + (teamfights, fin de game)

Usage direct :
    python src/tools/phase_analysis.py "TonPseudo" "TAG"
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from riot_client import (  # noqa: E402
    get_puuid,
    get_match_ids,
    get_match_detail,
    get_match_timeline,
)

LANING_END_MIN = 10
EARLY_END_MIN = 14
MID_END_MIN = 25
LATE_END_MIN = 30


def _approximate_zone(x: int, y: int) -> str:
    """
    Classification APPROXIMATIVE de la zone de la carte à partir des
    coordonnées brutes (0 à ~14800 sur chaque axe, base alliée en bas à
    gauche, base ennemie en haut à droite). C'est une heuristique simple
    par seuils, pas une donnée officielle Riot — d'où le mot "approximatif"
    conservé dans le résultat, pour que l'agent ne présente pas ça comme
    une certitude absolue.
    """
    diag = x - y  # proche de 0 -> proche de la diagonale (mid/river)
    if -2000 < diag < 2000:
        if 6000 < x < 9000 and 6000 < y < 9000:
            return "river (proche mid)"
        return "river ou mid lane (approximatif)"
    if diag >= 2000:
        return "bot lane / jungle bas (approximatif)"
    return "top lane / jungle haut (approximatif)"


def _format_timestamp(ms: int) -> str:
    total_seconds = ms // 1000
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:02d}"


def _phase_for_timestamp(ms: int) -> str:
    minute = ms / 60000
    if minute < LANING_END_MIN:
        return "laning_phase"
    elif minute < EARLY_END_MIN:
        return "early"
    elif minute < MID_END_MIN:
        return "mid"
    elif minute < LATE_END_MIN:
        return "late"
    return "ultra_late"


def analyze_last_game_by_phase(game_name: str, tag_line: str) -> dict:
    puuid = get_puuid(game_name, tag_line)
    match_ids = get_match_ids(puuid, count=1)
    if not match_ids:
        return {"error": "Aucune game trouvée."}
    match_id = match_ids[0]

    detail = get_match_detail(match_id)
    participants = detail["info"]["participants"]
    me_raw = next(p for p in participants if p["puuid"] == puuid)
    my_participant_id = me_raw["participantId"]

    # infos statiques par participantId (nom, champion, rôle, équipe) —
    # utilisées pour enrichir les stats par phase de chaque joueur
    participant_info = {
        p["participantId"]: {
            "summoner_name": p.get("riotIdGameName", p.get("summonerName", "?")),
            "champion": p["championName"],
            "role": p.get("teamPosition", "UNKNOWN"),
            "team": "BLUE" if p["teamId"] == 100 else "RED",
        }
        for p in participants
    }

    timeline = get_match_timeline(match_id)
    frames = timeline["info"]["frames"]

    # structure : {phase: {participant_id: {kills, deaths, assists, gold_start, gold_end}}}
    phases = {
        phase_name: {
            pid: {"kills": 0, "deaths": 0, "assists": 0, "gold_start": None, "gold_end": None}
            for pid in participant_info
        }
        for phase_name in ("laning_phase", "early", "mid", "late", "ultra_late")
    }

    # events détaillés concernant "moi" uniquement : timestamp précis,
    # position brute, zone approximative, et qui était impliqué
    my_kill_events = []
    my_death_events = []
    # TOUS les kills de la game (pas juste les miens) — sert à détecter les
    # skirmishes : plusieurs kills proches dans le temps = pas un 1v1 propre
    all_kill_events = []

    for frame in frames:
        ts = frame["timestamp"]
        phase = _phase_for_timestamp(ts)

        # gold de CHAQUE joueur à cet instant (permet le delta gold par phase, par joueur)
        for pid_str, pframe in frame["participantFrames"].items():
            pid = int(pid_str)
            gold = pframe["totalGold"]
            bucket = phases[phase][pid]
            if bucket["gold_start"] is None:
                bucket["gold_start"] = gold
            bucket["gold_end"] = gold

        # events de kills/deaths/assists : on attribue à CHAQUE joueur concerné
        for event in frame.get("events", []):
            if event.get("type") != "CHAMPION_KILL":
                continue
            event_phase = _phase_for_timestamp(event["timestamp"])
            killer = event.get("killerId")
            victim = event.get("victimId")
            assists = event.get("assistingParticipantIds", [])
            position = event.get("position", {})

            if killer in phases[event_phase]:
                phases[event_phase][killer]["kills"] += 1
            if victim in phases[event_phase]:
                phases[event_phase][victim]["deaths"] += 1
            for a in assists:
                if a in phases[event_phase]:
                    phases[event_phase][a]["assists"] += 1

            all_kill_events.append({
                "timestamp_ms": event["timestamp"],
                "killer": killer,
                "victim": victim,
                "assists": assists,
            })

            # détail supplémentaire si "moi" est impliqué (kill ou mort)
            if killer == my_participant_id and victim in participant_info:
                my_kill_events.append({
                    "timestamp": _format_timestamp(event["timestamp"]),
                    "phase": event_phase,
                    "victim_champion": participant_info[victim]["champion"],
                    "position_raw": position,
                    "zone_approximative": _approximate_zone(position.get("x", 0), position.get("y", 0)) if position else "inconnue",
                    "assisted_by": [participant_info[a]["champion"] for a in assists if a in participant_info],
                })
            if victim == my_participant_id and killer in participant_info:
                my_death_events.append({
                    "timestamp": _format_timestamp(event["timestamp"]),
                    "timestamp_ms": event["timestamp"],
                    "phase": event_phase,
                    "killer_champion": participant_info[killer]["champion"],
                    "position_raw": position,
                    "zone_approximative": _approximate_zone(position.get("x", 0), position.get("y", 0)) if position else "inconnue",
                    "killer_assisted_by": [participant_info[a]["champion"] for a in assists if a in participant_info],
                })

    # --- Contexte "skirmish" : pour chaque mort, quels autres kills se sont
    # produits dans les 15 secondes autour ? Ça permet de distinguer un vrai
    # 1v1 isolé d'un combat de groupe où plusieurs champions étaient présents
    # (ex: gank suivi d'une riposte qui tue les attaquants).
    SKIRMISH_WINDOW_MS = 15000
    for death in my_death_events:
        death_ts = death["timestamp_ms"]
        nearby = [
            {
                "timestamp": _format_timestamp(e["timestamp_ms"]),
                "killer_champion": participant_info[e["killer"]]["champion"] if e["killer"] in participant_info else "?",
                "victim_champion": participant_info[e["victim"]]["champion"] if e["victim"] in participant_info else "?",
            }
            for e in all_kill_events
            if abs(e["timestamp_ms"] - death_ts) <= SKIRMISH_WINDOW_MS
            and not (e["timestamp_ms"] == death_ts and e["victim"] == my_participant_id)
        ]
        death["other_kills_within_15s"] = nearby
        death["was_skirmish"] = len(nearby) > 0
        death.pop("timestamp_ms", None)  # nettoyage, servait juste au calcul interne

    # --- Construction du résumé par phase, pour chaque joueur ---
    by_phase = {}
    for phase_name, players_data in phases.items():
        players_summary = []
        for pid, data in players_data.items():
            gold_gained = None
            if data["gold_start"] is not None and data["gold_end"] is not None:
                gold_gained = data["gold_end"] - data["gold_start"]
            info = participant_info[pid]
            players_summary.append({
                "summoner_name": info["summoner_name"],
                "champion": info["champion"],
                "role": info["role"],
                "team": info["team"],
                "is_me": pid == my_participant_id,
                "kills": data["kills"],
                "deaths": data["deaths"],
                "assists": data["assists"],
                "gold_gained": gold_gained,
            })
        by_phase[phase_name] = players_summary

    # --- Diagnostic centré sur "moi", en gardant le contexte des autres ---
    my_by_phase = {
        phase_name: next(p for p in players if p["is_me"])
        for phase_name, players in by_phase.items()
    }
    worst_phase = max(my_by_phase, key=lambda p: my_by_phase[p]["deaths"])
    diagnosis = []
    if my_by_phase[worst_phase]["deaths"] >= 2:
        diagnosis.append(
            f"La phase la plus coûteuse pour toi est le {worst_phase} game "
            f"({my_by_phase[worst_phase]['deaths']} morts)."
        )
    if my_by_phase["laning_phase"]["deaths"] == 0 and my_by_phase["ultra_late"]["deaths"] >= 3:
        diagnosis.append(
            "Laning phase propre (0 mort) mais gros décrochage en fin de game — "
            "possible souci de positionnement en teamfight plutôt que de laning."
        )
    # comparaison avec l'adversaire direct (même rôle, équipe adverse) sur la phase la pire
    my_role = participant_info[my_participant_id]["role"]
    my_team = participant_info[my_participant_id]["team"]
    opponent_worst = next(
        (p for p in by_phase[worst_phase]
         if p["role"] == my_role and p["team"] != my_team),
        None,
    )
    if opponent_worst and opponent_worst["gold_gained"] is not None and my_by_phase[worst_phase]["gold_gained"] is not None:
        gold_diff = my_by_phase[worst_phase]["gold_gained"] - opponent_worst["gold_gained"]
        if gold_diff < -500:
            diagnosis.append(
                f"Sur la phase {worst_phase}, ton adversaire direct ({opponent_worst['champion']}) "
                f"a gagné {abs(gold_diff)} gold de plus que toi — écart significatif sur cette phase précise."
            )
    if not diagnosis:
        diagnosis.append("Pas de bascule nette détectée automatiquement — regarde le détail par phase ci-dessous.")

    # --- Bloc explicite équipes : évite que le LLM doive recouper le champ
    # "team" de chaque joueur lui-même dans une structure imbriquée, ce qui
    # est source d'erreur (mauvaise identification allié/adversaire).
    allies = [
        {"summoner_name": info["summoner_name"], "champion": info["champion"], "role": info["role"]}
        for pid, info in participant_info.items()
        if info["team"] == my_team and pid != my_participant_id
    ]
    enemies = [
        {"summoner_name": info["summoner_name"], "champion": info["champion"], "role": info["role"]}
        for pid, info in participant_info.items()
        if info["team"] != my_team
    ]

    return {
        "match_id": match_id,
        "champion": me_raw["championName"],
        "win": me_raw["win"],
        "my_team_color": my_team,
        "teams": {
            "my_allies": allies,       # 4 coéquipiers, hors moi
            "enemy_team": enemies,     # 5 adversaires
        },
        "by_phase": by_phase,
        "my_kill_events": my_kill_events,
        "my_death_events": my_death_events,
        "diagnosis": diagnosis,
    }


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python phase_analysis.py <game_name> <tag_line>")
        sys.exit(1)

    result = analyze_last_game_by_phase(sys.argv[1], sys.argv[2])
    print(json.dumps(result, indent=2, ensure_ascii=False))
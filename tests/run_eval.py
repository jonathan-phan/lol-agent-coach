"""
Rejoue tests/eval_cases.json : vérifie automatiquement le choix d'outil, et
affiche la réponse pour jugement manuel (hallucinations) dans eval_results.md.

Usage : python tests/run_eval.py "TonPseudo" "TAG"
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from agent import agent_loop  # noqa: E402


def tools_called(messages: list) -> list[str]:
    return [
        c["function"]["name"]
        for m in messages if m["role"] == "assistant"
        for c in m.get("tool_calls", [])
    ]


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python tests/run_eval.py <game_name> <tag_line>")
        sys.exit(1)

    game_name, tag_line = sys.argv[1], sys.argv[2]
    path = os.path.join(os.path.dirname(__file__), "eval_cases.json")
    with open(path, encoding="utf-8") as f:
        cases = json.load(f)

    ok = 0
    for i, case in enumerate(cases, 1):
        try:
            answer, messages = agent_loop(f"[joueur: {game_name}#{tag_line}] {case['question']}", [])
            called = tools_called(messages)
        except Exception as e:
            answer, called = f"[erreur] {e}", []
        good = bool(set(called) & set(case["expected_tools"]))
        ok += good
        print(f"\n#{i} {case['question']}\n  attendu : {case['expected_tools']}\n  appelé  : {called}\n  outil   : {'OK' if good else 'KO'}")
        print(f"  réponse : {answer}\n")

    print(f"Choix d'outil correct : {ok}/{len(cases)}")

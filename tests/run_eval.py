"""
Replay tests/eval_cases.json: automatically checks the tool choice, and prints
the answer for manual judging (hallucinations); see eval_results.md.

Usage: python tests/run_eval.py "YourName" "TAG"
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from agent import agent_loop, tools_used  # noqa: E402


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
            answer, messages = agent_loop(f"[player: {game_name}#{tag_line}] {case['question']}", [])
            called = tools_used(messages)
        except Exception as e:
            answer, called = f"[error] {e}", []
        good = bool(set(called) & set(case["expected_tools"]))
        ok += good
        print(f"\n#{i} {case['question']}\n  expected: {case['expected_tools']}\n  called  : {called}\n  tool    : {'OK' if good else 'KO'}")
        print(f"  answer  : {answer}\n")

    print(f"Correct tool choice: {ok}/{len(cases)}")

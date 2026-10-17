"""
Agent loop: the core of the project.

Unlike a plain chatbot, the LLM does not just answer: it receives a list of
available tools, decides on its own which ones to call (and in which order),
we run them in Python, send the results back, and it continues until it can
give a final answer.

No framework (LangChain/CrewAI) on purpose: this is what those frameworks do
internally, but here every step is explicit and visible.

Interface: agent_loop(user_message, messages) -> (answer, messages).

Usage:
    python src/agent.py "YourName" "TAG"
    then ask your questions in natural language in the terminal.
"""
import os
import re
import sys
import json

import requests
from dotenv import load_dotenv

from tool_registry import TOOLS_SCHEMA, run_tool
import riot_client

load_dotenv()

# Generic LLM config: any OpenAI-compatible endpoint (Gemini, Groq, ...) via .env
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_URL = os.getenv("LLM_URL", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash")
MAX_STEPS = 6
# Spells/wards never appear in the tool data, so any mention is invented
FORBIDDEN_DETAILS = re.compile(r"\b(?:spells?|wards?)\b|\([QWER]\)|\b[QWER] ?\+ ?\w", re.IGNORECASE)
RETRY_PROMPT = (
    "Your answer mentions spells (Q/W/E/R) or wards, which are absent from the data. "
    "Redo it, strictly limited to the data returned by the tools."
)

SYSTEM_PROMPT = (
    "You are a League of Legends coach. You have tools to fetch and analyze "
    "the player's real games through the Riot API. Use them to answer with "
    "precise facts (real numbers), not generalities. Pick the most suitable "
    "tool for the question: analyze_last_game or analyze_last_game_by_phase "
    "for a single recent game, compute_stats for trends over several games. "
    "Be direct and concrete in your advice, like a real coach, not a stats "
    "summary. Answer in the language of the user's question.\n\n"
    "CRITICAL RULE - NEVER INVENT DETAILS:\n"
    "For each death/kill of the player (my_death_events/my_kill_events) you have: "
    "the exact timestamp, the opposing champion involved, an APPROXIMATE map "
    "zone (estimated from coordinates, never a certainty), and the other kills "
    "that happened within 15s (other_kills_within_15s). You do NOT have access "
    "to: which spell was used (Q/W/E/R), wards placed, or a detailed account "
    "of the fight. NEVER invent that level of detail, even if it seems "
    "plausible given the champions involved.\n\n"
    "CRITICAL RULE - INTERPRETING A NEARBY ALLY DEATH:\n"
    "If other_kills_within_15s shows an ally died SHORTLY BEFORE your own "
    "death (a few seconds up to ~15s), it probably means they were engaged in "
    "THE SAME fight as you (a skirmish), not that they abandoned you or did "
    "not help. A nearby ally death is evidence of PARTICIPATION in the fight, "
    "not absence. NEVER say 'no help' or 'you were alone' if an ally died in "
    "that time window; say instead that it was a group fight in which the ally "
    "was also killed. Likewise, an ally missing from the list does NOT prove "
    "they were absent: there is no presence data, only kill data."
    "\n\nRULE - POSITIVE/NEGATIVE BALANCE:\n"
    "Do not focus only on problems. For each analyzed phase, explicitly "
    "mention what went well (successful kills, gold/CS lead over the opponent, "
    "phases without deaths), based on the same numbers, not just the failures. "
    "A good coach identifies strengths to repeat as much as weaknesses to fix."
)


def call_llm(messages: list, api_key: str | None = None) -> dict:
    """Raw call to the LLM API (OpenAI-compatible chat completions + tools).
    The key comes from the caller (e.g. a visitor's own key), else from LLM_API_KEY."""
    api_key = api_key or LLM_API_KEY
    if not api_key:
        raise RuntimeError("No LLM key: enter yours in the sidebar or set LLM_API_KEY in .env")
    resp = requests.post(
        LLM_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": LLM_MODEL, "messages": messages, "tools": TOOLS_SCHEMA},
        timeout=60,
    )
    if resp.status_code in (401, 403):
        raise RuntimeError("Invalid LLM key: check the key you entered, or LLM_API_KEY in .env")
    if resp.status_code == 429:
        raise RuntimeError("LLM quota reached: retry later or switch model/provider.")
    if not resp.ok:
        raise RuntimeError(f"LLM API error {resp.status_code}: {resp.text}")
    return resp.json()


def _execute_tool_calls(tool_calls: list) -> list[dict]:
    results = []
    for call in tool_calls:
        name = call["function"]["name"]
        try:
            args = json.loads(call["function"]["arguments"])
            print(f"  [tool called] {name}({args})")
            result = run_tool(name, args)
        except json.JSONDecodeError:
            result = {"error": f"Invalid JSON arguments for {name}"}
        results.append({
            "role": "tool",
            "name": name,
            "tool_call_id": call["id"],
            "content": json.dumps(result, ensure_ascii=False),
        })
    return results


def tools_used(messages: list) -> list[str]:
    """Names of the tools the LLM called in these messages, in order."""
    return [
        c["function"]["name"]
        for m in messages if m["role"] == "assistant"
        for c in m.get("tool_calls", [])
    ]


def agent_loop(user_message: str, messages: list, api_key: str | None = None) -> tuple[str, list]:
    """
    Send the conversation to the LLM, run the requested tools, send the
    results back, and repeat until a final answer (at most MAX_STEPS turns).
    api_key overrides LLM_API_KEY for this conversation and is never stored.

    Returns (answer_text, updated_messages) so the conversation can continue
    (multi-turn memory).
    """
    if not messages:
        messages.append({"role": "system", "content": SYSTEM_PROMPT})
    messages.append({"role": "user", "content": user_message})
    retried = False

    for _ in range(MAX_STEPS):
        message = call_llm(messages, api_key)["choices"][0]["message"]
        content = message.get("content") or ""
        tool_calls = message.get("tool_calls")

        if not tool_calls:
            messages.append({"role": "assistant", "content": content})
            if not retried and FORBIDDEN_DETAILS.search(content):
                retried = True
                messages.append({"role": "user", "content": RETRY_PROMPT})
                continue
            return content, messages

        messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
        messages.extend(_execute_tool_calls(tool_calls))

    return "Too many tool steps without a final answer, please rephrase your question.", messages


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python agent.py <game_name> <tag_line>")
        sys.exit(1)

    game_name, tag_line = sys.argv[1], sys.argv[2]
    print(f"Agent ready for {game_name}#{tag_line} (data mode: {riot_client.mode()}). Ask your question (or 'quit' to exit).\n")

    conversation = []
    while True:
        user_input = input("You: ")
        if user_input.strip().lower() in ("quit", "exit"):
            break
        # The Riot ID is injected in every message so the user never repeats it.
        try:
            answer, conversation = agent_loop(f"[player: {game_name}#{tag_line}] {user_input}", conversation)
        except (RuntimeError, requests.RequestException) as e:
            print(f"\n[error] {e}\n")
            continue
        print(f"\nCoach: {answer}\n")

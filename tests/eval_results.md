# Agent evaluation — LoL Agent Coach

This file documents a manual evaluation of the agent, carried out by the
author (a former Diamond player), on questions asked in real conditions
during development. Each case was judged by comparing the agent's answer
with what actually happened in the game (known to the player, or verifiable
in the raw data returned by the tools).

The questions were asked in French; the replayable cases in
`eval_cases.json` are their English equivalents.

## Methodology

- Model used: `mistral-small-latest` (free tier). The default model of the
  current code is `gemini-2.5-flash`; this evaluation has not been re-run on it.
- Each question is asked to the agent through `agent.py`, in real conditions.
- The "Correct" / "Incorrect" judgement is based on: (1) was the right tool
  called, (2) is the answer grounded in data actually returned by that tool,
  (3) does the player confirm the diagnosis matches how they experienced the game.

## Results

| #   | Question asked                                            | Expected tool                | Tool called                | Verdict      | Observed problem                                                                                                                                                                                                      |
| --- | --------------------------------------------------------- | ---------------------------- | -------------------------- | ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | "Why did I lose my last game?"                            | analyze_last_game / by_phase | analyze_last_game_by_phase | Correct      | —                                                                                                                                                                                                                     |
| 2   | "Analyze the early and mid game against Leona/MF"         | analyze_last_game_by_phase   | analyze_last_game_by_phase | Partial      | Did not correctly tell allies from opponents (fixed since, see Fix #1)                                                                                                                                                |
| 3   | "The trades I lost, prove it"                             | analyze_last_game_by_phase   | analyze_last_game_by_phase | Incorrect    | **Severe hallucination**: invented a fake table with spells (Q/E), unverifiable precise timestamps, and a fake JSON excerpt with keys that exist in no tool                                                            |
| 4   | "How did I play?" (my support was present)                | —                            | analyze_last_game_by_phase | Incorrect    | Concluded "no help from your support" from the absence of a kill in `other_kills_within_15s` — confused absence of data with absence of the fact                                                                       |
| 5   | "Analyze my laning phase" (jungler died just before me)   | —                            | analyze_last_game_by_phase | Incorrect    | Read a nearby ally death as "no help", when it is evidence of participation in the same fight                                                                                                                         |
| 6   | "Full summary of the game"                                | compute_stats or by_phase    | analyze_last_game_by_phase | Partial      | Good numeric summary, but 100% focused on weaknesses (no strength mentioned) and reintroduced an invented spell ("Q + auto-attack") despite the ban in the system prompt                                              |

**Overall score on these 6 tests: 1 fully correct, 3 partial, 2 incorrect (hallucination / misinterpretation).**

## Lessons and fixes

### Fix #1 — Ally/opponent confusion

**Cause:** the data structure forced the LLM to cross-check the `team` field
of 10 players across 3 phases to work out who was on which team.
**Fix:** added an explicit `teams: {my_allies, enemy_team}` block at the top
of the result so the LLM does not have to infer it.

### Fix #2 — Hallucinated fight details (spells, invented JSON)

**Cause:** faced with a request for "proof", the model preferred to fabricate
a convincing answer rather than admit a data limit.
**Fix:** explicit rule in the system prompt forbidding any mention of spells
(Q/W/E/R), wards, or a detailed fight account not present in the tool data.
A regex guardrail in `agent.py` also detects such mentions and asks the
model to redo its answer once.
**Remaining limit:** the rule is not followed 100% by `mistral-small` — the
hallucinated spell reappeared in test #6 despite the explicit ban. This is a
documented limit of the cheap model used, not a code bug.

### Fix #3 — Absence of data read as absence of the fact

**Cause:** `other_kills_within_15s` only lists kills, not the presence of
living players; its absence was wrongly read as proof of an ally's physical
absence.
**Fix:** explicit system prompt rule: an empty or incomplete list proves
nothing about allies' actual presence.

### Fix #4 — Wrong causal reading of a nearby ally death

**Cause:** an ally death shortly before the player's death was read as
abandonment ("no help"), when it actually indicates participation in the same
fight (the ally also lost their duel).
**Fix:** explicit rule asking to interpret a nearby ally death as evidence of
participation in a skirmish, not absence.

### Fix #5 — Unbalanced feedback (negative only)

**Cause:** the system prompt implicitly steered towards diagnosing problems,
without asking to highlight strengths.
**Fix:** explicit rule asking for a balance between strengths and weaknesses,
based on the same numbers.

## Known, unresolved limits

- `mistral-small` does not perfectly follow the anti-hallucination rules under
  some phrasings (notably when asked for "proof" or extra detail) — a more
  robust model (`mistral-medium`) might help; untested for lack of budget.
- No memory between sessions: each launch of `agent.py` starts from an empty
  conversation.
- No access to ward data (placed/destroyed), spells used, or item purchase
  order over time — the agent cannot answer questions about these with
  certainty.

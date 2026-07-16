# LoL Agent Coach

Agent conversationnel qui analyse tes parties de League of Legends et te donne
un diagnostic personnalisé, en croisant plusieurs sources de données via un
system de function calling construit à la main (pas de framework type
LangChain/CrewAI — l'objectif est de comprendre chaque brique).

## Problématique

Les joueurs ont accès à énormément de stats brutes (op.gg, u.gg) mais peu
d'analyse contextualisée. Cet agent transforme des données de match brutes
en diagnostic actionnable, en langage naturel, en décidant lui-même quels
outils appeler et dans quel ordre pour répondre à une question comme
*"pourquoi je perds mes games sur Yasuo en ce moment ?"*.

## Architecture

```
User question
     │
     ▼
┌─────────────┐
│  Agent Loop  │◄──────────────┐
│ (src/agent.py)│               │
└──────┬───────┘               │
       │ décide d'appeler un outil
       ▼                       │
┌──────────────────┐           │
│  Tool Registry     │          │
│  (src/tools/)      │          │
├────────────────────┤          │
│ get_match_history  │          │
│ compute_stats       │──────────┘
│ get_champion_meta   │  résultat renvoyé au LLM
│ compare_to_benchmark│  (boucle jusqu'à réponse finale)
└──────────────────┘
       │
       ▼
  Riot Games API
  (data/ cache local)
```

## Boucle agentique (le cœur du projet)

1. L'utilisateur pose une question
2. Le LLM reçoit la question + la liste des outils disponibles (nom, description, paramètres)
3. Le LLM répond soit avec du texte final, soit avec une demande d'appel d'outil (tool_use)
4. Si c'est un appel d'outil : on l'exécute en Python, on renvoie le résultat au LLM comme nouveau message
5. On répète jusqu'à ce que le LLM donne une réponse finale (pas de tool_use)

Voir `src/agent.py` pour l'implémentation — volontairement écrite sans
framework pour bien comprendre le mécanisme sous-jacent à LangGraph/CrewAI.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # puis renseigner tes clés API
```

Clés nécessaires dans `.env` :
- `RIOT_API_KEY` — https://developer.riotgames.com (clé dev, expire 24h, à régénérer)
- `ANTHROPIC_API_KEY` ou `MISTRAL_API_KEY` — selon le LLM choisi

## Roadmap (été 2026)

- [x] Semaine 1 : squelette projet + wrapper Riot API (get_match_history)
- [ ] Semaine 2 : compute_stats + premiers appels LLM avec function calling
- [ ] Semaine 3 : get_champion_meta + compare_to_benchmark
- [ ] Semaine 4 : boucle agentique complète, multi-tool, gestion des erreurs
- [ ] Semaine 5 : jeu d'éval (15-20 questions), mesure taux de succès/pertinence
- [ ] Semaine 6 : README final, polish, éventuelle interface Streamlit

## Évaluation

Le jeu d'éval (`tests/eval_questions.json`) contient des questions types
(diagnostic, comparaison, conseil matchup) jugées manuellement sur une
grille : pertinence du diagnostic, bons outils appelés dans le bon ordre,
absence d'hallucination sur les stats.

## Ce que ce projet démontre

- Compréhension fine du function calling (pas juste "j'ai utilisé un framework")
- Capacité à structurer un agent multi-étapes avec raisonnement
- Rigueur d'évaluation (rare chez les projets perso débutants)
- Manipulation d'une vraie API externe avec ses contraintes (rate limits, auth)

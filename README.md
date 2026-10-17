# LoL Agent Coach

Agent conversationnel qui analyse tes parties de League of Legends et te
donne un diagnostic personnalisé, en croisant plusieurs sources de données
via un système de function calling construit à la main (pas de framework
type LangChain/CrewAI — l'objectif est de comprendre chaque brique).

## Problématique

Les joueurs ont accès à énormément de stats brutes (op.gg, u.gg) mais peu
d'analyse contextualisée. Cet agent transforme des données de match brutes
en diagnostic actionnable, en langage naturel, en décidant lui-même quels
outils appeler et dans quel ordre pour répondre à une question comme
_"pourquoi je perds mes games sur Yasuo en ce moment ?"_.

## Architecture

```
User question
     │
     ▼
┌──────────────┐
│  Agent Loop   │◄──────────────┐
│ (src/agent.py)│                │
└──────┬───────┘                │
       │ décide d'appeler un outil
       ▼                        │
┌────────────────────┐          │
│  Tool Registry       │        │
│  (src/, src/tools/)  │        │
├──────────────────────┤        │
│ get_match_history      │      │
│ compute_stats           │─────┘
│ analyze_last_game         │  résultat renvoyé au LLM
│ analyze_last_game_by_phase│  (boucle jusqu'à réponse finale)
└────────────────────┘
       │
       ▼
  Riot Games API
  (match/v5 + timeline)
```

## Boucle agentique (le cœur du projet)

1. L'utilisateur pose une question
2. Le LLM (Gemini, via API HTTP directe, endpoint compatible OpenAI) reçoit
   la question + la liste des outils disponibles (nom, description, paramètres)
3. Le LLM répond soit avec du texte final, soit avec une demande d'appel
   d'outil (`tool_calls`)
4. Si c'est un appel d'outil : on l'exécute en Python, on renvoie le
   résultat au LLM comme nouveau message (`role: "tool"`)
5. On répète jusqu'à ce que le LLM donne une réponse finale

Voir `src/agent.py` pour l'implémentation — écrite sans framework pour bien
comprendre le mécanisme sous-jacent à LangGraph/CrewAI. Choix du modèle
Gemini (tier gratuit) plutôt que Claude/OpenAI/Mistral : gratuit et simple
à obtenir pour n'importe quel utilisateur qui veut lancer cet agent avec
sa propre clé.

## Les 4 outils exposés à l'agent

| Outil                        | Ce qu'il fait                                                                                                                                                                                                                                                                                                        | Fichier                       |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------- |
| `get_match_history`          | Récupère N dernières games, avec pour chacune : le joueur, son adversaire direct (même rôle, équipe adverse), et les 10 joueurs                                                                                                                                                                                      | `src/riot_client.py`          |
| `compute_stats`              | Agrège plusieurs games : winrate, KDA moyen, stats par rôle et par champion+rôle, comparaison moyenne vs adversaires directs, 3 pires games                                                                                                                                                                          | `src/tools/stats.py`          |
| `analyze_last_game`          | Diagnostic rapide de la toute dernière game (résultat, KDA, comparaison gold/CS avec l'adversaire direct)                                                                                                                                                                                                            | `src/tools/last_game.py`      |
| `analyze_last_game_by_phase` | Découpe la dernière game en 5 phases temporelles (laning 0-10min, early 10-14min, mid 14-25min, late 25-30min, ultra_late 30min+), avec kills/deaths/gold par joueur et par phase, plus le détail de chaque mort/kill du joueur (timestamp, zone approximative, autres kills dans les 15s pour détecter un skirmish) | `src/tools/phase_analysis.py` |

## Setup

Ce projet est pensé pour être cloné et lancé en local par n'importe quel
joueur : chacun fournit ses propres clés API (pas de clé partagée, pas de
serveur, pas de compte/login).

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

Crée ensuite un fichier `.env` à la racine du projet avec :

```
RIOT_API_KEY=ta_cle_riot
LLM_API_KEY=ta_cle_llm
# optionnels (défaut : Gemini)
# LLM_URL=https://api.cohere.ai/compatibility/v1/chat/completions
# LLM_MODEL=command-a-plus-05-2026
```

Le fournisseur LLM est interchangeable : tout endpoint compatible OpenAI
(Gemini, Groq, Cohere...) fonctionne en changeant ces 3 variables, sans
toucher au code.

Clés nécessaires (toutes gratuites) :

- `RIOT_API_KEY` — https://developer.riotgames.com (clé dev perso, **expire
  toutes les 24h**, à régénérer à chaque session via "Regenerate API Key")
- `LLM_API_KEY` — clé de ton fournisseur LLM (ex. https://aistudio.google.com/apikey (tier gratuit
  Gemini, pas d'expiration 24h mais quota quotidien limité par clé)

## Utilisation

```bash
py src\agent.py "TonPseudo" "TAG"
```

Puis pose tes questions en langage naturel. Tape `quit` pour sortir.

Interface web locale (Streamlit) :

```bash
streamlit run app.py
```

Seules les parties Solo/Duo (queue 420) sont analysées, remakes exclus.

## Évaluation

Voir [`tests/eval_results.md`](tests/eval_results.md) pour le détail complet.
Les questions sont rejouables avec `python tests/run_eval.py "Pseudo" "TAG"`
(`tests/eval_cases.json`) : le choix d'outil est vérifié automatiquement, le
contenu des réponses reste jugé à la main.

Résumé (première évaluation, sur `mistral-small`) : sur 6 questions-tests jugées manuellement (par un joueur ex-Diamond,
donc capable de juger la pertinence réelle des diagnostics), **1 réponse
correcte complète, 3 partielles, 2 incorrectes** — les erreurs identifiées
sont classées en 3 catégories distinctes :

1. **Hallucination pure** — invention de détails (sorts utilisés, faux JSON
   présenté comme preuve) non présents dans les données réelles
2. **Déduction abusive** — confondre l'absence d'une donnée dans le résultat
   d'un outil avec l'absence du fait réel (ex: "pas de kill alliée à
   proximité" interprété comme "allié absent")
3. **Erreur d'interprétation causale** — lire une mort alliée proche dans le
   temps comme un abandon, alors qu'elle indique une participation au même
   combat

Chaque erreur a donné lieu à une correction documentée (ajustement du
system prompt ou de la structure de données retournée par les outils) —
voir le détail dans le fichier d'éval.

## Limites connues

- Le modèle utilisé (tier gratuit Gemini) ne respecte pas parfaitement les
  règles anti-hallucination sous certaines formulations ("prouve-le",
  demandes de détail) — non résolu, documenté comme piste d'amélioration
- Pas de mémoire entre sessions ni de stockage persistant des games : tout
  est recalculé à la volée depuis l'API Riot à chaque lancement
- Pas d'accès aux données de wards, sorts utilisés, ou build order — l'API
  Riot timeline ne les expose pas dans les champs actuellement exploités
- Pas de données en temps réel (champ select, game en cours) — évalué et
  volontairement écarté : la seule voie techniquement possible (LCU API)
  n'est pas officiellement documentée par Riot et est jugée trop fragile
  pour ce projet
- Pensé pour un usage multi-joueurs en local : chaque utilisateur clone le
  repo et fournit ses propres clés (Riot + Google), il n'y a pas de clé
  partagée ni de serveur central

## Ce que ce projet démontre

- Compréhension fine du function calling (boucle écrite à la main, pas de
  framework)
- Capacité à structurer un agent multi-étapes avec raisonnement sur
  plusieurs outils
- Démarche d'évaluation rigoureuse : détection, catégorisation et
  correction d'erreurs de raisonnement du LLM, pas seulement de bugs de code
- Manipulation d'une vraie API externe avec ses contraintes (rate limiting,
  clé expirante, structure de données imbriquée)
- Choix d'architecture justifiés et documentés (Mistral plutôt que Claude,
  API officielle plutôt que sources non-officielles fragiles)

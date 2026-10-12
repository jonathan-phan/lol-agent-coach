# Évaluation de l'agent — LoL Agent Coach

Ce fichier documente une évaluation manuelle de l'agent, réalisée par Jonathan
(ex-joueur Diamond), sur des questions posées en conditions réelles pendant
le développement. Chaque cas a été jugé par comparaison entre la réponse de
l'agent et le déroulé réel de la game (connu du joueur ou vérifiable dans les
données brutes retournées par les outils).

## Méthodologie

- Modèle utilisé : `mistral-small-latest` (tier gratuit)
- Chaque question est posée à l'agent via `agent.py`, en conditions réelles
- Le jugement "Correct" / "Incorrect" est basé sur : (1) le bon outil a-t-il
  été appelé, (2) la réponse est-elle fondée sur des données réellement
  retournées par cet outil, (3) le joueur confirme-t-il que le diagnostic
  correspond à son vécu de la game

## Résultats

| #   | Question posée                                           | Outil attendu                | Outil appelé               | Verdict      | Type de problème observé                                                                                                                                                                             |
| --- | -------------------------------------------------------- | ---------------------------- | -------------------------- | ------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | "Pourquoi j'ai perdu ma dernière game ?"                 | analyze_last_game / by_phase | analyze_last_game_by_phase | ✅ Correct   | —                                                                                                                                                                                                    |
| 2   | "Analyse le early et mid game contre Leona/MF"           | analyze_last_game_by_phase   | analyze_last_game_by_phase | ⚠️ Partiel   | N'identifiait pas correctement qui était allié vs adversaire (corrigé depuis, voir Fix #1)                                                                                                           |
| 3   | "Les trades que j'ai perdus, prouve-le"                  | analyze_last_game_by_phase   | analyze_last_game_by_phase | ❌ Incorrect | **Hallucination sévère** : a inventé un faux tableau avec sorts (Q/E), timestamps précis non vérifiables, et un faux extrait JSON avec des clés qui n'existent dans aucun outil                      |
| 4   | "Comment j'ai joué ?" (mon support était présent)        | —                            | analyze_last_game_by_phase | ❌ Incorrect | A conclu "pas d'aide de ton support" à partir de l'absence de kill dans `other_kills_within_15s` — confusion entre absence de donnée et absence du fait                                              |
| 5   | "Analyse ma laning phase" (jungler mort juste avant moi) | —                            | analyze_last_game_by_phase | ❌ Incorrect | A interprété la mort proche d'un allié comme "aucune aide" alors que c'est une preuve de participation au même combat                                                                                |
| 6   | "Résumé complet de la game"                              | compute_stats ou by_phase    | analyze_last_game_by_phase | ⚠️ Partiel   | Bonne synthèse chiffrée, mais 100% orientée sur les points faibles (aucun point fort mentionné) et réintroduction d'un sort inventé ("Q + auto-attaque") malgré l'interdiction dans le system prompt |

**Score global observé sur ces 6 tests : 1 correct complet, 3 partiels, 2 incorrects (hallucination/mauvaise interprétation).**

## Enseignements et corrections apportées

### Fix #1 — Confusion allié/adversaire

**Cause :** la structure de données obligeait le LLM à recouper le champ
`team` de 10 joueurs à travers 3 phases pour déduire qui était dans quelle
équipe.
**Correction :** ajout d'un bloc explicite `teams: {my_allies, enemy_team}`
en tête du résultat, pour éviter au LLM d'avoir à faire cette déduction.

### Fix #2 — Hallucination de détails de combat (sorts, JSON inventé)

**Cause :** face à une demande de "preuve", le modèle a préféré fabriquer
une réponse convaincante plutôt que d'admettre une limite de données.
**Correction :** règle explicite dans le system prompt interdisant toute
mention de sorts (Q/W/E/R), de wards, ou de récit détaillé de combat non
présent dans les données d'outils.
**Limite persistante :** cette règle n'est pas respectée à 100% par
`mistral-small` — le sort halluciné est réapparu dans le test #6 malgré
l'interdiction explicite. C'est une limite documentée du modèle économique
utilisé, pas un bug du code.

### Fix #3 — Absence de donnée interprétée comme absence du fait

**Cause :** `other_kills_within_15s` ne liste que des kills, pas la présence
des joueurs vivants ; son absence a été lue à tort comme une preuve
d'absence physique d'un allié.
**Correction :** règle explicite dans le system prompt : une liste vide ou
incomplète ne prouve rien sur la présence réelle des alliés.

### Fix #4 — Mauvaise interprétation causale d'une mort alliée proche

**Cause :** une mort alliée survenue juste avant la mort du joueur a été
lue comme un abandon ("aucune aide"), alors qu'elle indique en réalité une
participation au même combat (l'allié a aussi perdu son duel).
**Correction :** règle explicite demandant d'interpréter une mort alliée
proche comme preuve de participation à un skirmish, pas d'absence.

### Fix #5 — Feedback déséquilibré (uniquement négatif)

**Cause :** le system prompt orientait implicitement vers un diagnostic de
problèmes, sans demander de valoriser les points forts.
**Correction :** règle explicite demandant un équilibre entre points forts
et points faibles, basés sur les mêmes données chiffrées.

## Limites connues, non résolues

- Le modèle `mistral-small` ne respecte pas parfaitement les règles
  anti-hallucination sous certaines formulations de question (notamment
  quand on lui demande une "preuve" ou un luxe de détail) — passer à un
  modèle plus robuste (`mistral-medium`) pourrait améliorer ce point, non
  testé faute de budget
- Pas de mémoire entre sessions : chaque lancement de `agent.py` repart
  d'une conversation vide
- Pas d'accès aux données de wards (posées/détruites), sorts utilisés, ou
  ordre d'achat d'objets dans le temps — l'agent ne peut donc pas répondre
  avec certitude aux questions portant sur ces éléments

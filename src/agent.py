"""
Boucle agentique — le cœur du projet.

Contrairement à un chatbot classique, ici le LLM ne se contente pas de
répondre : il reçoit une liste d'outils disponibles, décide lui-même
lesquels appeler (et dans quel ordre) pour répondre à la question posée,
on exécute ces outils en Python, on lui renvoie les résultats, et il
continue jusqu'à pouvoir donner une réponse finale.

C'est écrit sans framework (pas de LangChain/CrewAI) pour bien comprendre
le mécanisme sous-jacent : c'est exactement ce que ces frameworks font en
interne, mais ici chaque étape est explicite et visible.

Usage :
    python src/agent.py "TonPseudo" "TAG"
    puis pose tes questions en langage naturel dans le terminal.
"""
import os
import re
import sys
import json

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
from riot_client import get_match_history  # noqa: E402
from tools.stats import compute_stats  # noqa: E402
from tools.last_game import analyze_last_game  # noqa: E402
from tools.phase_analysis import analyze_last_game_by_phase  # noqa: E402

load_dotenv()

# Config LLM générique : tout endpoint compatible OpenAI (Gemini, Groq...) via .env
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_URL = os.getenv("LLM_URL", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash")
MAX_STEPS = 6
# Sorts/wards : jamais présents dans les données des outils, donc toujours inventés
FORBIDDEN_DETAILS = re.compile(r"\b(?:sorts?|wards?)\b|\([QWER]\)|\b[QWER] ?\+ ?\w", re.IGNORECASE)

# --- 1. Le registre des outils : nom -> fonction Python réelle ---
# Chaque outil ici a la même signature (game_name, tag_line) pour rester
# simple ; le LLM fournit toujours ces deux paramètres.
TOOL_FUNCTIONS = {
    "get_match_history": lambda game_name, tag_line, count=10: get_match_history(game_name, tag_line, count=count),
    "compute_stats": lambda game_name, tag_line, count=10: compute_stats(
        get_match_history(game_name, tag_line, count=count)
    ),
    "analyze_last_game": lambda game_name, tag_line: analyze_last_game(game_name, tag_line),
    "analyze_last_game_by_phase": lambda game_name, tag_line: analyze_last_game_by_phase(game_name, tag_line),
}

# --- 2. Les schémas d'outils tels que le LLM les voit ---
# C'est ici que le LLM lit "quels outils existent, à quoi ils servent, et
# quels paramètres ils attendent" — c'est la pièce centrale du function calling.
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_match_history",
            "description": (
                "Récupère les N dernières games du joueur, avec pour chaque game : "
                "ses propres stats, celles de son adversaire direct (même rôle, "
                "équipe adverse), et celles des 10 joueurs. Utile pour une vue "
                "d'ensemble brute, mais préférer compute_stats pour des tendances "
                "déjà agrégées."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "game_name": {"type": "string", "description": "Pseudo Riot (avant le #)"},
                    "tag_line": {"type": "string", "description": "Tag Riot (après le #)"},
                    "count": {"type": "integer", "description": "Nombre de games à récupérer (défaut 10)"},
                },
                "required": ["game_name", "tag_line"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compute_stats",
            "description": (
                "Agrège plusieurs games en statistiques : winrate global, KDA moyen, "
                "stats par rôle, stats par champion+rôle, comparaison moyenne face aux "
                "adversaires directs, et les 3 pires games. À utiliser pour répondre à "
                "des questions sur des TENDANCES ('pourquoi je perds en ce moment', "
                "'suis-je meilleur sur tel champion'), pas pour une seule game précise."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "game_name": {"type": "string", "description": "Pseudo Riot (avant le #)"},
                    "tag_line": {"type": "string", "description": "Tag Riot (après le #)"},
                    "count": {"type": "integer", "description": "Nombre de games à analyser (défaut 10)"},
                },
                "required": ["game_name", "tag_line"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_last_game",
            "description": (
                "Diagnostic rapide de la toute dernière game jouée uniquement : "
                "résultat, KDA, comparaison en gold/CS avec l'adversaire direct. "
                "À utiliser pour des questions du type 'qu'est-ce qui s'est passé "
                "dans ma dernière game', juste après avoir fini une partie."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "game_name": {"type": "string", "description": "Pseudo Riot (avant le #)"},
                    "tag_line": {"type": "string", "description": "Tag Riot (après le #)"},
                },
                "required": ["game_name", "tag_line"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_last_game_by_phase",
            "description": (
                "Découpe la toute dernière game en 3 phases (early 0-14min, mid "
                "14-25min, late 25min+), avec kills/deaths/assists/gold gagné pour "
                "les 10 joueurs sur chaque phase. Fournit aussi my_kill_events et "
                "my_death_events : pour CHAQUE mort/kill du joueur, le timestamp "
                "exact, le champion adverse impliqué, et une zone de la carte "
                "APPROXIMATIVE (ex: 'river ou mid lane (approximatif)'). Ces zones "
                "sont des estimations par coordonnées, pas une donnée certaine — "
                "ne jamais les présenter comme une certitude absolue. Chaque mort "
                "inclut aussi other_kills_within_15s (autres KILLS dans les 15s "
                "autour, pour détecter un skirmish vs un 1v1). ATTENTION : "
                "l'absence d'un allié dans cette liste NE PROUVE PAS son absence "
                "physique — on n'a aucune donnée de présence, seulement de kills. "
                "Ne jamais inventer de détail au-delà de ce qui est fourni (pas de "
                "sort utilisé, pas de description de combat). À utiliser pour comprendre "
                "QUAND et où précisément une game a basculé, pas juste le résultat "
                "final. Plus lent que les autres outils (récupère la timeline "
                "complète)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "game_name": {"type": "string", "description": "Pseudo Riot (avant le #)"},
                    "tag_line": {"type": "string", "description": "Tag Riot (après le #)"},
                },
                "required": ["game_name", "tag_line"],
            },
        },
    },
]

SYSTEM_PROMPT = (
    "Tu es un coach League of Legends. Tu as accès à des outils pour récupérer "
    "et analyser les vraies games du joueur via l'API Riot. Utilise-les pour "
    "répondre avec des faits précis (chiffres réels), pas des généralités. "
    "Choisis l'outil le plus adapté à la question : analyze_last_game ou "
    "analyze_last_game_by_phase pour une seule game récente, compute_stats "
    "pour des tendances sur plusieurs games. Sois direct et concret dans tes "
    "conseils, comme un vrai coach, pas un résumé de stats.\n\n"
    "RÈGLE CRITIQUE — NE JAMAIS INVENTER DE DÉTAILS :\n"
    "Pour chaque mort/kill du joueur (my_death_events/my_kill_events), tu as : "
    "timestamp exact, champion adverse impliqué, une zone de carte APPROXIMATIVE "
    "(estimation par coordonnées, jamais une certitude), et les autres kills "
    "survenus dans les 15s autour (other_kills_within_15s). Tu N'AS PAS accès "
    "à : quel sort a été utilisé (Q/W/E/R), les wards posées, ou un récit "
    "détaillé du combat. N'invente JAMAIS ce niveau de détail, même s'il te "
    "semble plausible avec les champions en présence.\n\n"
    "RÈGLE CRITIQUE — INTERPRÉTATION D'UNE MORT ALLIÉE PROCHE :\n"
    "Si other_kills_within_15s montre qu'un allié est mort PEU AVANT ta propre "
    "mort (quelques secondes à ~15s), cela indique probablement qu'il était "
    "engagé dans LE MÊME combat que toi (un skirmish), pas qu'il t'a abandonné "
    "ou n'a pas aidé. Une mort alliée proche = preuve de PARTICIPATION au "
    "fight, pas d'absence. Ne dis JAMAIS 'aucune aide' ou 'tu étais seul' si "
    "un allié est mort dans cette fenêtre de temps — dis plutôt que c'était "
    "un combat de groupe où l'allié a aussi été tué."
    "\n\nRÈGLE — ÉQUILIBRE POSITIF/NÉGATIF :\n"
    "Ne te concentre pas uniquement sur les problèmes. Pour chaque phase "
    "analysée, mentionne explicitement ce qui a bien fonctionné (kills "
    "réussis, avance en gold/CS sur l'adversaire, phases sans mort) en te "
    "basant sur les mêmes données chiffrées, pas juste les échecs. Un bon "
    "coach identifie les points forts à répéter autant que les points "
    "faibles à corriger."
)


def run_tool(name: str, tool_input: dict) -> dict:
    """Exécute l'outil demandé par le LLM et retourne son résultat brut."""
    if name not in TOOL_FUNCTIONS:
        return {"error": f"Outil inconnu : {name}"}
    try:
        return TOOL_FUNCTIONS[name](**tool_input)
    except Exception as e:
        return {"error": f"Erreur lors de l'exécution de {name} : {str(e)}"}


def call_llm(messages: list) -> dict:
    """Appel brut à l'API Gemini (endpoint compatible OpenAI, chat completions + tools)."""
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": LLM_MODEL,
        "messages": messages,
        "tools": TOOLS_SCHEMA,
    }
    resp = requests.post(LLM_URL, headers=headers, json=body, timeout=60)
    if resp.status_code in (401, 403):
        raise RuntimeError("Clé LLM invalide : vérifie LLM_API_KEY dans .env")
    if resp.status_code == 429:
        raise RuntimeError("Quota LLM atteint : réessaie plus tard ou change de modèle/fournisseur.")
    if not resp.ok:
        raise RuntimeError(f"LLM API error {resp.status_code}: {resp.text}")
    return resp.json()


def agent_loop(user_message: str, messages: list) -> tuple[str, list]:
    """
    Boucle principale : envoie la conversation à Gemini, exécute les outils
    demandés, renvoie les résultats, répète jusqu'à une réponse finale.

    Retourne (réponse_texte, messages_mis_à_jour) pour pouvoir continuer la
    conversation ensuite (mémoire multi-tour).
    """
    if not messages:
        messages.append({"role": "system", "content": SYSTEM_PROMPT})
    messages.append({"role": "user", "content": user_message})
    retried = False

    for _ in range(MAX_STEPS):
        data = call_llm(messages)
        choice = data["choices"][0]
        message = choice["message"]

        tool_calls = message.get("tool_calls")

        # Le LLM a fini de répondre (pas d'appel d'outil en attente)
        if not tool_calls:
            content = message.get("content") or ""
            messages.append({"role": "assistant", "content": content})
            if not retried and FORBIDDEN_DETAILS.search(content):
                retried = True
                messages.append({
                    "role": "user",
                    "content": (
                        "Ta réponse mentionne des sorts (Q/W/E/R) ou des wards absents des données. "
                        "Refais-la en te limitant strictement aux données des outils."
                    ),
                })
                continue
            return content, messages

        # Le LLM veut appeler un ou plusieurs outils
        messages.append({
            "role": "assistant",
            "content": message.get("content") or "",
            "tool_calls": tool_calls,
        })

        for call in tool_calls:
            name = call["function"]["name"]
            args = json.loads(call["function"]["arguments"])
            print(f"  [outil appelé] {name}({args})")
            result = run_tool(name, args)
            messages.append({
                "role": "tool",
                "name": name,
                "tool_call_id": call["id"],
                "content": json.dumps(result, ensure_ascii=False),
            })
        # la boucle continue : on renvoie au LLM avec les résultats d'outils

    return "Trop d'étapes d'outils sans réponse finale, reformule ta question.", messages


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python agent.py <game_name> <tag_line>")
        sys.exit(1)

    game_name, tag_line = sys.argv[1], sys.argv[2]
    print(f"Agent prêt pour {game_name}#{tag_line}. Pose ta question (ou 'quit' pour sortir).\n")

    conversation = []
    while True:
        user_input = input("Toi : ")
        if user_input.strip().lower() in ("quit", "exit"):
            break
        # On glisse le pseudo/tag dans le message pour que le LLM les ait
        # sous la main sans que tu aies à les répéter à chaque question.
        contextualized = f"[joueur: {game_name}#{tag_line}] {user_input}"
        try:
            answer, conversation = agent_loop(contextualized, conversation)
        except (RuntimeError, requests.RequestException) as e:
            print(f"\n[erreur] {e}\n")
            continue
        print(f"\nCoach : {answer}\n")
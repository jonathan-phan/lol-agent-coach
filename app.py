"""Streamlit interface: streamlit run app.py"""
import os
import sys

import requests
import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
import riot_client  # noqa: E402
from agent import LLM_API_KEY, agent_loop, tools_used  # noqa: E402
from limits import check_question  # noqa: E402

SAMPLE_QUESTIONS = [
    "Analyze my last game",
    "Was I ahead of my lane opponent in CS at 10 minutes?",
    "At what point did my last game turn?",
    "Did my support help me on my deaths?",
]

st.set_page_config(page_title="LoL Agent Coach", page_icon="🎮")
st.title("LoL Agent Coach")

try:
    data_mode = riot_client.mode()
except riot_client.RiotAPIError as e:
    st.error(str(e))
    st.stop()

if "conversation" not in st.session_state:
    st.session_state.conversation = []
    st.session_state.display = []  # (role, text, tools)
    st.session_state.questions_asked = 0

with st.sidebar:
    if data_mode == "demo":
        name, tag = riot_client.DEMO_PLAYER
        st.info(f"**Demo mode**: analyzing an anonymized sample match as {name}#{tag}. No Riot key needed.")
        game_name, tag_line = name, tag
    else:
        st.success("**Live mode**: your real games, through the Riot API.")
        game_name = st.text_input("Riot name")
        tag_line = st.text_input("Tag (without #)")

    llm_key = st.text_input(
        "Your LLM API key" + (" (optional)" if LLM_API_KEY else ""),
        type="password",
        help="Any OpenAI-compatible provider. Kept only in this browser session, never stored or logged.",
    )

    st.write("**Try a question**")
    for sample in SAMPLE_QUESTIONS:
        if st.button(sample, use_container_width=True):
            st.session_state.pending = sample

    if st.button("Reset conversation"):
        st.session_state.clear()
        st.rerun()

for role, text, tools in st.session_state.display:
    with st.chat_message(role):
        st.write(text)
        if tools:
            st.caption("Tools called: " + ", ".join(tools))

question = st.chat_input("Ask your question") or st.session_state.pop("pending", None)
if question:
    if not game_name or not tag_line:
        st.warning("Fill in the Riot name and tag in the sidebar.")
        st.stop()

    refusal = check_question(question, st.session_state.questions_asked)
    if refusal:
        st.warning(refusal)
        st.stop()

    st.chat_message("user").write(question)
    st.session_state.display.append(("user", question, []))
    st.session_state.questions_asked += 1

    seen = len(st.session_state.conversation)
    tools = []
    try:
        with st.spinner("Analyzing..."):
            answer, st.session_state.conversation = agent_loop(
                f"[player: {game_name}#{tag_line}] {question}",
                st.session_state.conversation,
                api_key=llm_key or None,
            )
        tools = tools_used(st.session_state.conversation[seen:])
    except (RuntimeError, requests.RequestException, riot_client.RiotAPIError) as e:
        answer = f"Error: {e}"

    with st.chat_message("assistant"):
        st.write(answer)
        if tools:
            st.caption("Tools called: " + ", ".join(tools))
    st.session_state.display.append(("assistant", answer, tools))

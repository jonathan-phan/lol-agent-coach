"""Interface Streamlit : streamlit run app.py"""
import os
import sys

import requests
import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from agent import agent_loop  # noqa: E402

st.title("LoL Agent Coach")

with st.sidebar:
    game_name = st.text_input("Pseudo Riot")
    tag_line = st.text_input("Tag (sans #)")

if "conversation" not in st.session_state:
    st.session_state.conversation = []
    st.session_state.display = []

for role, text in st.session_state.display:
    st.chat_message(role).write(text)

if question := st.chat_input("Pose ta question"):
    if not game_name or not tag_line:
        st.warning("Renseigne pseudo et tag dans la barre latérale.")
        st.stop()

    st.chat_message("user").write(question)
    st.session_state.display.append(("user", question))
    try:
        with st.spinner("Analyse en cours..."):
            answer, st.session_state.conversation = agent_loop(
                f"[joueur: {game_name}#{tag_line}] {question}", st.session_state.conversation
            )
    except (RuntimeError, requests.RequestException) as e:
        answer = f"Erreur : {e}"

    st.chat_message("assistant").write(answer)
    st.session_state.display.append(("assistant", answer))

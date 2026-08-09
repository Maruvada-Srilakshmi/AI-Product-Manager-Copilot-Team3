import streamlit as st
from datetime import datetime

from src.llm import chat_response
from src.db import execute, fetch_df, now
from utils.helpers import build_chat_context, ws_id


def _inject_css():
    st.markdown("""
        <style>
        .chat-user-bubble {
            background: linear-gradient(135deg, #6D28D9, #7C3AED);
            color: white;
            padding: 12px 16px;
            border-radius: 14px 14px 2px 14px;
            max-width: 70%;
            margin-left: auto;
            font-size: 14px;
        }
        .chat-ai-row {
            display: flex;
            align-items: flex-start;
            gap: 10px;
            max-width: 78%;
        }
        .chat-ai-avatar {
            background: var(--pm-primary-light);
            border-radius: 50%;
            width: 34px; height: 34px;
            display: flex; align-items: center; justify-content: center;
            font-size: 16px;
            flex-shrink: 0;
        }
        .chat-ai-bubble {
            background: var(--pm-bg);
            border: 1px solid var(--pm-border);
            padding: 12px 16px;
            border-radius: 14px 14px 14px 2px;
            font-size: 14px;
            color: var(--pm-text);
            line-height: 1.6;
        }
        .chat-timestamp {
            font-size: 11px;
            color: var(--pm-text-muted);
            margin: 4px 4px 0 4px;
        }
        .suggested-title {
            font-size: 14px;
            font-weight: 700;
            color: var(--pm-navy);
            margin-bottom: 10px;
        }
        </style>
    """, unsafe_allow_html=True)


_SUGGESTED_QUESTIONS = [
    "What are our top 3 customer pain points?",
    "Which features have the highest RICE score?",
    "What's planned for this quarter?",
    "Give me a summary of recent feedback",
    "What are the top requested features?",
]

_WELCOME = "Hi! I'm your AI Product Manager assistant. Ask me anything about your product, feedback, or roadmap."


def _history_for_backend():
    """Backend expects {"role": "user"/"assistant", "content": str}."""
    return [
        {"role": "user" if m["role"] == "user" else "assistant", "content": m["text"]}
        for m in st.session_state.chat_history
    ]


def _send_message(text: str):
    if not text.strip():
        return
    ts = datetime.now().strftime("%I:%M %p")
    st.session_state.chat_history.append({"role": "user", "text": text, "time": ts})
    execute(
        "INSERT INTO chat_history (workspace_id, role, content, created_at) VALUES (?,?,?,?)",
        (ws_id(), "user", text, now()),
    )

    with st.spinner("AI is thinking..."):
        context = build_chat_context(text)
        reply = chat_response(_history_for_backend(), context)

    st.session_state.chat_history.append({"role": "ai", "text": reply, "time": ts})
    execute(
        "INSERT INTO chat_history (workspace_id, role, content, created_at) VALUES (?,?,?,?)",
        (ws_id(), "assistant", reply, now()),
    )


def show_ai_chat():
    _inject_css()

    if "chat_history" not in st.session_state:
        saved = fetch_df(
            "SELECT role, content, created_at FROM chat_history WHERE workspace_id = ? ORDER BY created_at",
            (ws_id(),),
        )
        if saved.empty:
            st.session_state.chat_history = [
                {"role": "ai", "text": _WELCOME, "time": datetime.now().strftime("%I:%M %p")}
            ]
        else:
            st.session_state.chat_history = [
                {
                    "role": "user" if r.role == "user" else "ai",
                    "text": r.content,
                    "time": str(r.created_at)[11:16] or "",
                }
                for r in saved.itertuples()
            ]

    header_col, clear_col = st.columns([5, 1])
    with header_col:
        st.markdown("### AI Chat Assistant")
        st.caption("Ask anything about your product, feedback, and roadmap — grounded in your real workspace data.")
    with clear_col:
        st.write("")
        if st.button("Clear Chat", use_container_width=True):
            execute("DELETE FROM chat_history WHERE workspace_id = ?", (ws_id(),))
            st.session_state.chat_history = [
                {"role": "ai", "text": _WELCOME, "time": datetime.now().strftime("%I:%M %p")}
            ]
            st.rerun()

    st.write("")

    chat_col, side_col = st.columns([2.3, 1])

    with chat_col:
        chat_box = st.container(height=440, border=True)
        with chat_box:
            for msg in st.session_state.chat_history:
                if msg["role"] == "user":
                    st.markdown(
                        f'<div class="chat-user-bubble">{msg["text"]}</div>'
                        f'<div class="chat-timestamp" style="text-align:right;">{msg["time"]}</div>',
                        unsafe_allow_html=True
                    )
                else:
                    formatted = msg["text"].replace("\n", "<br>")
                    st.markdown(
                        f'<div class="chat-ai-row">'
                        f'<div class="chat-ai-avatar">🤖</div>'
                        f'<div class="chat-ai-bubble">{formatted}</div>'
                        f'</div>'
                        f'<div class="chat-timestamp">{msg["time"]}</div>',
                        unsafe_allow_html=True
                    )
                st.write("")

        question = st.chat_input("Type your question here...")
        if question:
            _send_message(question)
            st.rerun()

    with side_col:
        with st.container(border=True):
            st.markdown('<div class="suggested-title">Suggested Questions</div>', unsafe_allow_html=True)

            for q in _SUGGESTED_QUESTIONS:
                if st.button(q, key=f"suggested_{q}", use_container_width=True):
                    _send_message(q)
                    st.rerun()

import streamlit as st
import requests

st.title("🤖 AI Product Manager Copilot")

user_input = st.text_area("Enter product feedback or feature request:", height=150)

if st.button("Generate PRD", type="primary"):
    if user_input.strip():
        with st.spinner("CrewAI + Gemini processing..."):
            try:
                res = requests.post("http://127.0.0.1:8000/api/generate", json={"prompt": user_input})
                if res.status_code == 200:
                    st.success("Done!")
                    st.markdown(res.json()["response"])
                else:
                    st.error("Backend Error")
            except Exception as e:
                st.error(f"Cannot connect to FastAPI backend: {e}")
    else:
        st.warning("Please enter some text first.")
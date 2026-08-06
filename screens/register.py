import sqlite3

import streamlit as st

from src.db import create_user


def show_register():

    # ---------- CSS ----------
    # Mirrors screens/login.py's hero-panel styling so the two auth pages
    # feel like one flow. Base theme still comes from apply_style() in app.py.
    st.markdown("""
    <style>

    .left-box{
        background:linear-gradient(135deg,#5B21B6,#7C3AED);
        border-radius:25px;
        padding:50px;
        min-height:700px;
        color:white;
    }

    .title{
        font-size:32px;
        font-weight:bold;
    }

    .subtitle{
        font-size:16px;
        color:#E9D5FF;
        line-height:1.6;
    }

    .robot{
        font-size:70px;
        margin-top:60px;
        text-align:center;
    }

    div.stButton > button{
        border-radius:10px;
        height:45px;
        font-weight:600;
    }

    </style>
    """, unsafe_allow_html=True)

    # ---------- Layout ----------
    left, right = st.columns([1, 1])

    # ---------- Left Side ----------
    with left:

        st.markdown("""
        <div class="left-box">

        <div class="title">
        AI Product Manager
        </div>

        <div class="title">
        Copilot
        </div>

        <br>

        <div class="subtitle">
        Turn customer feedback into smarter product decisions
        using Artificial Intelligence.
        </div>

        <div class="robot">
            🤖
            <br>
            📊
        </div>

        </div>
        """, unsafe_allow_html=True)

    # ---------- Right Side ----------
    with right:

        with st.container(border=True):

            st.markdown("## Create Account ✨")
            st.write("Sign up to get started")

            full_name = st.text_input(
                "🧑 Full Name",
                placeholder="Your name"
            )

            email = st.text_input(
                "📧 Email Address",
                placeholder="example@company.com"
            )

            password = st.text_input(
                "🔒 Password",
                type="password",
                placeholder="Create a password"
            )

            confirm_password = st.text_input(
                "🔒 Confirm Password",
                type="password",
                placeholder="Re-enter your password"
            )

            # ---------- Sign Up ----------
            if st.button("Sign Up", use_container_width=True):

                if not full_name or not email or not password:
                    st.error("Please fill in all fields.")
                elif password != confirm_password:
                    st.error("Passwords do not match.")
                elif len(password) < 4:
                    st.error("Password must be at least 4 characters.")
                else:
                    try:
                        create_user(username=email, password=password, role="Product Manager")
                        st.success("Account created! You can now sign in.")
                        st.session_state["auth_page"] = "login"
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("An account with that email already exists.")

            st.write("")

            # ---------- Back to Sign In ----------
            st.markdown(
                """
                <div style="text-align:center;">
                Already have an account?
                </div>
                """,
                unsafe_allow_html=True
            )

            if st.button("Back to Sign In", use_container_width=True):
                st.session_state["auth_page"] = "login"
                st.rerun()

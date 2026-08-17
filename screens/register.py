import sqlite3

import streamlit as st

from src.db import create_user


def show_register():

    # ---------- CSS ----------
    # Mirrors screens/login.py's hero-panel styling so the two auth pages
    # feel like one flow. Base theme still comes from apply_style() in app.py.
    st.markdown("""
    <style>

    .brand-header{
        text-align:center;
        margin-bottom:10px;
    }

    .brand-title{
        font-size:30px;
        font-weight:bold;
        background:linear-gradient(135deg,#5B21B6,#7C3AED);
        -webkit-background-clip:text;
        -webkit-text-fill-color:transparent;
    }

    .brand-subtitle{
        font-size:15px;
        color:#6B7280;
        margin-top:4px;
    }

    div.stButton > button{
        border-radius:10px;
        height:45px;
        font-weight:600;
    }

    </style>
    """, unsafe_allow_html=True)

    # ---------- Layout (centered) ----------
    left_spacer, center, right_spacer = st.columns([1, 1.2, 1])

    with center:

        st.markdown("""
        <div class="brand-header">
            <div class="brand-title">AI Product Manager Copilot</div>
            <div class="brand-subtitle">
                Turn customer feedback into smarter product decisions
                using Artificial Intelligence.
            </div>
        </div>
        """, unsafe_allow_html=True)

        with st.container(border=True):

            st.markdown("## Create Account")
            st.write("Sign up to get started")

            full_name = st.text_input(
                "Full Name",
                placeholder="Your name"
            )

            email = st.text_input(
                "Email Address",
                placeholder="example@company.com"
            )

            password = st.text_input(
                "Password",
                type="password",
                placeholder="Create a password"
            )

            confirm_password = st.text_input(
                "Confirm Password",
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
                        create_user(username=email, password=password, role="Product Manager", name=full_name.strip())
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
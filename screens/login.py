import streamlit as st

from src.db import verify_user, get_user_by_username


def show_login():

    # ---------- CSS ----------
    # Note: base page background/theme now comes from the global
    # apply_style() call in app.py + .streamlit/config.toml, so this
    # only adds the login page's own gradient hero panel.
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

            st.markdown("## Welcome Back 👋")
            st.write("Sign in to continue")

            email = st.text_input(
                "📧 Email Address",
                placeholder="example@company.com"
            )

            password = st.text_input(
                "🔒 Password",
                type="password",
                placeholder="Enter your password"
            )

            col1, col2 = st.columns(2)

            with col1:
                remember = st.checkbox("Remember Me")

            with col2:
                st.markdown(
                    """
                    <div style="
                        text-align:right;
                        color:#2563EB;
                        font-size:14px;
                        margin-top:8px;
                    ">
                    Forgot Password?
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            # ---------- Sign In ----------
            if st.button("Sign In", use_container_width=True):

                if email == "sathvika@gmail.com" and password == "sath":
                    # Demo/shortcut account - still populate a real current_user
                    # so Settings shows this account instead of a hardcoded one.
                    demo_user = get_user_by_username(email) or {
                        "username": email,
                        "role": "Product Manager",
                    }
                    st.session_state.current_user = demo_user
                    st.session_state.logged_in = True
                    st.rerun()
                else:
                    user = verify_user(email, password)
                    if user:
                        st.session_state.current_user = user
                        st.session_state.logged_in = True
                        st.rerun()
                    else:
                        st.error("Invalid Email or Password")

            st.write("")

            # ---------- Sign Up ----------
            st.markdown(
                """
                <div style="text-align:center;">
                Don't have an account?
                </div>
                """,
                unsafe_allow_html=True
            )

            if st.button("Sign Up", use_container_width=True):
                st.session_state["auth_page"] = "register"
                st.rerun()
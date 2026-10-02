"""Entry point: page config, shared theme, navigation. Run with:  streamlit run app.py"""
import streamlit as st

from utils import THEME_CSS

st.set_page_config(page_title="Auto Dashboard", page_icon="📊", layout="wide",
                   initial_sidebar_state="expanded")
st.markdown(THEME_CSS, unsafe_allow_html=True)

pages = [
    st.Page("views/auto_dashboard.py", title="Auto Dashboard", icon="📊", default=True),
    st.Page("views/custom_dashboard.py", title="Custom Dashboard", icon="🧪"),
]
try:
    nav = st.navigation(pages, position="sidebar")   # top bar keeps the sidebar free for page controls
except TypeError:
    nav = st.navigation(pages)                   # older Streamlit: sidebar navigation
nav.run()
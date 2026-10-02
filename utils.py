"""Shared helpers for the Auto Dashboard pages."""
import html
import warnings

import pandas as pd
import plotly.express as px
import streamlit as st

PALETTE = ["#4F46E5", "#06B6D4", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6"]
THEME_CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, .stApp, button, input {font-family:'Inter',sans-serif !important;}
#MainMenu, footer {visibility:hidden;}
header[data-testid="stHeader"] {background:transparent;}
.block-container {padding-top:1.5rem; max-width:1400px;}
.hero {background:linear-gradient(120deg,#312E81 0%,#4F46E5 55%,#06B6D4 130%); border-radius:20px; padding:28px 34px; color:#fff; margin-bottom:22px; box-shadow:0 12px 32px rgba(79,70,229,.25);}
.hero .eyebrow {font-size:.72rem; letter-spacing:.14em; text-transform:uppercase; opacity:.8; font-weight:600;}
.hero .title {font-size:1.9rem; font-weight:700; margin:.3rem 0 .3rem; line-height:1.2;}
.hero .sub {opacity:.85; font-size:.95rem;}
.chip {display:inline-block; background:rgba(255,255,255,.16); border-radius:999px; padding:4px 14px; margin:14px 8px 0 0; font-size:.8rem; font-weight:500;}
[class*="st-key-card_"] {background:#fff; border:1px solid #E8EAF2; border-radius:16px; padding:16px 20px 10px; margin-bottom:8px; box-shadow:0 1px 2px rgba(16,24,40,.04), 0 6px 16px rgba(16,24,40,.04);}
.sec-title {font-weight:600; font-size:1rem; color:#0F172A; padding-top:6px;}
.sec-cap {font-size:.78rem; color:#94A3B8; margin:-6px 0 4px;}
section[data-testid="stSidebar"] {background:#fff; border-right:1px solid #E8EAF2;}
[data-testid="stFileUploader"] section {background:#fff; border:2px dashed #C7CBEF; border-radius:14px;}
[data-testid="stDataFrame"] {border-radius:10px; overflow:hidden;}
.tile {border:1px solid; border-radius:16px; padding:16px 18px; height:100%;}
.tile-top {display:flex; align-items:center; gap:10px; margin-bottom:10px;}
.tile-ico {width:30px; height:30px; border-radius:9px; display:flex; align-items:center; justify-content:center; font-size:.95rem;}
.tile-label {font-size:.8rem; font-weight:600; color:#475569;}
.tile-val {font-size:1.75rem; font-weight:700; line-height:1.1;}
.tile-sub {font-size:.76rem; color:#64748B; margin-top:6px;}
.side-h {font-size:.7rem; letter-spacing:.1em; text-transform:uppercase; color:#94A3B8; font-weight:600; margin:14px 0 2px;}
[data-testid="stSidebarCollapseButton"], [data-testid="stSidebarCollapseButton"] *, [data-testid="stExpandSidebarButton"], [data-testid="stSidebarCollapsedControl"], [data-testid="stSidebarCollapsedControl"] * {opacity:1 !important; visibility:visible !important;}
[data-testid="stSidebarCollapseButton"] button, [data-testid="stExpandSidebarButton"], [data-testid="stSidebarCollapsedControl"] button {background:#EEF2FF !important; color:#4F46E5 !important; border:1px solid #C7D2FE !important; border-radius:10px !important;}
[data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div {border:1px solid #CBD5E1 !important; outline:1px solid #CBD5E1 !important; outline-offset:-1px; border-radius:10px !important; background-color:#fff !important;}
[data-baseweb="input"]:hover, [data-baseweb="textarea"]:hover, [data-baseweb="select"] > div:hover {border-color:#CBD5E1 !important; outline-color:#CBD5E1 !important;}
[data-baseweb="input"]:focus-within, [data-baseweb="textarea"]:focus-within, [data-baseweb="select"] > div:focus-within {border-color:#4F46E5 !important; outline-color:#4F46E5 !important; box-shadow:0 0 0 3px rgba(79,70,229,.15) !important;}
[data-baseweb="base-input"] {border:none !important; outline:none !important; box-shadow:none !important; background:transparent !important;}
</style>"""


# ───────────────────────── Loading & cleaning ─────────────────────────
def read_file(file, sheet=None):
    name = file.name.lower()
    if name.endswith(".csv"):
        for enc in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                file.seek(0)
                return pd.read_csv(file, sep=None, engine="python", encoding=enc)
            except UnicodeDecodeError:
                continue
        raise ValueError("Could not decode the CSV file.")
    file.seek(0)
    return pd.read_excel(file, sheet_name=sheet or 0)


def clean_columns(df):
    df = df.dropna(how="all").dropna(axis=1, how="all").copy()
    cols, seen = [], {}
    for i, c in enumerate(df.columns):
        c = str(c).strip() or f"column_{i + 1}"
        seen[c] = seen.get(c, 0) + 1
        cols.append(c if seen[c] == 1 else f"{c}_{seen[c]}")
    df.columns = cols
    return df.reset_index(drop=True)


def to_numeric_text(s):
    stripped = s.astype(str).str.replace(r"[,\$€£₹%\s]", "", regex=True)
    return pd.to_numeric(stripped, errors="coerce")


def infer_types(df):
    """Return (converted_df, {col: type}). Types: numeric, datetime, categorical, boolean, id, text."""
    df, types = df.copy(), {}
    n = len(df)
    for c in df.columns:
        s, nn = df[c], df[c].notna().sum()
        if nn == 0:
            types[c] = "text"
        elif pd.api.types.is_bool_dtype(s):
            types[c] = "boolean"
        elif pd.api.types.is_datetime64_any_dtype(s):
            types[c] = "datetime"
        elif pd.api.types.is_numeric_dtype(s):
            is_int = (s.dropna() % 1 == 0).all()
            types[c] = "id" if (is_int and s.nunique() == nn and nn > 20 and nn == n) else "numeric"
        else:
            s = s.astype(object)
            num = to_numeric_text(s[s.notna()])
            if num.notna().mean() >= 0.9:
                df[c] = to_numeric_text(s.where(s.notna()))
                types[c] = "numeric"
                continue
            sample = s.dropna().astype(str)
            if sample.str.len().mean() < 40 and sample.str.contains(r"\d").mean() > 0.9:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    dt = pd.to_datetime(s, errors="coerce")
                if dt.notna().sum() / nn >= 0.9:
                    df[c] = dt
                    types[c] = "datetime"
                    continue
            nu = s.nunique()
            if nu <= 2 and nn > 2:
                types[c] = "boolean"
            elif nu <= 50 or nu / nn <= 0.3:
                types[c] = "categorical"
            else:
                types[c] = "text"
    return df, types


# ───────────────────────── Helpers ─────────────────────────
def fmt(x):
    if pd.isna(x):
        return "–"
    a = abs(x)
    for lim, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= lim:
            return f"{x / lim:,.2f}{suf}"
    return f"{x:,.0f}" if float(x).is_integer() else f"{x:,.2f}"


def style(fig, height=320):
    fig.update_layout(
        template="plotly_white", colorway=PALETTE, height=height, title=None,
        font=dict(family="Inter, sans-serif", size=12, color="#475569"),
        margin=dict(l=4, r=4, t=10, b=4), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        hoverlabel=dict(bgcolor="#0F172A", font_color="#fff", bordercolor="#0F172A"),
    )
    fig.update_xaxes(showgrid=False, linecolor="#E2E8F0", title_text=None)
    fig.update_yaxes(gridcolor="#EEF0F6", zeroline=False)
    return fig


def show(obj, kind="plot", **kw):
    if kind == "plot":
        fn, kw = st.plotly_chart, {"config": {"displayModeBar": False}, **kw}
        obj = style(obj)
    else:
        fn = st.dataframe
    try:
        fn(obj, width="stretch", **kw)
    except TypeError:
        fn(obj, use_container_width=True, **kw)


def cols_of(types, *kinds):
    return [c for c, t in types.items() if t in kinds]


TILE_COLORS = [("#EEF2FF", "#4338CA", "#E0E7FF"), ("#ECFEFF", "#0E7490", "#CFFAFE"),
               ("#ECFDF5", "#047857", "#D1FAE5"), ("#FFFBEB", "#B45309", "#FEF3C7"),
               ("#FFF1F2", "#BE123C", "#FFE4E6"), ("#F5F3FF", "#6D28D9", "#EDE9FE")]


def tiles(items):
    for col, (label, value, sub, icon, ci) in zip(st.columns(len(items)), items):
        bg, fg, bd = TILE_COLORS[ci % len(TILE_COLORS)]
        col.markdown(
            f'<div class="tile" style="background:{bg};border-color:{bd}">'
            f'<div class="tile-top"><span class="tile-ico" style="background:{bd};color:{fg}">{icon}</span>'
            f'<span class="tile-label">{html.escape(str(label))}</span></div>'
            f'<div class="tile-val" style="color:{fg}">{html.escape(str(value))}</div>'
            f'<div class="tile-sub">{html.escape(str(sub))}</div></div>', unsafe_allow_html=True)
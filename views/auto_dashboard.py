"""Auto Dashboard view: upload a CSV/Excel file and get an instant dashboard.
Sections can be shown or hidden from the sidebar (but not edited)."""
import hashlib
import html

import pandas as pd
import plotly.express as px
import streamlit as st

from utils import PALETTE, clean_columns, cols_of, fmt, infer_types, read_file, show, tiles

MAX_HIST, MAX_BARS, MAX_LINES, MAX_CAT_NUM = 4, 4, 3, 2


# ───────────────────────── Section definitions ─────────────────────────
def build_sections(df, types):
    num, dates = cols_of(types, "numeric"), cols_of(types, "datetime")
    cats = cols_of(types, "categorical", "boolean")
    S = []

    def add(id_, title, kind, half=False, **params):
        S.append(dict(id=id_, title=title, kind=kind, half=half, params=params))

    # Preview first, then summary tiles, then other tables
    add("preview", "Data preview", "preview")
    add("overview", "Dataset overview", "overview")
    if num:
        add("kpis", "Key metrics", "kpis")
    add("profile", "Column profile", "profile")
    if num:
        add("describe", "Numeric summary", "describe")

    # Charts
    for d in dates[:1]:
        if num:
            for n in num[:MAX_LINES]:
                add(f"line_{d}_{n}", f"{n} over time", "line", True, date=d, num=n)
        else:
            add(f"line_{d}", f"Records over time ({d})", "line", True, date=d, num=None)
    for c in cats[:MAX_BARS]:
        add(f"bar_{c}", f"Top values: {c}", "bar_count", True, cat=c)
    for c in [x for x in cats if 2 <= df[x].nunique() <= 15][:MAX_CAT_NUM]:
        if num:
            add(f"catnum_{c}", f"{num[0]} by {c}", "bar_sum", True, cat=c, num=num[0])
    for n in num[:MAX_HIST]:
        add(f"hist_{n}", f"Distribution of {n}", "hist", True, num=n)
    if len(num) >= 2:
        add("corr", "Correlation heatmap", "corr", True)
        add("scatter", "Strongest relationship", "scatter", True)
    if df.isna().any().any():
        add("missing", "Missing values by column", "missing", True)
    return S


def render(sec, df, types):
    k, p = sec["kind"], sec["params"]
    num = cols_of(types, "numeric")

    dates, cats = cols_of(types, "datetime"), cols_of(types, "categorical", "boolean")
    if k == "overview":
        miss = int(df.isna().sum().sum())
        tiles([
            ("Rows", f"{len(df):,}", "records in file", "📄", 0),
            ("Columns", len(df.columns), f"{len(num)} numeric · {len(dates)} date · {len(cats)} category", "🧱", 1),
            ("Completeness", f"{1 - df.isna().mean().mean():.1%}", f"{miss:,} missing cells", "✅", 2),
            ("Duplicate rows", f"{df.duplicated().sum():,}", "exact repeats", "🧬", 3),
            ("Memory", f"{df.memory_usage(deep=True).sum() / 1e6:,.1f} MB", "in-memory size", "💾", 5),
        ])

    elif k == "kpis":
        icons = ["📈", "💵", "🧮", "📊"]
        tiles([(f"Total {n}", fmt(df[n].sum()), f"avg {fmt(df[n].mean())} · max {fmt(df[n].max())}", icons[i], i + 1)
               for i, n in enumerate(num[:4])])

    elif k == "profile":
        prof = pd.DataFrame({
            "Column": df.columns,
            "Detected type": [types[c] for c in df.columns],
            "Non-null": [int(df[c].notna().sum()) for c in df.columns],
            "Unique": [int(df[c].nunique()) for c in df.columns],
            "Example": [str(df[c].dropna().iloc[0]) if df[c].notna().any() else "" for c in df.columns],
        })
        show(prof, "table", hide_index=True)

    elif k == "describe":
        show(df[num].describe().T.round(2), "table")

    elif k == "preview":
        show(df.head(100), "table", height=300)

    elif k == "line":
        d, n = p["date"], p["num"]
        x = df.dropna(subset=[d])
        span = (x[d].max() - x[d].min()).days
        per, label = ("M", "month") if span > 730 else ("W", "week") if span > 90 else ("D", "day")
        key = x[d].dt.to_period(per).dt.to_timestamp()
        if n:
            g = x.groupby(key)[n].sum().reset_index()
            g.columns = ["Date", n]
            fig = px.line(g, x="Date", y=n, markers=True)
            st.markdown(f'<div class="sec-cap">Sum of {n} per {label}</div>', unsafe_allow_html=True)
        else:
            g = x.groupby(key).size().reset_index(name="Records")
            g.columns = ["Date", "Records"]
            fig = px.line(g, x="Date", y="Records", markers=True)
            st.markdown(f'<div class="sec-cap">Records per {label}</div>', unsafe_allow_html=True)
        fig.update_traces(line=dict(width=3, color=PALETTE[0]), marker=dict(size=6),
                          fill="tozeroy", fillcolor="rgba(79,70,229,0.08)")
        show(fig)

    elif k == "bar_count":
        vc = df[p["cat"]].astype(str).value_counts().head(10).reset_index()
        vc.columns = [p["cat"], "Count"]
        fig = px.bar(vc, x="Count", y=p["cat"], orientation="h").update_yaxes(autorange="reversed", title_text=None)
        show(fig.update_traces(marker_color=PALETTE[0]))

    elif k == "bar_sum":
        g = df.groupby(p["cat"])[p["num"]].sum().sort_values(ascending=False).head(15).reset_index()
        show(px.bar(g, x=p["cat"], y=p["num"]).update_traces(marker_color=PALETTE[1]))

    elif k == "hist":
        fig = px.histogram(df, x=p["num"], nbins=30).update_traces(marker_color=PALETTE[2])
        show(fig.update_layout(bargap=0.05))

    elif k == "corr":
        scale = [[0, "#EF4444"], [0.5, "#FFFFFF"], [1, "#4F46E5"]]
        show(px.imshow(df[num].corr(), text_auto=".2f", color_continuous_scale=scale, zmin=-1, zmax=1))

    elif k == "scatter":
        c = df[num].corr().abs()
        for i in range(len(c)):
            c.iloc[i, i] = 0
        a, b = c.stack().idxmax()
        st.markdown(f'<div class="sec-cap">{a} vs {b}</div>', unsafe_allow_html=True)
        show(px.scatter(df, x=a, y=b, opacity=0.65).update_traces(marker=dict(color=PALETTE[5], size=7)))

    elif k == "missing":
        m = df.isna().sum()
        m = m[m > 0].sort_values(ascending=False).reset_index()
        m.columns = ["Column", "Missing"]
        show(px.bar(m, x="Column", y="Missing").update_traces(marker_color=PALETTE[3]))


# ───────────────────────── App ─────────────────────────
GROUPS = {"overview": "Summary", "kpis": "Summary", "preview": "Tables", "profile": "Tables", "describe": "Tables"}


def set_all(val):
    for s in st.session_state.get("sections", []):
        st.session_state[f"show_{s['id']}"] = val


hero = st.empty()


def set_hero(title, sub, chips=()):
    c = "".join(f'<span class="chip">{html.escape(x)}</span>' for x in chips)
    hero.markdown(
        f'<div class="hero"><div class="eyebrow">Auto Dashboard</div>'
        f'<div class="title">{html.escape(title)}</div><div class="sub">{html.escape(sub)}</div>{c}</div>',
        unsafe_allow_html=True)


# Sidebar: upload lives here
with st.sidebar:
    st.markdown("### 📊 Auto Dashboard")
    st.markdown('<div class="side-h">Data source</div>', unsafe_allow_html=True)
    file = st.file_uploader("Upload CSV or Excel", type=["csv", "xlsx", "xls"], label_visibility="collapsed")
    sheet = None
    if file and file.name.lower().endswith((".xlsx", ".xls")):
        sheet = st.selectbox("Sheet", pd.ExcelFile(file).sheet_names)

if not file:
    # Before a file is uploaded the sidebar is locked open (no hide/show arrow)
    st.markdown("""<style>
    [data-testid="stSidebarCollapseButton"], [data-testid="stSidebarCollapsedControl"], [data-testid="stExpandSidebarButton"] {display:none !important;}
    section[data-testid="stSidebar"][aria-expanded="false"] {transform:none !important; margin-left:0 !important; width:21rem !important; min-width:21rem !important;}
    </style>""", unsafe_allow_html=True)
    set_hero("Turn any spreadsheet into a dashboard",
             "Upload a CSV or Excel file from the sidebar. We detect your columns and build the dashboard automatically.")
    st.stop()

sig = hashlib.md5(file.getvalue()).hexdigest() + str(sheet)
if st.session_state.get("sig") != sig:
    try:
        raw = clean_columns(read_file(file, sheet))
    except Exception as e:
        st.error(f"Could not read the file: {e}")
        st.stop()
    if raw.empty:
        st.warning("The file has no data.")
        st.stop()
    df, types = infer_types(raw)
    st.session_state.update(sig=sig, df=df, types=types, sections=build_sections(df, types))
    set_all(True)

df, types, sections = st.session_state.df, st.session_state.types, st.session_state.sections
for s in sections:
    st.session_state.setdefault(f"show_{s['id']}", True)

# Sidebar: one checkbox per section
with st.sidebar:
    st.markdown('<div class="side-h">Dashboard sections</div>', unsafe_allow_html=True)
    b1, b2 = st.columns(2)
    b1.button("Show all", on_click=set_all, args=(True,))
    b2.button("Hide all", on_click=set_all, args=(False,))
    for group in ("Summary", "Tables", "Charts"):
        items = [s for s in sections if GROUPS.get(s["kind"], "Charts") == group]
        if items:
            st.markdown(f'<div class="side-h">{group}</div>', unsafe_allow_html=True)
            for s in items:
                st.checkbox(s["title"], key=f"show_{s['id']}")

visible = [s for s in sections if st.session_state.get(f"show_{s['id']}", True)]

set_hero(file.name, "Dashboard generated from your data", [
    f"{len(df):,} rows", f"{len(df.columns)} columns",
    f"{len(cols_of(types, 'numeric'))} numeric", f"{len(cols_of(types, 'datetime'))} date",
    f"{len(cols_of(types, 'categorical', 'boolean'))} categorical",
    f"{len(visible)}/{len(sections)} sections shown"])


def card(sec):
    bare = sec["kind"] in ("overview", "kpis")
    with st.container(key=f"{'bare' if bare else 'card'}_{sec['id']}"):
        st.markdown(f'<div class="sec-title">{html.escape(sec["title"])}</div>', unsafe_allow_html=True)
        render(sec, df, types)


pending = []


def flush():
    for i in range(0, len(pending), 2):
        row = st.columns(2)
        for col, sec in zip(row, pending[i:i + 2]):
            with col:
                card(sec)
    pending.clear()


for s in visible:
    if s["half"]:
        pending.append(s)
    else:
        flush()
        card(s)
flush()

if not visible:
    st.info("No sections selected. Tick some sections in the sidebar.")
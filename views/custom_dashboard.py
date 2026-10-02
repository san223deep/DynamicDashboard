"""Custom Dashboard view: a notebook-style page. Each cell = pick data -> pick an operation -> run."""
import html
import io
import textwrap
from functools import reduce
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from utils import PALETTE, clean_columns, infer_types, read_file, show

st.markdown("""<style>
html, [data-testid="stMain"], section.main {scroll-behavior:smooth;}
[class*="st-key-card_open"] {border:1.5px solid #6366F1 !important; box-shadow:0 0 0 5px rgba(99,102,241,.10), 0 6px 16px rgba(16,24,40,.05) !important;}
[class*="st-key-card_"] h3 {font-size:1.15rem; font-weight:700; padding:2px 0 0; color:#0F172A; scroll-margin-top:70px;}
.nav-item {display:flex; gap:10px; align-items:flex-start; padding:8px 10px; border-radius:12px; text-decoration:none !important; color:#0F172A !important; margin-bottom:2px;}
.nav-item:hover {background:#EEF2FF;}
.nav-n {min-width:24px; height:24px; border-radius:8px; background:#E0E7FF; color:#4338CA; font-size:.78rem; font-weight:700; display:flex; align-items:center; justify-content:center;}
.nav-item.open .nav-n {background:#4F46E5; color:#fff;}
.nav-t b {display:block; font-size:.86rem; font-weight:600; line-height:1.2;}
.nav-t small {display:block; color:#64748B; font-size:.72rem; line-height:1.25; margin-top:1px;}
[class*="st-key-card_"] [data-testid="stVerticalBlock"] {gap:.65rem;}
[class*="st-key-card_"] label p {font-size:.8rem; font-weight:600; color:#475569;}
[data-baseweb="tab-list"] {gap:6px; border-bottom:1px solid #E8EAF2;}
[data-baseweb="tab"] {font-weight:600; padding:6px 14px !important; height:auto !important;}
[data-baseweb="tab-panel"] {padding-top:.7rem !important;}
.ds {font-size:.8rem; color:#334155; padding:2px 0;} .ds small {color:#94A3B8;}
</style>""", unsafe_allow_html=True)

ss = st.session_state
ss.setdefault("nb_datasets", {})   # name -> {"df", "types"}
ss.setdefault("nb_cells", [])      # finished cells
ss.setdefault("nb_n", 1)           # number of the open cell

# ───────────────────────── Chart catalogue ─────────────────────────
SLOT = {"x": "X axis", "y": "Y axis (numeric)", "color": "Color / group by", "size": "Size (numeric)",
        "names": "Categories", "values": "Values (numeric)", "z": "Z axis (numeric)", "r": "Radius (numeric)",
        "theta": "Angle (categories)", "cols": "Numeric columns", "path": "Hierarchy (in order)",
        "date": "Date", "open": "Open", "high": "High", "low": "Low", "close": "Close"}
NUMERIC = {"y", "values", "size", "z", "r", "open", "high", "low", "close"}
BAR = ["x", "y", "color?"]
CHARTS = {
    "Line": BAR, "Area": BAR, "Bar": BAR, "Horizontal bar": BAR, "Stacked bar": BAR,
    "Grouped bar": BAR, "100% stacked bar": BAR,
    "Scatter": ["x", "y", "color?", "size?"], "Bubble": ["x", "y", "size", "color?"],
    "Histogram": ["x", "color?"], "ECDF": ["x", "color?"],
    "Box": ["y", "x?", "color?"], "Violin": ["y", "x?", "color?"], "Strip": ["y", "x?", "color?"],
    "Pie": ["names", "values"], "Donut": ["names", "values"], "Funnel": ["names", "values"],
    "Sunburst": ["path", "values"], "Treemap": ["path", "values"],
    "Radar": ["theta", "r", "color?"], "Polar bar": ["theta", "r", "color?"],
    "Waterfall": ["x", "y"], "Candlestick": ["date", "open", "high", "low", "close"],
    "Density heatmap": ["x", "y"], "Density contour": ["x", "y"],
    "Correlation heatmap": ["cols"], "Scatter matrix": ["cols", "color?"],
    "Parallel coordinates": ["cols", "color?"], "3D scatter": ["x", "y", "z", "color?"],
}
AGG_KINDS = {"Line", "Area", "Bar", "Horizontal bar", "Stacked bar", "Grouped bar", "100% stacked bar", "Pie",
             "Donut", "Funnel", "Radar", "Polar bar", "Waterfall", "Sunburst", "Treemap"}
HOW = {"Sum": "sum", "Mean": "mean", "Median": "median", "Min": "min", "Max": "max", "Count": "count"}
OPS = {
    "num": ["=", "≠", ">", "≥", "<", "≤", "between", "is empty", "is not empty"],
    "date": ["on", "before", "after", "between", "is empty", "is not empty"],
    "cat": ["equals", "not equals", "is one of", "contains", "is empty", "is not empty"],
    "text": ["contains", "equals", "not equals", "starts with", "ends with", "is empty", "is not empty"],
}


# ───────────────────────── Data helpers ─────────────────────────
@st.cache_data(show_spinner=False)
def excel_sheets(data):
    return pd.ExcelFile(io.BytesIO(data)).sheet_names


@st.cache_data(show_spinner="Reading file…")
def load_bytes(name, data, sheet):
    f = io.BytesIO(data)
    f.name = name
    return infer_types(clean_columns(read_file(f, sheet)))


def numbered(d):
    d = d.copy()
    d.index = range(1, len(d) + 1)
    return d


def unique(name):
    base, i = name, 2
    while name in ss.nb_datasets:
        name, i = f"{base}_{i}", i + 1
    return name


def short(s, n=46):
    return textwrap.shorten(str(s), n, placeholder="…")


def plot(fig):
    cfg = {"displaylogo": False}
    try:
        st.plotly_chart(fig, width="stretch", config=cfg)
    except TypeError:
        st.plotly_chart(fig, use_container_width=True, config=cfg)


# ───────────────────────── Row selection ─────────────────────────
def parse_rows(text, n):
    idx = []
    for part in text.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            idx += range(int(a), int(b) + 1)
        elif part:
            idx.append(int(part))
    return [i - 1 for i in idx if 1 <= i <= n], [i for i in idx if not 1 <= i <= n]


def row_selector(df, p):
    n = len(df)
    mode = st.radio("Rows", ["All rows", "First N", "Row range", "Specific rows"], horizontal=True, key=p + "rmode")
    if mode == "First N":
        k = int(st.number_input("N", 1, max(n, 1), min(10, n), key=p + "rn"))
        return df.head(k), f"first {k} rows"
    if mode == "Row range":
        c1, c2 = st.columns(2)
        a = int(c1.number_input("From row", 1, max(n, 1), 1, key=p + "ra"))
        b = int(c2.number_input("To row", 1, max(n, 1), min(n, 50), key=p + "rb"))
        a, b = min(a, b), max(a, b)
        return df.iloc[a - 1:b], f"rows {a}–{b}"
    if mode == "Specific rows":
        t = st.text_input("Row numbers (1-based)", placeholder="e.g. 1-5, 9, 12", key=p + "rs")
        if not t.strip():
            return df, ""
        try:
            idx, bad = parse_rows(t, n)
        except ValueError:
            st.warning("Use numbers and ranges like `1-5, 9, 12`.")
            return df, ""
        if bad:
            st.warning(f"Ignored rows outside 1–{n}: {bad[:10]}")
        return df.iloc[idx], f"rows {t.strip()}"
    return df, ""


# ───────────────────────── Condition builder ─────────────────────────
def condition(s, kind, op, box, key):
    name = s.name
    if op == "is empty":
        return s.isna(), f"{name} is empty"
    if op == "is not empty":
        return s.notna(), f"{name} is not empty"
    if kind == "num":
        lo, hi = (0.0 if pd.isna(v) else float(v) for v in (s.min(), s.max()))
        if op == "between":
            a = box.number_input("From", value=lo, key=key + "a")
            b = box.number_input("To", value=hi, key=key + "b")
            return s.between(a, b), f"{name} between {a:g} and {b:g}"
        v = box.number_input("Value", value=0.0 if pd.isna(s.median()) else float(s.median()), key=key)
        m = {"=": s == v, "≠": s != v, ">": s > v, "≥": s >= v, "<": s < v, "≤": s <= v}[op]
        return m, f"{name} {op} {v:g}"
    if kind == "date":
        lo = s.min().date() if s.notna().any() else pd.Timestamp.today().date()
        if op == "between":
            r = box.date_input("Range", value=(lo, s.max().date() if s.notna().any() else lo), key=key)
            if not (isinstance(r, tuple) and len(r) == 2):
                return pd.Series(True, index=s.index), f"{name} (pick end date)"
            a, b = pd.Timestamp(r[0]), pd.Timestamp(r[1]) + pd.Timedelta(days=1)
            return (s >= a) & (s < b), f"{name} between {r[0]} and {r[1]}"
        v = pd.Timestamp(box.date_input("Date", value=lo, key=key))
        m = {"on": s.dt.normalize() == v, "before": s < v, "after": s >= v + pd.Timedelta(days=1)}[op]
        return m, f"{name} {op} {v.date()}"
    sa = s.astype("string")
    if kind == "cat" and op in ("equals", "not equals"):
        v = box.selectbox("Value", sorted(sa.dropna().unique()), key=key)
        return (sa == v) if op == "equals" else (sa != v), f"{name} {'=' if op == 'equals' else '≠'} {v}"
    if op == "is one of":
        v = box.multiselect("Values", sorted(sa.dropna().unique()), key=key)
        return (sa.isin(v) if v else pd.Series(True, index=s.index)), f"{name} in {v}"
    v = box.text_input("Text", key=key)
    if not v:
        return pd.Series(True, index=s.index), f"{name} {op} …"
    m = {"contains": sa.str.contains(v, case=False, regex=False), "equals": sa == v, "not equals": sa != v,
         "starts with": sa.str.lower().str.startswith(v.lower()), "ends with": sa.str.lower().str.endswith(v.lower())}[op]
    return m, f"{name} {op} '{v}'"


def filter_builder(df, types, p):
    k = int(st.number_input("Number of conditions", 1, 6, 1, key=p + "nc"))
    join = st.radio("Combine with", ["AND", "OR"], horizontal=True, key=p + "join") if k > 1 else "AND"
    masks, descs = [], []
    for i in range(k):
        c1, c2, c3 = st.columns([1.2, 1, 1.6])
        col = c1.selectbox("Column", list(df.columns), key=f"{p}fc{i}")
        t = types.get(col, "text")
        kind = "num" if t in ("numeric", "id") else "date" if t == "datetime" else "cat" if t in ("categorical", "boolean") else "text"
        op = c2.selectbox("Condition", OPS[kind], key=f"{p}fo{i}_{kind}")
        m, d = condition(df[col], kind, op, c3, f"{p}fv{i}_{col}_{op}")
        masks.append(m.fillna(False).astype(bool))
        descs.append(d)
    mask = reduce(lambda a, b: (a & b) if join == "AND" else (a | b), masks)
    return mask, f" {join} ".join(descs)


# ───────────────────────── Group by ─────────────────────────
GFN = {"Sum": "sum", "Mean": "mean", "Median": "median", "Min": "min", "Max": "max",
       "Count": "count", "Distinct count": "nunique"}
PER = {"Day": "D", "Week": "W", "Month": "M", "Quarter": "Q", "Year": "Y"}


def group_builder(df, types, p):
    """Group by column(s) and aggregate. Returns (table, description, column_types) or (None, '', None)."""
    cols = list(df.columns)
    num = [c for c in cols if types.get(c) in ("numeric", "id")]
    c1, c2 = st.columns(2)
    keys = c1.multiselect("Group by column(s)", cols, key=p + "gk")
    vals = c2.multiselect("Columns to aggregate", [c for c in num if c not in keys], key=p + "gv")
    c3, c4, c5 = st.columns(3)
    fns = c3.multiselect("Aggregate with", list(GFN), default=["Sum"], key=p + "gf")
    has_date = any(types.get(k) == "datetime" for k in keys)
    per = c4.selectbox("Group dates by", ["As is"] + list(PER), index=3, key=p + "gp") if has_date else "As is"
    order = c5.selectbox("Sort groups", ["By group", "Largest first", "Smallest first"], key=p + "go")
    count = st.checkbox("Add row count", value=True, key=p + "gc")
    if not keys:
        st.info("Pick at least one column to group by.")
        return None, "", None
    if not ((vals and fns) or count):
        st.info("Pick columns to aggregate, or turn on the row count.")
        return None, "", None
    d = df[list(dict.fromkeys(keys + vals))].copy()
    gkeys, nt = [], {}
    for k in keys:
        if types.get(k) == "datetime" and per != "As is":
            name = f"{k} ({per.lower()})"
            d[name] = d[k].dt.to_period(PER[per]).dt.to_timestamp()
            gkeys.append(name)
            nt[name] = "datetime"
        else:
            gkeys.append(k)
            nt[k] = types.get(k, "text")
    g = d.groupby(gkeys)
    parts, named = [], {f"{c} ({fn.lower()})": (c, GFN[fn]) for c in vals for fn in fns}
    if named:
        parts.append(g.agg(**named))
        nt.update({k: "numeric" for k in named})
    if count:
        parts.append(g.size().rename("Rows"))
        nt["Rows"] = "numeric"
    res = pd.concat(parts, axis=1).reset_index()
    if order != "By group":
        res = res.sort_values([c for c in res.columns if c not in gkeys][0], ascending=order == "Smallest first")
    what = [f"{fn.lower()} {c}" for c in vals for fn in fns] + (["row count"] if count else [])
    return res.reset_index(drop=True), "Group by " + ", ".join(keys) + ": " + ", ".join(what), nt


# ───────────────────────── Charts ─────────────────────────
def make_chart(kind, c, d, how, title):
    x, y, col, size = c.get("x"), c.get("y"), c.get("color"), c.get("size")

    def A(dims, val):
        dims = [k for k in dict.fromkeys(dims) if k]
        if how == "None (raw)" or not dims or not val:
            return d
        return getattr(d.groupby(dims, dropna=False)[val], HOW[how])().reset_index()

    if kind in ("Line", "Area"):
        d2 = A([x, col], y).sort_values(x)
        fig = (px.line(d2, x=x, y=y, color=col, markers=True) if kind == "Line" else px.area(d2, x=x, y=y, color=col))
    elif kind in ("Bar", "Stacked bar", "Grouped bar", "100% stacked bar"):
        fig = px.bar(A([x, col], y), x=x, y=y, color=col)
        mode = {"Stacked bar": "stack", "Grouped bar": "group", "100% stacked bar": "stack"}.get(kind)
        if mode:
            fig.update_layout(barmode=mode)
        if kind == "100% stacked bar":
            fig.update_layout(barnorm="percent")
    elif kind == "Horizontal bar":
        fig = px.bar(A([x, col], y), x=y, y=x, color=col, orientation="h")
    elif kind in ("Scatter", "Bubble"):
        fig = px.scatter(d.dropna(subset=[size]) if size else d, x=x, y=y, color=col, size=size, opacity=0.75)
    elif kind == "Histogram":
        fig = px.histogram(d, x=x, color=col, nbins=30, barmode="overlay", opacity=0.85 if col else 1)
    elif kind == "ECDF":
        fig = px.ecdf(d, x=x, color=col)
    elif kind == "Box":
        fig = px.box(d, x=x, y=y, color=col)
    elif kind == "Violin":
        fig = px.violin(d, x=x, y=y, color=col, box=True)
    elif kind == "Strip":
        fig = px.strip(d, x=x, y=y, color=col)
    elif kind in ("Pie", "Donut"):
        fig = px.pie(A([c["names"]], c["values"]), names=c["names"], values=c["values"], hole=0.45 if kind == "Donut" else 0)
    elif kind == "Funnel":
        d2 = A([c["names"]], c["values"]).sort_values(c["values"], ascending=False)
        fig = px.funnel(d2, x=c["values"], y=c["names"])
    elif kind in ("Sunburst", "Treemap"):
        path = c["path"]
        d2 = A(path, c["values"]).dropna(subset=path)
        fig = (px.sunburst if kind == "Sunburst" else px.treemap)(d2, path=path, values=c["values"])
    elif kind in ("Radar", "Polar bar"):
        d2 = A([c["theta"], col], c["r"])
        if kind == "Radar":
            fig = px.line_polar(d2, r=c["r"], theta=c["theta"], color=col, line_close=True).update_traces(fill="toself")
        else:
            fig = px.bar_polar(d2, r=c["r"], theta=c["theta"], color=col)
    elif kind == "Waterfall":
        d2 = A([x], y)
        fig = go.Figure(go.Waterfall(x=d2[x].astype(str).tolist(), y=d2[y].tolist(), measure=["relative"] * len(d2),
                                     increasing=dict(marker=dict(color=PALETTE[2])),
                                     decreasing=dict(marker=dict(color=PALETTE[4])),
                                     connector=dict(line=dict(color="#CBD5E1"))))
    elif kind == "Candlestick":
        dd = d.dropna(subset=[c[k] for k in ("date", "open", "high", "low", "close")]).sort_values(c["date"])
        fig = go.Figure(go.Candlestick(x=dd[c["date"]], open=dd[c["open"]], high=dd[c["high"]],
                                       low=dd[c["low"]], close=dd[c["close"]]))
        fig.update_layout(xaxis_rangeslider_visible=False)
    elif kind == "Density heatmap":
        fig = px.density_heatmap(d, x=x, y=y, nbinsx=25, nbinsy=25, color_continuous_scale="Purples")
    elif kind == "Density contour":
        fig = px.density_contour(d, x=x, y=y)
    elif kind == "Correlation heatmap":
        if len(c["cols"]) < 2:
            raise ValueError("Pick at least 2 numeric columns.")
        fig = px.imshow(d[c["cols"]].corr(), text_auto=".2f", zmin=-1, zmax=1,
                        color_continuous_scale=[[0, "#EF4444"], [0.5, "#FFFFFF"], [1, "#4F46E5"]])
    elif kind == "Scatter matrix":
        fig = px.scatter_matrix(d, dimensions=c["cols"], color=col).update_traces(diagonal_visible=False, marker=dict(size=4))
    elif kind == "Parallel coordinates":
        dd = d.dropna(subset=c["cols"] + ([col] if col else []))
        fig = px.parallel_coordinates(dd, dimensions=c["cols"], color=col, color_continuous_scale=px.colors.sequential.Indigo)
    else:  # 3D scatter
        fig = px.scatter_3d(d, x=x, y=y, z=c["z"], color=col)
    fig.update_layout(
        template="plotly_white", colorway=PALETTE, height=380, title_text=title or "",
        font=dict(family="Inter, sans-serif", size=12, color="#475569"),
        margin=dict(l=8, r=8, t=50 if title else 16, b=8), paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)", hoverlabel=dict(bgcolor="#0F172A", font_color="#fff"))
    return fig


def chart_ui(d, types, p):
    kind = st.selectbox("Chart type", list(CHARTS), key=p + "ck")
    cols = list(d.columns)
    num = [c for c in cols if types.get(c) in ("numeric", "id")]
    sel, spec = {}, CHARTS[kind]
    boxes = st.columns(min(len(spec), 3))
    for i, s in enumerate(spec):
        name, opt = s.rstrip("?"), s.endswith("?")
        box, key = boxes[i % len(boxes)], f"{p}s_{kind}_{name}"
        pool = num if (name in NUMERIC or name == "cols" or (kind == "Parallel coordinates" and name == "color")) else cols
        if name in ("path", "cols"):
            sel[name] = box.multiselect(SLOT[name], pool, default=pool[:4] if name == "cols" else pool[:1], key=key)
        elif opt:
            v = box.selectbox(SLOT[name] + " (optional)", ["—"] + pool, key=key)
            sel[name] = None if v == "—" else v
        else:
            sel[name] = box.selectbox(SLOT[name], pool, key=key) if pool else None
    how = "None (raw)"
    if kind in AGG_KINDS:
        how = st.selectbox("Aggregate values", ["Sum", "Mean", "Median", "Min", "Max", "Count", "None (raw)"], key=p + "agg")
    title = st.text_input("Chart title (optional)", key=p + "ct")
    missing = [SLOT[s.rstrip("?")] for s in spec if not s.endswith("?") and not sel.get(s.rstrip("?"))]
    if missing:
        st.info("Choose: " + ", ".join(missing) + (" (this dataset needs numeric columns)" if not num else ""))
        return None, ""
    try:
        fig = make_chart(kind, sel, d, how, title)
    except Exception as e:
        st.error(f"Could not draw this chart: {e}")
        return None, ""
    parts = [", ".join(v) if isinstance(v, list) else v for v in sel.values() if v]
    return fig, f"{kind}: " + ", ".join(parts) + ("" if how == "None (raw)" or kind not in AGG_KINDS else f" ({how.lower()})")


# ───────────────────────── Cells ─────────────────────────
DATA_H, OUT_H = 380, 380


def tabs_default(labels, default):
    """st.tabs with a chosen default tab (falls back to putting that tab first on older Streamlit)."""
    try:
        return st.tabs(labels, default=default)
    except TypeError:
        order = [default] + [l for l in labels if l != default]
        t = dict(zip(order, st.tabs(order)))
        return [t[l] for l in labels]


def open_cell(n):
    p = f"nb{n}_"
    with st.container(key=f"card_open{n}"):
        st.subheader(f"{n} · New cell", anchor=f"cell-{n}")
        t_data, t_op, t_out = st.tabs(["Data", "Operation", "Output"])
        df = types = None
        label, mode = "", "Upload new file"

        # ── Data tab: choose data + preview
        with t_data:
            names = list(ss.nb_datasets)
            if names:
                mode = st.radio("Data source", ["Upload new file", "Use existing dataset"], horizontal=True, key=p + "mode")
            if mode == "Upload new file":
                c1, c2 = st.columns([1.3, 1])
                up = c1.file_uploader("CSV or Excel file", type=["csv", "xlsx", "xls"], key=p + "file")
                if up:
                    data, sheet = up.getvalue(), None
                    if up.name.lower().endswith((".xlsx", ".xls")):
                        sheet = c2.selectbox("Sheet", excel_sheets(data), key=p + "sheet")
                    try:
                        df, types = load_bytes(up.name, data, sheet)
                        label = c2.text_input("Dataset name (reuse it later)", value=Path(up.name).stem,
                                              key=f"{p}name_{up.name}_{sheet}").strip() or Path(up.name).stem
                    except Exception as e:
                        st.error(f"Could not read the file: {e}")
            else:
                label = st.selectbox("Dataset", names, key=p + "ds")
                df, types = ss.nb_datasets[label]["df"], ss.nb_datasets[label]["types"]
            if df is not None:
                st.caption(f"**{label}** · {len(df):,} rows × {len(df.columns)} columns")
                show(numbered(df.head(100)), "table", height=DATA_H)
            elif mode == "Upload new file":
                st.caption("Upload a CSV or Excel file to start this cell.")

        if df is None:
            for t in (t_op, t_out):
                t.caption("Choose a data source in the Data tab first.")
            return

        # ── Operation tab
        out_df = fig = data = None
        desc, new_types = "", {}
        with t_op:
            op = st.radio("Operation", ["Select columns & rows", "Filter rows by condition", "Group by & summarize",
                                        "Create chart"], horizontal=True, key=p + "op")
            if op == "Select columns & rows":
                sel_cols = st.multiselect("Columns", list(df.columns), default=list(df.columns), key=p + "cols")
                d, rd = row_selector(df, p)
                if sel_cols:
                    out_df = d[sel_cols].reset_index(drop=True)
                    desc = f"Select {len(sel_cols)}/{len(df.columns)} columns" + (f", {rd}" if rd else "")
            elif op == "Filter rows by condition":
                mask, fd = filter_builder(df, types, p)
                out_df = df[mask].reset_index(drop=True)
                desc = "Filter: " + fd
            elif op == "Group by & summarize":
                d, fd = df, ""
                if st.checkbox("Filter rows first", key=p + "gfl"):
                    mask, fd = filter_builder(d, types, p)
                    d = d[mask]
                res, gdesc, new_types = group_builder(d, types, p)
                if res is not None:
                    out_df, desc = res, gdesc + (f" · where {fd}" if fd else "")
            else:
                with st.expander("Limit rows"):
                    d, rd = row_selector(df, p)
                fd, ctypes = "", types
                if st.checkbox("Filter data before charting", key=p + "usef"):
                    mask, fd = filter_builder(d, types, p)
                    d = d[mask]
                grouped = st.checkbox("Group data before charting", key=p + "usegr")
                if grouped:
                    d, gd, ctypes = group_builder(d, types, p)
                if d is None:
                    pass
                elif d.empty:
                    st.warning("No rows to chart.")
                else:
                    fig, desc = chart_ui(d, ctypes, p)
                    data = d.reset_index(drop=True)
                    desc += (" · grouped" if grouped else "") + (" · filtered" if fd else "") + (f" · {rd}" if rd else "")

        # ── Output tab
        save_as = ""
        with t_out:
            if out_df is None and fig is None:
                st.caption("Finish the Operation tab to see the output here.")
            if out_df is not None:
                st.caption(f"{len(out_df):,} rows × {len(out_df.columns)} columns")
                show(numbered(out_df.head(200)), "table", height=OUT_H)
                save_as = st.text_input("Save result as (reusable dataset)", value=f"{label}_{n}",
                                        key=f"{p}out_{op[:3]}_{label}")
            if fig is not None:
                plot(fig)

        # ── Run bar
        ready = out_df is not None or fig is not None
        b, m = st.columns([1, 3])
        run = b.button("▶ Run cell", type="primary", key=p + "run", disabled=not ready)
        m.caption(f"✓ {short(desc, 90)}" if ready else "Complete the Operation tab to enable Run.")
        if run:
            src_df = df
            if mode == "Upload new file":
                label = unique(label)
                ss.nb_datasets[label] = {"df": df, "types": types}
            out_name = None
            if out_df is not None:
                out_name = unique(save_as.strip() or f"{label}_{n}")
                ss.nb_datasets[out_name] = {"df": out_df,
                                            "types": {c: new_types.get(c) or types.get(c, "numeric") for c in out_df.columns}}
            ss.nb_cells.append(dict(n=n, src=label, op=op, desc=desc, df=out_df, fig=fig, data=data,
                                    out=out_name, src_df=src_df))
            ss.nb_n += 1
            st.rerun()


def done_cell(c):
    with st.container(key=f"card_done{c['n']}"):
        st.subheader(f"{c['n']} · {c['src']}", anchor=f"cell-{c['n']}")
        t_data, t_op, t_out = tabs_default(["Data", "Operation", "Output"], "Output")
        with t_data:
            s = c["src_df"]
            st.caption(f"**{c['src']}** · {len(s):,} rows × {len(s.columns)} columns")
            show(numbered(s.head(100)), "table", height=DATA_H)
        with t_op:
            st.caption("Operation")
            st.text(c["op"])
            st.caption("Details")
            st.text(c["desc"])
            if c["out"]:
                st.caption("Saved as dataset")
                st.text(c["out"])
            st.caption("This cell has been run. To change it, add a new cell that uses the saved dataset.")
        with t_out:
            if c["fig"] is not None:
                plot(c["fig"])
                with st.expander("Data used"):
                    show(numbered(c["data"].head(200)), "table", height=300)
            else:
                d = c["df"]
                st.caption(f"{len(d):,} rows × {len(d.columns)} columns · saved as **{c['out']}**")
                show(numbered(d.head(500)), "table", height=OUT_H)
                st.download_button("⬇ Download CSV", d.to_csv(index=False).encode(), file_name=f"{c['out']}.csv",
                                   mime="text/csv", key=f"nbdl{c['n']}")


def reset():
    for k in [k for k in ss if str(k).startswith("nb")]:
        del ss[k]


# ───────────────────────── Page ─────────────────────────
with st.sidebar:
    st.markdown("### 🧪 Custom Dashboard")
    st.markdown('<div class="side-h">Cells</div>', unsafe_allow_html=True)
    nav = "".join(
        f'<a class="nav-item" href="#cell-{c["n"]}" target="_self"><span class="nav-n">{c["n"]}</span>'
        f'<span class="nav-t"><b>{html.escape(short(c["src"], 28))}</b><small>{html.escape(short(c["desc"], 52))}</small></span></a>'
        for c in ss.nb_cells)
    nav += (f'<a class="nav-item open" href="#cell-{ss.nb_n}" target="_self"><span class="nav-n">{ss.nb_n}</span>'
            f'<span class="nav-t"><b>New cell</b><small>open · choose data &amp; operation</small></span></a>')
    st.markdown(nav, unsafe_allow_html=True)
    if ss.nb_datasets:
        st.markdown('<div class="side-h">Datasets</div>', unsafe_allow_html=True)
        st.markdown("".join(
            f'<div class="ds"><b>{html.escape(k)}</b> <small>{len(v["df"]):,} × {len(v["df"].columns)}</small></div>'
            for k, v in ss.nb_datasets.items()), unsafe_allow_html=True)
    st.markdown("&nbsp;", unsafe_allow_html=True)
    st.button("🗑 Reset notebook", on_click=reset, disabled=not ss.nb_cells)

st.markdown(
    '<div class="hero"><div class="eyebrow">Custom Dashboard</div><div class="title">Build it cell by cell</div>'
    '<div class="sub">Upload a file, then select, filter or chart it. Every result becomes a named dataset '
    'you can reuse in the next cell.</div></div>', unsafe_allow_html=True)

for cell in ss.nb_cells:
    done_cell(cell)
open_cell(ss.nb_n)
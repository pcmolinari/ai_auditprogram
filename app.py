"""Audit Program Builder - run with:  streamlit run app.py"""
import io
import pandas as pd
import streamlit as st

from engine import (ACCOUNTS, guess_columns, load_grc, build_program, allocate, tasks_to_df)
from pdf_report import build_pdf

st.set_page_config(page_title="Audit Program Builder", layout="wide")
st.title("Audit Program Builder")
st.caption("Inventory - Accounts Receivable - Accounts Payable | risk-based, GRC-driven, resource-constrained")

# ------------------------------------------------------------------ Sidebar: rules
with st.sidebar:
    st.header("Rules")
    medium = st.number_input("Medium investigation above", value=10_000_000.0, step=1_000_000.0, format="%.0f")
    deep = st.number_input("Deep investigation above", value=50_000_000.0, step=5_000_000.0, format="%.0f")
    cap = st.number_input("Max hours per person", value=80.0, step=4.0)
    rely = st.checkbox("Rely on passed GRC controls for small, lower-importance risks", value=True)
    st.info("Any GRC control not passed forces a Deep test regardless of balance.")

# ------------------------------------------------------------------ Step 1: balances
st.subheader("1. Balance sheet amounts")
c1, c2, c3 = st.columns(3)
inv = c1.number_input("Total inventory", min_value=0.0, step=100_000.0, format="%.0f")
ar = c2.number_input("Accounts receivable", min_value=0.0, step=100_000.0, format="%.0f")
ap = c3.number_input("Accounts payable", min_value=0.0, step=100_000.0, format="%.0f")
balances = {"Inventory": inv, "Accounts Receivable": ar, "Accounts Payable": ap}

# ------------------------------------------------------------------ Step 2: GRC upload
st.subheader("2. GRC control assessment (spreadsheet)")
up = st.file_uploader("Upload the GRC control situation (.xlsx / .xls / .csv)", type=["xlsx", "xls", "csv"])
grc = None
if up is not None:
    try:
        if up.name.lower().endswith(".csv"):
            raw = pd.read_csv(up)
        else:
            xl = pd.ExcelFile(up)
            sheet = st.selectbox("Sheet", xl.sheet_names) if len(xl.sheet_names) > 1 else xl.sheet_names[0]
            raw = xl.parse(sheet)
        raw = raw.dropna(how="all")
        guess = guess_columns(raw)
        cols = list(raw.columns)
        st.caption("Confirm the column mapping:")
        m1, m2, m3, m4 = st.columns(4)
        id_col = m1.selectbox("Control ID", cols, index=cols.index(guess["id"]))
        name_col = m2.selectbox("Control name / description", cols, index=cols.index(guess["name"]))
        status_opts = ["(none)"] + cols
        status_col = m3.selectbox("Assessment result", status_opts,
                                  index=status_opts.index(guess["status"]) if guess["status"] in cols else 0)
        area_col = m4.selectbox("Area / process (optional)", ["(none)"] + cols)
        grc = load_grc(raw, id_col, name_col, None if status_col == "(none)" else status_col,
                       None if area_col == "(none)" else area_col)
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Controls loaded", len(grc))
        k2.metric("Passed", int((grc.Status == "Passed").sum()))
        k3.metric("Failed", int((grc.Status == "Failed").sum()))
        k4.metric("Unknown", int((grc.Status == "Unknown").sum()))
        with st.expander("Preview interpreted GRC data"):
            st.dataframe(grc.drop(columns="_text"), use_container_width=True)
    except Exception as e:
        st.error(f"Could not read the file: {e}")

# ------------------------------------------------------------------ Step 3: resources
st.subheader("3. Resources")
n_people = st.number_input("How many people are available?", min_value=1, max_value=50, value=2, step=1)
names_raw = st.text_input("Names (optional, comma separated)", placeholder="Ana, Ben, Carla")
names = [n.strip() for n in names_raw.split(",") if n.strip()]
people = [names[i] if i < len(names) else f"Auditor {i + 1}" for i in range(int(n_people))]

# ------------------------------------------------------------------ Generate
if st.button("Generate audit program", type="primary"):
    if sum(balances.values()) == 0:
        st.warning("Enter at least one balance.")
    else:
        tasks, scoped_out = build_program(balances, grc, medium, deep, rely)
        assigned, not_covered, load = allocate(tasks, people, cap)
        st.session_state["result"] = dict(
            tasks=tasks, scoped_out=scoped_out, assigned=assigned, not_covered=not_covered, load=load,
            balances=balances, medium=medium, deep=deep, cap=cap, people=people, grc=grc, rely=rely)

res = st.session_state.get("result")
if res:
    st.divider()
    st.subheader("Audit program")
    total_hours = sum(t.hours for t in res["assigned"])
    a, b, c, d = st.columns(4)
    a.metric("Tests assigned", len(res["assigned"]))
    b.metric("Hours planned", f"{total_hours:.0f}")
    c.metric("Capacity", f"{len(res['people']) * res['cap']:.0f}")
    d.metric("Not covered (capacity)", len(res["not_covered"]))

    if res["not_covered"]:
        need = sum(t.hours for t in res["not_covered"])
        st.warning(f"{len(res['not_covered'])} lower-priority tests ({need:.0f} h) do not fit in the "
                   f"{res['cap']:.0f} h/person limit. Add about {need / res['cap']:.1f} more people or accept the residual risk.")

    st.markdown("**Balance-rule risk by account**")
    st.dataframe(pd.DataFrame([{
        "Account": k, "Balance": f"{v:,.0f}",
        "Depth": "Deep" if v > res["deep"] else "Medium" if v > res["medium"] else "Standard"}
        for k, v in res["balances"].items()]), hide_index=True)

    st.markdown("**Hours per person**")
    st.dataframe(pd.DataFrame([{"Person": p, "Hours": res["load"][p], "Capacity": res["cap"],
                                "Utilisation %": round(res["load"][p] / res["cap"] * 100)} for p in res["people"]]),
                 hide_index=True)

    df = tasks_to_df(res["assigned"])
    st.markdown("**Program (risk, control, test, person, hours, why)**")
    st.dataframe(df, use_container_width=True, hide_index=True)

    if res["not_covered"]:
        with st.expander("Tests not allocated"):
            st.dataframe(tasks_to_df(res["not_covered"]).drop(columns="Person"), hide_index=True)
    if res["scoped_out"]:
        with st.expander("Risks relied upon via GRC (no test)"):
            st.dataframe(pd.DataFrame(res["scoped_out"]), hide_index=True)

    col_a, col_b = st.columns(2)
    pdf = build_pdf(res["balances"], res["medium"], res["deep"], res["cap"], res["people"], res["load"],
                    res["assigned"], res["not_covered"], res["scoped_out"], res["grc"], res["rely"])
    col_a.download_button("Download PDF (rules + results + rationale)", pdf, "audit_program.pdf", "application/pdf")
    xbuf = io.BytesIO()
    df.to_excel(xbuf, index=False)
    col_b.download_button("Download Excel", xbuf.getvalue(), "audit_program.xlsx")

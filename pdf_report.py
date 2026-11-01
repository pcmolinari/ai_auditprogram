"""PDF export of the audit program (rules + results + rationale)."""
from __future__ import annotations

import io
from datetime import date
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

NAVY = colors.HexColor("#1F3864")
LIGHT = colors.HexColor("#EEF2F8")
DEPTH_COLOR = {"Deep": colors.HexColor("#F8D7DA"), "Medium": colors.HexColor("#FFF3CD"),
               "Standard": colors.HexColor("#D9EAD3")}


def _styles():
    ss = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=ss["Title"], textColor=NAVY, fontSize=20),
        "h1": ParagraphStyle("h1", parent=ss["Heading1"], textColor=NAVY, fontSize=14, spaceBefore=10),
        "body": ParagraphStyle("b", parent=ss["Normal"], fontSize=9, leading=12),
        "cell": ParagraphStyle("c", parent=ss["Normal"], fontSize=7.5, leading=9.5),
        "head": ParagraphStyle("h", parent=ss["Normal"], fontSize=8, leading=10, textColor=colors.white,
                               fontName="Helvetica-Bold"),
    }


def _p(text, style):
    return Paragraph(escape(str(text)), style)


def _table(data, widths, st, depth_col=None, rows_depth=None):
    t = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#B7C0CC")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    if depth_col is not None and rows_depth:
        for i, d in enumerate(rows_depth, start=1):
            style.append(("BACKGROUND", (depth_col, i), (depth_col, i), DEPTH_COLOR.get(d, colors.white)))
    t.setStyle(TableStyle(style))
    return t


def build_pdf(balances, medium, deep, cap, people, load, assigned, not_covered, scoped_out,
              grc_df=None, rely_on_passed=True) -> bytes:
    st = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm, title="Audit Program")
    W = landscape(A4)[0] - 24 * mm
    s = []
    total = sum(balances.values()) or 1

    s += [Paragraph("Audit Program - Inventory, Accounts Receivable, Accounts Payable", st["title"]),
          Paragraph(f"Generated {date.today():%d %B %Y}", st["body"]), Spacer(1, 6)]

    # ---- Rules
    s.append(Paragraph("1. Rules applied", st["h1"]))
    rules = [
        f"Balance rule (per account): balance above {medium:,.0f} = Medium investigation; above {deep:,.0f} = Deep investigation; otherwise Standard.",
        "GRC rule: any control NOT PASSED in the GRC assessment forces a Deep test, regardless of the balance. "
        "Controls with no result are not relied upon. Risks with no matching GRC control are treated as coverage gaps.",
        "Prioritisation: risk importance (1-5) x 10 + GRC failure/gap bonus + depth weight + share of balance sheet. Highest score is allocated first.",
        f"Resourcing: {len(people)} people, maximum {cap:.0f} hours each ({len(people) * cap:,.0f} hours available).",
    ]
    if rely_on_passed:
        rules.append("Scope-out: Standard-balance risks with a passed GRC control and importance below 4 rely on GRC (no extra testing).")
    for r in rules:
        s.append(Paragraph("&bull; " + escape(r), st["body"]))

    # ---- Inputs
    s.append(Paragraph("2. Inputs and risk rating by account", st["h1"]))
    rows = [[_p(h, st["head"]) for h in ["Account", "Balance", "% of total", "Balance-rule depth", "GRC controls (Pass / Fail / Unknown)"]]]
    depths = []
    for a, v in balances.items():
        d = "Deep" if v > deep else "Medium" if v > medium else "Standard"
        depths.append(d)
        if grc_df is not None and len(grc_df):
            sub = grc_df[grc_df["Account"] == a]
            g = f"{(sub.Status == 'Passed').sum()} / {(sub.Status == 'Failed').sum()} / {(sub.Status == 'Unknown').sum()}"
        else:
            g = "n/a"
        rows.append([_p(a, st["cell"]), _p(f"{v:,.0f}", st["cell"]), _p(f"{v / total * 100:.1f}%", st["cell"]),
                     _p(d, st["cell"]), _p(g, st["cell"])])
    s.append(_table(rows, [W * .22, W * .16, W * .12, W * .18, W * .32], st, depth_col=3, rows_depth=depths))

    # ---- Resources
    s.append(Paragraph("3. Resource allocation", st["h1"]))
    rows = [[_p(h, st["head"]) for h in ["Person", "Tasks", "Hours", "Capacity", "Utilisation"]]]
    for p in people:
        n = sum(1 for t in assigned if t.person == p)
        rows.append([_p(p, st["cell"]), _p(n, st["cell"]), _p(f"{load[p]:.0f}", st["cell"]),
                     _p(f"{cap:.0f}", st["cell"]), _p(f"{load[p] / cap * 100:.0f}%", st["cell"])])
    s.append(_table(rows, [W * .3, W * .15, W * .15, W * .15, W * .15], st))
    if not_covered:
        extra = sum(t.hours for t in not_covered)
        s.append(Spacer(1, 4))
        s.append(Paragraph(f"<b>WARNING:</b> {len(not_covered)} lower-priority tests ({extra:.0f} hours) could not be "
                           f"allocated within the {cap:.0f}-hour limit. See section 6.", st["body"]))

    # ---- Program
    s.append(PageBreak())
    s.append(Paragraph("4. Audit program (ordered by priority)", st["h1"]))
    rows = [[_p(h, st["head"]) for h in ["Ref", "Account", "Risk", "Control expected", "Test to perform", "Depth", "Person", "Hrs"]]]
    for t in assigned:
        rows.append([_p(t.ref, st["cell"]), _p(t.account, st["cell"]), _p(t.risk, st["cell"]),
                     _p(t.control, st["cell"]), _p(t.test, st["cell"]), _p(t.depth, st["cell"]),
                     _p(t.person, st["cell"]), _p(f"{t.hours:.0f}", st["cell"])])
    s.append(_table(rows, [W * .06, W * .09, W * .2, W * .2, W * .27, W * .06, W * .08, W * .04], st,
                    depth_col=5, rows_depth=[t.depth for t in assigned]))

    # ---- Rationale
    s.append(PageBreak())
    s.append(Paragraph("5. Why each control / test was selected", st["h1"]))
    rows = [[_p(h, st["head"]) for h in ["Ref", "Depth", "Priority", "GRC controls linked", "Rationale"]]]
    for t in assigned:
        rows.append([_p(t.ref, st["cell"]), _p(t.depth, st["cell"]), _p(t.priority, st["cell"]),
                     _p(", ".join(t.grc_links) or "none", st["cell"]), _p(" ".join(t.reasons), st["cell"])])
    s.append(_table(rows, [W * .06, W * .07, W * .07, W * .15, W * .65], st,
                    depth_col=1, rows_depth=[t.depth for t in assigned]))

    # ---- Not covered / scoped out
    s.append(Paragraph("6. Tests not allocated (capacity) and risks relied upon", st["h1"]))
    if not_covered:
        rows = [[_p(h, st["head"]) for h in ["Ref", "Account", "Risk", "Depth", "Hrs needed", "Priority"]]]
        for t in not_covered:
            rows.append([_p(t.ref, st["cell"]), _p(t.account, st["cell"]), _p(t.risk, st["cell"]),
                         _p(t.depth, st["cell"]), _p(f"{t.hours:.0f}", st["cell"]), _p(t.priority, st["cell"])])
        s.append(Paragraph("Not allocated - add resources or accept residual risk:", st["body"]))
        s.append(_table(rows, [W * .08, W * .14, W * .42, W * .1, W * .1, W * .1], st))
    else:
        s.append(Paragraph("All selected tests were allocated within capacity.", st["body"]))
    s.append(Spacer(1, 6))
    if scoped_out:
        rows = [[_p(h, st["head"]) for h in ["Ref", "Account", "Risk", "Why no test"]]]
        for r in scoped_out:
            rows.append([_p(r["Ref"], st["cell"]), _p(r["Account"], st["cell"]), _p(r["Risk"], st["cell"]),
                         _p(r["Why"], st["cell"])])
        s.append(Paragraph("Scoped out (reliance on GRC):", st["body"]))
        s.append(_table(rows, [W * .08, W * .14, W * .35, W * .43], st))

    doc.build(s)
    return buf.getvalue()

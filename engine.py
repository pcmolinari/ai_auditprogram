"""Audit program engine: rules, test library, GRC matching, prioritisation and resource allocation."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
import pandas as pd

ACCOUNTS = ["Inventory", "Accounts Receivable", "Accounts Payable"]

# Keywords used to decide which balance-sheet area a GRC control belongs to
ACCOUNT_KEYWORDS = {
    "Inventory": ["inventor", "stock", "warehouse", "obsole", "physical count", "cycle count", "consign"],
    "Accounts Receivable": ["receivable", "revenue", "sales", "customer", "billing", "invoice", "collection",
                            "credit note", "credit loss", "order to cash", "o2c", "otc", "cash application"],
    "Accounts Payable": ["payable", "purchas", "procure", "vendor", "supplier", "disbursement", "p2p",
                         "procure to pay", "grni", "three-way", "3-way", "payment run"],
}

FAIL_WORDS = ["fail", "not pass", "ineffective", "not effective", "deficien", "non-compliant", "non compliant",
              "gap", "exception", "weak", "not operating", "not designed"]
PASS_WORDS = ["pass", "effective", "compliant", "satisfactory", "adequate", "operating"]

DEPTH_RANK = {"Standard": 0, "Medium": 1, "Deep": 2}


@dataclass
class LibItem:
    ref: str
    account: str
    risk: str
    control: str
    test: dict          # depth -> test description
    importance: int     # 1 (low) .. 5 (critical)
    hours: tuple        # (standard, medium, deep)
    keywords: list


def _t(std, med, deep):
    return {"Standard": std, "Medium": med, "Deep": deep}


LIBRARY: list[LibItem] = [
    # ---------------- INVENTORY ----------------
    LibItem("INV-01", "Inventory", "Inventory recorded does not exist or is not held (existence)",
            "Periodic physical count / cycle counts reconciled to perpetual records with approved adjustments",
            _t("Review count procedures and reconciliation; agree 10 items floor-to-book",
               "Observe count; test-count 25 items both directions; agree count sheets to final listing",
               "Attend full count, 60+ items both directions, roll-forward/back to balance sheet date, investigate all variances"),
            5, (6, 14, 28), ["count", "physical", "stocktake", "cycle", "existence"]),
    LibItem("INV-02", "Inventory", "Inventory valued at incorrect cost (valuation)",
            "Standard cost / weighted average cost reviewed and approved; purchase price variances analysed",
            _t("Recompute cost on 10 items to supplier invoices",
               "Recompute cost on 25 items incl. labour/overhead absorption; analyse PPV",
               "Full cost build-up test on 50+ items, overhead rate recalculation, analytical review of margins by product"),
            5, (5, 12, 24), ["cost", "valuation", "costing", "standard cost", "ppv", "variance"]),
    LibItem("INV-03", "Inventory", "Obsolete / slow-moving stock not provided for (NRV)",
            "Periodic slow-moving & obsolescence review with provision policy approved by management",
            _t("Review provision policy and last review evidence",
               "Run ageing report; recompute provision; compare to post year-end sales for 15 items",
               "Full ageing and NRV test on all lines over threshold; subsequent sales / price testing; challenge management assumptions"),
            4, (4, 10, 20), ["obsole", "slow", "provision", "nrv", "reserve", "write-down", "write down"]),
    LibItem("INV-04", "Inventory", "Receipts and shipments recorded in wrong period (cut-off)",
            "Goods received / dispatched cut-off procedures; GRN and delivery notes sequentially controlled",
            _t("Review cut-off procedures; test 5 receipts/shipments either side of year-end",
               "Test 15 receipts and 15 shipments either side of period end",
               "Test 30+ movements either side of year-end, including in-transit and returns; reconcile GRN sequence"),
            4, (3, 8, 16), ["cutoff", "cut-off", "cut off", "goods receipt", "grn", "dispatch"]),
    LibItem("INV-05", "Inventory", "Theft, misuse or unauthorised movement of inventory (safeguarding)",
            "Restricted warehouse access, segregation of duties between custody and recording, authorised adjustments",
            _t("Walkthrough of warehouse access and adjustment approvals",
               "Test access list to roles; sample 20 stock adjustments for approval",
               "Test access rights fully; analyse all material adjustments/write-offs for unusual patterns; test SoD in the WMS/ERP"),
            3, (3, 8, 16), ["access", "warehouse", "segregation", "sod", "security", "adjustment", "safeguard"]),
    LibItem("INV-06", "Inventory", "Stock held at third parties, consigned or in transit misstated (rights & ownership)",
            "Third-party / consignment stock confirmed and reconciled; ownership terms reviewed",
            _t("Inquire and review list of third-party stock",
               "Confirm balances with third parties for largest locations",
               "Confirm all third-party stock, review contracts and incoterms, test in-transit items to supplier documents"),
            3, (2, 6, 14), ["consign", "transit", "ownership", "third party", "third-party", "incoterm"]),

    # ---------------- ACCOUNTS RECEIVABLE ----------------
    LibItem("AR-01", "Accounts Receivable", "Fictitious or overstated receivables / revenue (existence & occurrence)",
            "Invoices matched to sales order, proof of delivery and contract before posting",
            _t("Test 10 invoices to order, delivery and cash receipt",
               "Send confirmations for largest customers; test 25 invoices to POD and contract",
               "Confirm 70%+ of balance, alternative procedures for non-replies, test 50+ invoices end-to-end, revenue recognition review"),
            5, (6, 14, 28), ["billing", "invoice", "delivery", "revenue", "occurrence", "existence", "order to cash", "o2c", "confirmation"]),
    LibItem("AR-02", "Accounts Receivable", "Uncollectible receivables not adequately provided for (valuation)",
            "Expected credit loss / allowance methodology reviewed monthly; overdue follow-up",
            _t("Review allowance policy and recompute on ageing",
               "Test ageing accuracy on 20 items; recompute ECL; review subsequent receipts of top 15 overdue",
               "Full ageing re-performance, challenge ECL model inputs, subsequent cash for all overdue, customer-level credit-worthiness review"),
            5, (5, 12, 24), ["allowance", "credit loss", "ecl", "bad debt", "doubtful", "ageing", "aging", "collection", "provision"]),
    LibItem("AR-03", "Accounts Receivable", "Sales recorded in wrong period (cut-off)",
            "Revenue cut-off controls; shipping documents and invoice dates reconciled at period end",
            _t("Test 5 sales either side of period end",
               "Test 15 sales and 10 credit notes either side of period end",
               "Test 30+ sales and all large credit notes around period end; review post year-end returns"),
            4, (3, 8, 16), ["cutoff", "cut-off", "cut off", "period end", "revenue recognition"]),
    LibItem("AR-04", "Accounts Receivable", "Sales to customers beyond credit capacity or unauthorised customers (credit risk)",
            "Customer master data approval; credit limits approved and system-enforced",
            _t("Walkthrough of credit-limit process",
               "Test 15 new customers and 15 limit changes for approval; test system block",
               "Test all limit overrides, analyse customers exceeding limits, review master-data change logs"),
            3, (3, 8, 16), ["credit limit", "customer master", "credit", "master data", "onboarding"]),
    LibItem("AR-05", "Accounts Receivable", "Cash receipts misapplied or unapplied cash hides errors/fraud (lapping)",
            "Daily cash application; bank-to-ledger reconciliation reviewed independently",
            _t("Review cash application reconciliation for 2 periods",
               "Test 20 receipts bank-to-ledger-to-customer; review unapplied cash",
               "Lapping analysis, test all unapplied items over threshold, full bank-to-subledger reconciliation re-performance"),
            3, (3, 8, 16), ["cash application", "receipts", "unapplied", "lapping", "bank reconciliation"]),
    LibItem("AR-06", "Accounts Receivable", "Unauthorised credit notes, write-offs or manual adjustments",
            "Credit notes and write-offs approved above delegated authority limits",
            _t("Sample 10 credit notes/write-offs for approval",
               "Sample 25 and review reasons; test authority matrix",
               "Test all credit notes/write-offs above threshold; analyse by user, timing and customer for anomalies"),
            4, (3, 8, 16), ["credit note", "write-off", "write off", "adjustment", "approval", "authority"]),
    LibItem("AR-07", "Accounts Receivable", "Subledger does not agree to general ledger (accuracy / completeness)",
            "Monthly AR subledger to GL reconciliation, reviewed and signed off",
            _t("Review last reconciliation and re-add subledger listing",
               "Re-perform reconciliation at period end; test reconciling items",
               "Re-perform 3 months of reconciliations; trace all reconciling items; test manual journals to AR control account"),
            4, (2, 6, 12), ["reconciliation", "subledger", "sub-ledger", "general ledger", "gl", "journal"]),

    # ---------------- ACCOUNTS PAYABLE ----------------
    LibItem("AP-01", "Accounts Payable", "Liabilities understated / unrecorded (completeness)",
            "Goods-received-not-invoiced accrual and period-end liability review",
            _t("Review GRNI accrual and search 5 post year-end payments",
               "Search for unrecorded liabilities: post year-end payments and invoices (20 items)",
               "Full unrecorded-liability search to a later date, supplier statement reconciliations for top vendors, accrual recompute"),
            5, (5, 12, 24), ["accrual", "grni", "unrecorded", "completeness", "liabilit", "supplier statement"]),
    LibItem("AP-02", "Accounts Payable", "Invalid, duplicate or inflated invoices paid (accuracy & occurrence)",
            "Three-way match (PO, goods receipt, invoice) and duplicate-invoice check in ERP",
            _t("Test 10 invoices for three-way match",
               "Test 25 invoices for match and approval; run duplicate check",
               "Test 50+ invoices; full-population duplicate analytics (vendor/amount/date/invoice no.); review tolerance overrides"),
            5, (5, 12, 24), ["three-way", "3-way", "three way", "match", "duplicate", "purchase order", "po ", "invoice"]),
    LibItem("AP-03", "Accounts Payable", "Fictitious vendors or fraudulent bank-detail changes",
            "Vendor master data creation/changes independently approved and call-back verified",
            _t("Test 10 vendor creations/changes for approval",
               "Test 25 changes; compare vendor bank accounts to employee data",
               "Full-population vendor analytics (shared bank/address, dormant vendors); test all bank-detail changes with call-back evidence"),
            5, (4, 10, 20), ["vendor master", "supplier master", "bank detail", "bank account", "master data", "vendor", "supplier"]),
    LibItem("AP-04", "Accounts Payable", "Purchases recorded in wrong period (cut-off)",
            "Receiving and invoice cut-off procedures at period end",
            _t("Test 5 receipts and invoices either side of period end",
               "Test 15 receipts and invoices either side of period end",
               "Test 30+ items either side of period end incl. services and capital items; review credit notes after year-end"),
            4, (3, 8, 16), ["cutoff", "cut-off", "cut off", "period end"]),
    LibItem("AP-05", "Accounts Payable", "Unauthorised or segregation-breaching payments",
            "Payment runs approved by two authorised signatories; SoD between vendor set-up, invoice entry and payment",
            _t("Walkthrough of payment run approval; test 5 runs",
               "Test 10 payment runs and 20 manual payments; review SoD ruleset",
               "Test all manual/urgent payments above threshold; full SoD conflict analysis in ERP/bank portal"),
            4, (3, 8, 18), ["payment", "approval", "segregation", "sod", "disbursement", "authoris", "authoriz", "signator"]),
    LibItem("AP-06", "Accounts Payable", "Subledger does not agree to GL; debit balances misclassified",
            "Monthly AP subledger-to-GL reconciliation; review of debit balances and aged items",
            _t("Review last reconciliation; re-add listing",
               "Re-perform period-end reconciliation; test reconciling items and debit balances",
               "Re-perform 3 months; trace all reconciling items; test manual journals and reclassifications"),
            3, (2, 6, 12), ["reconciliation", "subledger", "sub-ledger", "general ledger", "gl", "journal"]),
]


# ---------------------------------------------------------------- GRC parsing
def detect_status(text: str) -> str:
    t = str(text).lower().strip()
    if not t or t in ("nan", "none"):
        return "Unknown"
    if any(w in t for w in FAIL_WORDS) or t in ("no", "n", "red", "0", "fail", "failed"):
        return "Failed"
    if any(w in t for w in PASS_WORDS) or t in ("yes", "y", "green", "1", "ok"):
        return "Passed"
    return "Unknown"


def detect_account(text: str) -> str | None:
    t = text.lower()
    scores = {a: sum(k in t for k in kws) for a, kws in ACCOUNT_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else None


def guess_columns(df: pd.DataFrame) -> dict:
    cols = {c: str(c).lower() for c in df.columns}

    def pick(*needles, exclude=()):
        for needle in needles:
            for c, lc in cols.items():
                if needle in lc and not any(x in lc for x in exclude):
                    return c
        return None

    return {
        "id": pick("control id", "ctrl id", "id", "ref", "code") or df.columns[0],
        "name": pick("control name", "control description", "description", "title", "control") or df.columns[min(1, len(df.columns) - 1)],
        "status": pick("status", "result", "assessment", "outcome", "effective", "test"),
    }


def load_grc(df: pd.DataFrame, id_col, name_col, status_col, area_col=None) -> pd.DataFrame:
    rows = []
    for _, r in df.iterrows():
        cid = str(r[id_col]).strip()
        if not cid or cid.lower() == "nan":
            continue
        row_text = " ".join(str(v) for v in r.values if str(v).lower() != "nan")
        acct = detect_account(str(r[area_col]) + " " + row_text if area_col else row_text)
        rows.append({
            "Control ID": cid,
            "Control": str(r[name_col]).strip(),
            "Status": detect_status(r[status_col]) if status_col else "Unknown",
            "Account": acct or "",
            "_text": row_text.lower(),
        })
    return pd.DataFrame(rows, columns=["Control ID", "Control", "Status", "Account", "_text"])


# ---------------------------------------------------------------- Rules
def balance_depth(amount: float, medium: float, deep: float) -> str:
    if amount > deep:
        return "Deep"
    if amount > medium:
        return "Medium"
    return "Standard"


@dataclass
class Task:
    ref: str
    account: str
    risk: str
    control: str
    test: str
    depth: str
    hours: float
    importance: int
    priority: float
    reasons: list
    grc_links: list = field(default_factory=list)
    person: str = ""


def build_program(balances: dict, grc: pd.DataFrame | None, medium: float, deep: float,
                  rely_on_passed: bool = True):
    total = sum(balances.values()) or 1
    tasks: list[Task] = []
    scoped_out: list[dict] = []
    matched_control_ids = set()

    for item in LIBRARY:
        amount = balances[item.account]
        b_depth = balance_depth(amount, medium, deep)
        share = amount / total * 100
        reasons = [f"{item.account} balance {amount:,.0f} ({share:.0f}% of the three accounts) "
                   f"=> {b_depth} by balance rule (>{medium:,.0f} Medium, >{deep:,.0f} Deep)."]
        reasons.append(f"Risk importance {item.importance}/5 (library rating).")

        linked = []
        if grc is not None and len(grc):
            for _, g in grc.iterrows():
                if g["Account"] not in (item.account, ""):
                    continue
                if any(k in g["_text"] for k in item.keywords):
                    linked.append(g)
                    matched_control_ids.add(g["Control ID"])

        failed = [g for g in linked if g["Status"] == "Failed"]
        passed = [g for g in linked if g["Status"] == "Passed"]
        unknown = [g for g in linked if g["Status"] == "Unknown"]
        depth = b_depth
        fail_bonus = 0

        if failed:
            depth = "Deep"
            fail_bonus = 25
            reasons.append("GRC assessment NOT PASSED for " + ", ".join(g["Control ID"] for g in failed)
                           + " => Deep test regardless of balance.")
        if unknown:
            reasons.append("GRC result missing/unclear for " + ", ".join(g["Control ID"] for g in unknown)
                           + " => no reliance placed on control.")
            fail_bonus = max(fail_bonus, 5)
        if passed and not failed:
            reasons.append("GRC assessment PASSED for " + ", ".join(g["Control ID"] for g in passed) + ".")
        if grc is not None and len(grc) and not linked:
            reasons.append("No matching control found in the GRC file => coverage gap, control assumed absent.")
            fail_bonus = max(fail_bonus, 10)

        # Scope-out rule: small balance, control passed in GRC, lower importance risk
        relied = bool(passed) and not failed and not unknown
        if rely_on_passed and relied and b_depth == "Standard" and item.importance < 4:
            scoped_out.append({"Ref": item.ref, "Account": item.account, "Risk": item.risk,
                               "Why": "Balance below Medium threshold, GRC control passed and risk importance < 4: "
                                      "reliance on GRC result, no additional testing."})
            continue

        hours = item.hours[DEPTH_RANK[depth]]
        priority = (item.importance * 10 + fail_bonus
                    + {"Standard": 0, "Medium": 6, "Deep": 12}[depth] + share * 0.2)
        tasks.append(Task(item.ref, item.account, item.risk, item.control, item.test[depth], depth,
                          hours, item.importance, round(priority, 1), reasons,
                          [g["Control ID"] for g in linked]))

    # Failed GRC controls that did not map to any library test -> dedicated deep task
    if grc is not None and len(grc):
        for _, g in grc.iterrows():
            if g["Status"] == "Failed" and g["Control ID"] not in matched_control_ids:
                acct = g["Account"] or max(balances, key=balances.get)
                share = balances[acct] / total * 100
                tasks.append(Task(
                    f"GRC-{g['Control ID']}", acct,
                    f"Control failure not covered by standard risks: {g['Control']}",
                    g["Control"],
                    "Deep: understand failure root cause, re-perform control over the period, extend substantive "
                    "sample to 50+ items, quantify potential misstatement and report deficiency.",
                    "Deep", 16, 4, round(40 + 25 + 12 + share * 0.2, 1),
                    [f"GRC assessment NOT PASSED for {g['Control ID']} and no standard test covers it => Deep test.",
                     f"Assigned to {acct} (largest related balance / detected area)."],
                    [g["Control ID"]]))

    tasks.sort(key=lambda t: -t.priority)
    return tasks, scoped_out


# ---------------------------------------------------------------- Allocation
def allocate(tasks: list[Task], people: list[str], cap: float = 80.0):
    load = {p: 0.0 for p in people}
    acct_owner: dict[str, str] = {}
    not_covered = []
    for t in tasks:
        fits = [p for p in people if load[p] + t.hours <= cap]
        if not fits:
            not_covered.append(t)
            continue
        # prefer the person already working that account if they are not overloaded vs the least loaded
        least = min(fits, key=lambda p: load[p])
        owner = acct_owner.get(t.account)
        pick = owner if owner in fits and load[owner] <= load[least] + 8 else least
        acct_owner.setdefault(t.account, pick)
        t.person = pick
        load[pick] += t.hours
    assigned = [t for t in tasks if t.person]
    return assigned, not_covered, load


def tasks_to_df(tasks: list[Task]) -> pd.DataFrame:
    return pd.DataFrame([{
        "Ref": t.ref, "Account": t.account, "Risk": t.risk, "Control expected": t.control,
        "Test": t.test, "Depth": t.depth, "Person": t.person, "Hours": t.hours,
        "Priority": t.priority, "Why selected": " ".join(t.reasons),
    } for t in tasks])

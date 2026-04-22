import frappe
import requests
import json

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.1:8b"

ROUTABLE_DOCTYPES = [
    "Sales Invoice",
    "Sales Invoice Item",
    "Purchase Invoice",
    "Purchase Invoice Item",
    "Customer",
    "Supplier",
    "Item",
    "Stock Entry",
    "Payment Entry",
    "Journal Entry",
    "Opportunity",
    "Lead",
    "Sales Team",
]

SCHEMA_FIELDTYPES = {"Data", "Currency", "Date", "Datetime", "Float", "Int", "Link", "Select"}


def _get_default_currency() -> str:
    try:
        currency = frappe.defaults.get_global_default("currency")
        if not currency:
            currency = frappe.db.get_value("Company", {"is_group": 0}, "default_currency")
        return currency or "USD"
    except Exception:
        return "USD"


@frappe.whitelist()
def explain_logikmind(question: str, data: str) -> dict:
    if not data:
        return {"explanation": ""}
    try:
        rows = json.loads(data) if isinstance(data, str) else data
    except Exception:
        return {"explanation": ""}

    sample = rows[:10]
    prompt = f"""You are a business analyst. A user asked: "{question}"

The data returned (up to 10 rows):
{json.dumps(sample, indent=2, default=str)}

Write 1-2 sentences of plain-English insight about this data. Focus on what is notable, surprising, or actionable.
Only explain if the data warrants it — if it is straightforward, say nothing (return empty string).
Respond ONLY with valid JSON in this exact format:
{{"explanation": "<your insight or empty string>"}}"""

    try:
        result = call_ollama(prompt)
        return {"explanation": result.get("explanation", "")}
    except Exception:
        return {"explanation": ""}


def call_ollama(prompt: str) -> dict:
    print(f"\n[logikbrain] >>> calling ollama, prompt length={len(prompt)}")
    print(f"[logikbrain] prompt:\n{prompt}\n")

    try:
        response = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "format": "json"},
            timeout=300,
        )
        response.raise_for_status()
    except requests.exceptions.ReadTimeout:
        print("[logikbrain] ERROR: Ollama timed out")
        raise frappe.ValidationError("Ollama took too long to respond. Please try again.")
    except requests.exceptions.ConnectionError:
        print("[logikbrain] ERROR: could not connect to Ollama")
        raise frappe.ValidationError("Ollama is not running. Please start the Ollama service.")

    full_body = response.json()
    raw = full_body.get("response", "")
    duration_s = full_body.get("total_duration", 0) / 1e9

    print(f"[logikbrain] <<< ollama responded in {duration_s:.1f}s")
    print(f"[logikbrain] raw response text:\n{raw}\n")

    try:
        parsed = json.loads(raw)
        print(f"[logikbrain] parsed JSON:\n{json.dumps(parsed, indent=2)}\n")
        return parsed
    except (json.JSONDecodeError, TypeError):
        print(f"[logikbrain] ERROR: could not parse JSON from response: {raw}")
        frappe.log_error(title="Logikbrain: Ollama JSON parse failure", message=raw)
        raise frappe.ValidationError(
            "AI response could not be parsed. Please try rephrasing your question."
        )


def get_doctype_schema(doctypes: list) -> str:
    lines = []
    for doctype in doctypes:
        try:
            meta = frappe.get_meta(doctype)
        except Exception:
            continue

        field_parts = []
        for f in meta.fields:
            if f.fieldtype in SCHEMA_FIELDTYPES and f.fieldname and not f.fieldname.startswith("custom_"):
                field_parts.append(f"{f.fieldname} ({f.fieldtype})")

        if field_parts:
            lines.append(f"{doctype}: {', '.join(field_parts)}")

    return "\n".join(lines)


def _get_revenue_mom_comparison() -> dict:
    from frappe.utils import get_first_day, get_last_day, add_months, getdate, today

    today_date = getdate(today())
    this_start = str(get_first_day(today_date))
    this_end   = str(get_last_day(today_date))
    last_start = str(get_first_day(add_months(today_date, -1)))
    last_end   = str(get_last_day(add_months(today_date, -1)))

    this_label = get_first_day(today_date).strftime("%b %Y")
    last_label = get_first_day(add_months(today_date, -1)).strftime("%b %Y")

    rows = frappe.db.sql("""
        SELECT
            customer,
            SUM(CASE WHEN posting_date BETWEEN %(ts)s AND %(te)s THEN grand_total ELSE 0 END) AS this_month,
            SUM(CASE WHEN posting_date BETWEEN %(ls)s AND %(le)s THEN grand_total ELSE 0 END) AS last_month
        FROM `tabSales Invoice`
        WHERE docstatus = 1
          AND posting_date BETWEEN %(ls)s AND %(te)s
        GROUP BY customer
        ORDER BY this_month DESC
        LIMIT 10
    """, {"ts": this_start, "te": this_end, "ls": last_start, "le": last_end}, as_dict=True)

    return {
        "data": rows,
        "chart_type": "grouped_bar",
        "x_field": "customer",
        "series": [
            {"field": "this_month", "label": this_label},
            {"field": "last_month", "label": last_label},
        ],
        "title": f"Top 10 Revenue Contributors: {this_label} vs {last_label}",
    }


def _get_cash_vs_obligations() -> dict:
    from frappe.utils import today, add_days
    today_str = today()
    end_str = add_days(today_str, 30)

    cash = frappe.db.sql("""
        SELECT COALESCE(SUM(debit - credit), 0) as balance
        FROM `tabGL Entry`
        WHERE account IN (
            SELECT name FROM `tabAccount`
            WHERE account_type IN ('Bank', 'Cash') AND is_group = 0
        )
        AND is_cancelled = 0
    """, as_dict=True)
    cash_balance = float(cash[0].balance or 0)

    obligations = frappe.db.sql("""
        SELECT COALESCE(SUM(outstanding_amount), 0) as total
        FROM `tabPurchase Invoice`
        WHERE status IN ('Unpaid', 'Overdue', 'Partly Paid')
          AND due_date BETWEEN %s AND %s
          AND docstatus = 1
    """, (today_str, end_str), as_dict=True)
    obligations_total = float(obligations[0].total or 0)

    net = cash_balance - obligations_total

    rows = [
        {"metric": "Current Cash Position", "amount": cash_balance},
        {"metric": f"Obligations Due (next 30 days, by {end_str})", "amount": obligations_total},
        {"metric": "Net Position", "amount": net},
    ]
    return {
        "data": rows,
        "chart_type": "bar",
        "x_field": "metric",
        "y_field": "amount",
        "title": f"Cash Position vs Upcoming Obligations (next 30 days)",
    }


@frappe.whitelist()
def ask_logikmind(question: str) -> dict:
    print(f"\n{'='*60}")
    print(f"[logikbrain] ask_logikmind called — question: {question!r}")
    print(f"{'='*60}\n")

    q_lower = question.lower()

    # Short-circuit: month-over-month revenue comparison — two queries + grouped bar
    mom_keywords = {"vs last month", "this month vs", "month vs month", "compared to last month", "month over month"}
    if any(kw in q_lower for kw in mom_keywords):
        print("[logikbrain] detected MoM revenue question — using dedicated handler")
        result = _get_revenue_mom_comparison()
        result["currency"] = _get_default_currency()
        return result

    # Short-circuit: cash position vs obligations requires GL Entry — bypass LLM query builder
    cash_keywords = {"cash position", "cash vs", "obligations", "upcoming obligations", "cash balance"}
    if any(kw in q_lower for kw in cash_keywords):
        print("[logikbrain] detected cash position question — using dedicated handler")
        result = _get_cash_vs_obligations()
        result["currency"] = _get_default_currency()
        return result

    # Step 1 — route to relevant DocTypes
    routing_prompt = f"""You are an ERPNext assistant. Given a user question, identify which of the following DocTypes are needed to answer it.

DocTypes: {", ".join(ROUTABLE_DOCTYPES)}

Routing rules:
- Questions about sales revenue, customers, invoices issued → Sales Invoice
- Questions about purchase spend, procurement, supplier payments, bills received → Purchase Invoice
- Questions about items sold, products, SKUs → Sales Invoice Item
- Questions about items purchased, goods received → Purchase Invoice Item
- Questions about stock movements, warehouse transfers, goods issued/received into warehouse → Stock Entry
- Questions about payments received or made → Payment Entry
- Stock Entry does NOT contain purchase spend by supplier — use Purchase Invoice for that

User question: {question}

Respond ONLY with valid JSON in this exact format:
{{"doctypes": ["Sales Invoice"]}}

Do not include any explanation or extra text."""

    print("[logikbrain] --- STEP 1: routing ---")
    try:
        routing_result = call_ollama(routing_prompt)
        relevant_doctypes = routing_result.get("doctypes") or ["Sales Invoice"]
        if not isinstance(relevant_doctypes, list) or not relevant_doctypes:
            relevant_doctypes = ["Sales Invoice"]
    except frappe.ValidationError:
        relevant_doctypes = ["Sales Invoice"]

    # Keyword overrides — force correct doctypes regardless of routing result
    q_words = set(question.lower().split())

    # Items/products → Sales Invoice Item
    item_keywords = {"item", "items", "product", "products", "sku", "skus"}
    if q_words & item_keywords:
        if "Sales Invoice Item" not in relevant_doctypes:
            relevant_doctypes = ["Sales Invoice Item"] + [
                d for d in relevant_doctypes if d not in ("Item", "Sales Invoice Item")
            ]
            print(f"[logikbrain] overrode doctypes to include Sales Invoice Item: {relevant_doctypes}")

    # Conversion rate / win rate → Opportunity (not Sales Invoice)
    conversion_keywords = {"conversion", "convert", "converted", "win", "won", "winrate"}
    if q_words & conversion_keywords:
        if "Opportunity" not in relevant_doctypes:
            relevant_doctypes = ["Opportunity"] + [d for d in relevant_doctypes if d != "Opportunity"]
            print(f"[logikbrain] overrode doctypes to include Opportunity (conversion): {relevant_doctypes}")
        relevant_doctypes = [d for d in relevant_doctypes if d not in ("Sales Invoice", "Sales Invoice Item")]
        print(f"[logikbrain] removed Sales Invoice for conversion question: {relevant_doctypes}")

    # Salesperson / sales team → Sales Team child table
    salesperson_keywords = {"salesperson", "salespersons", "salespeople", "sales_person"}
    q_phrase = question.lower()
    if q_words & salesperson_keywords or "sales person" in q_phrase or "by salesperson" in q_phrase or "sales team" in q_phrase:
        if "Sales Team" not in relevant_doctypes:
            relevant_doctypes = ["Sales Team"] + [d for d in relevant_doctypes if d != "Sales Team"]
            print(f"[logikbrain] overrode doctypes to include Sales Team: {relevant_doctypes}")

    # Deals/pipeline/opportunities → Opportunity
    crm_opportunity_keywords = {"deal", "deals", "opportunity", "opportunities", "pipeline", "prospect", "prospects"}
    if q_words & crm_opportunity_keywords:
        if "Opportunity" not in relevant_doctypes:
            relevant_doctypes = ["Opportunity"] + [d for d in relevant_doctypes if d != "Opportunity"]
            print(f"[logikbrain] overrode doctypes to include Opportunity: {relevant_doctypes}")

    # Leads → Lead
    crm_lead_keywords = {"lead", "leads", "enquiry", "enquiries", "inquiry", "inquiries"}
    if q_words & crm_lead_keywords:
        if "Lead" not in relevant_doctypes:
            relevant_doctypes = ["Lead"] + [d for d in relevant_doctypes if d != "Lead"]
            print(f"[logikbrain] overrode doctypes to include Lead: {relevant_doctypes}")

    # Purchase/supplier spend → Purchase Invoice (not Stock Entry)
    purchase_keywords = {"purchase", "purchases", "procurement", "spend", "spending", "supplier", "suppliers", "bought", "buying"}
    if q_words & purchase_keywords:
        if "Purchase Invoice" not in relevant_doctypes:
            relevant_doctypes = ["Purchase Invoice"] + [d for d in relevant_doctypes if d != "Purchase Invoice"]
            print(f"[logikbrain] overrode doctypes to include Purchase Invoice: {relevant_doctypes}")
        # Remove Stock Entry if it snuck in for a purchase question
        if "Stock Entry" in relevant_doctypes and "stock" not in q_words and "warehouse" not in q_words:
            relevant_doctypes = [d for d in relevant_doctypes if d != "Stock Entry"]
            print(f"[logikbrain] removed Stock Entry from purchase question: {relevant_doctypes}")

    print(f"[logikbrain] selected doctypes: {relevant_doctypes}\n")

    # Step 2 — fetch compressed schema
    schema = get_doctype_schema(relevant_doctypes)
    print(f"[logikbrain] --- STEP 2: schema ---\n{schema}\n")

    # Step 3 — generate query params and chart metadata
    from frappe.utils import today as _today
    today_str = _today()

    query_prompt = f"""You are an ERPNext query builder. Using the schema below and the user question, produce a frappe.db.get_list() query and chart configuration.

Today's date: {today_str}

Schema:
{schema}

User question: {question}

DocType selection rules:
- Questions about sales revenue, customers, invoices issued → use "Sales Invoice"
- Questions about purchase spend, procurement, supplier payments → use "Purchase Invoice"
- Questions about items sold, products, SKUs → use "Sales Invoice Item" or "Purchase Invoice Item"
- Questions about stock movements, warehouse transfers → use "Stock Entry"
- Questions about deals, opportunities, pipeline, prospects → use "Opportunity"
- Questions about leads, enquiries, prospects not yet converted → use "Lead"
- The "group_by" field MUST match the "x_field" exactly
- The "order_by" MUST be "{{y_field}} desc" where {{y_field}} is the alias of the aggregate field

Chart type selection rules — choose chart_type based on what the question is asking:
- "bar"   → ranking or comparing discrete categories (top customers, best-selling items, suppliers by spend)
- "line"  → trend over time where x_field is a date/month/year (monthly revenue, daily sales)
- "pie"   → how a total is divided across categories, especially when the question uses words like "breakdown", "distribution", "share", "proportion", "composition", "split", "percentage"
- "donut" → same as pie but when there are very few categories (2-4), e.g. paid vs unpaid, stock entry types

Query type guidance — choose the right aggregate:
- Ranking/totalling by category → "sum(<amount field>) as total"
- Counting records by category → "count(name) as count"
- "paid vs unpaid", "status breakdown", "by type" → GROUP BY status/type field, use count(name) as count
- The "status" field on Sales Invoice contains values: "Draft", "Submitted", "Return", "Credit Note Issued", "Paid", "Partly Paid", "Unpaid", "Overdue", "Partly Paid and Overdue", "Cancelled"
- LIST queries (no aggregation): when the question asks "which records...", "show me deals...", "list invoices..." — use fields like ["name", "customer", "status", "modified"] with NO group_by, NO aggregate, just filters
- IDLE / STALE queries: "idle for N days" or "no activity for N days" means modified < (today minus N days). Use today's date above to compute the cutoff date as a YYYY-MM-DD string. Example: "idle 14 days" with today=2026-04-19 → filter ["modified", "<", "2026-04-05"]
- RATE / RATIO queries: "conversion rate", "win rate", "success rate" → use CASE WHEN inside COUNT to compute a percentage. Example: ROUND(COUNT(CASE WHEN status='Converted' THEN 1 END) * 100.0 / COUNT(*), 1) as conversion_rate
- Opportunity fields: opportunity_owner (salesperson), status (Open/Converted/Lost/Closed/Replied/Quotation), sales_stage
- Lead fields: lead_owner (salesperson), status (Open/Replied/Opportunity/Interested/Converted/Do Not Contact)
- Sales Team fields: sales_person, allocated_amount, allocated_percentage, incentives — this is a child table of Sales Invoice; always include filter ["parenttype", "=", "Sales Invoice"] when querying it
- "revenue by salesperson", "sales by salesperson", "commission by salesperson" → use "Sales Team", group by sales_person, sum(allocated_amount)

Examples (full correct JSON):
"top 10 customers by revenue" →
  fields: ["customer", "sum(grand_total) as revenue"], group_by: "customer", chart_type: "bar"
"monthly revenue trend" →
  fields: ["posting_date", "sum(grand_total) as revenue"], group_by: "posting_date", chart_type: "line"
"revenue breakdown by customer group" →
  fields: ["customer_group", "sum(grand_total) as revenue"], group_by: "customer_group", chart_type: "pie"
"paid vs unpaid invoices proportion" →
  fields: ["status", "count(name) as count"], group_by: "status", chart_type: "donut", filters: []
"payment entries by type" →
  fields: ["payment_type", "count(name) as count"], group_by: "payment_type", chart_type: "donut", filters: []

IMPORTANT filter rules:
- Only add filters when the user explicitly asks to filter (e.g. "this month", "last year", "for customer X")
- Do NOT add filters like company="All" or arbitrary date ranges — leave filters as [] if not needed
- docstatus filters are never needed

Respond ONLY with valid JSON matching this shape — choose values appropriate to the question, do NOT copy the example values:
{{
  "doctype": "<choose from schema>",
  "filters": [],
  "fields": ["<group field>", "sum(<value field>) as <alias>"],
  "group_by": "<group field>",
  "order_by": "<alias> desc",
  "limit": 10,
  "chart_type": "<bar|line|pie|donut>",
  "x_field": "<group field>",
  "y_field": "<alias>",
  "title": "<descriptive title>"
}}

Rules:
- chart_type must be one of: bar, line, pie, donut
- filters must be a list of [field, operator, value] triples — omit filters entirely if none are needed
- fields must include the group field AND the aggregate expression
- group_by and order_by must never be null when aggregates are used
- limit must be an integer"""

    print("[logikbrain] --- STEP 3: query build ---")
    query_config = call_ollama(query_prompt)

    fields = query_config.get("fields") or []
    BOGUS_FILTER_VALUES = {"*", "%", "%%", "", None, "null", "all", "All", "any", "Any",
                           "none", "None", "everything", "0000-00-00", "1900-01-01"}

    import re as _re

    # Drop wildcard/useless filters the model sometimes generates
    raw_filters = query_config.get("filters") or []
    def _is_bogus(f):
        if not (isinstance(f, list) and len(f) >= 3):
            return False
        val = f[2]
        if str(val) in BOGUS_FILTER_VALUES:
            return True
        # Drop hallucinated date filters (dates before 2000 or more than 1 year in future)
        if isinstance(val, str) and _re.match(r'^\d{4}-\d{2}-\d{2}$', val):
            year = int(val[:4])
            if year < 2000 or year > 2030:
                return True
        return False
    clean_filters = [f for f in raw_filters if not _is_bogus(f)]
    if len(clean_filters) != len(raw_filters):
        print(f"[logikbrain] dropped {len(raw_filters) - len(clean_filters)} bogus filter(s): {[f for f in raw_filters if _is_bogus(f)]}")
    query_config["filters"] = clean_filters

    # Auto-fix: if aggregates present but group_by missing, derive from non-aggregate fields
    has_aggregate = any(
        any(fn in f.lower() for fn in ("sum(", "count(", "avg(", "max(", "min("))
        for f in fields
    )
    if has_aggregate and not query_config.get("group_by"):
        non_aggregate = [f for f in fields if not any(
            fn in f.lower() for fn in ("sum(", "count(", "avg(", "max(", "min(")
        )]
        if non_aggregate:
            query_config["group_by"] = ", ".join(non_aggregate)
            print(f"[logikbrain] auto-fixed missing group_by: {query_config['group_by']}")

    # Auto-fix: derive missing x_field / y_field / title from fields list
    if not query_config.get("x_field") or not query_config.get("y_field"):
        aggregate_fns = ("sum(", "count(", "avg(", "max(", "min(")
        non_agg = [f for f in fields if not any(fn in f.lower() for fn in aggregate_fns)]
        agg     = [f for f in fields if     any(fn in f.lower() for fn in aggregate_fns)]
        if not query_config.get("x_field") and non_agg:
            query_config["x_field"] = non_agg[0]
            print(f"[logikbrain] auto-derived x_field: {query_config['x_field']}")
        if not query_config.get("y_field") and agg:
            # extract alias after "as"
            alias_match = _re.search(r'\bas\s+(\w+)', agg[0], _re.IGNORECASE)
            query_config["y_field"] = alias_match.group(1) if alias_match else agg[0]
            print(f"[logikbrain] auto-derived y_field: {query_config['y_field']}")
    if not query_config.get("title"):
        query_config["title"] = question
        print(f"[logikbrain] auto-derived title from question")

    # Auto-fix: if order_by is missing but y_field exists, default to y_field desc
    if not query_config.get("order_by") and query_config.get("y_field"):
        query_config["order_by"] = f"{query_config['y_field']} desc"
        print(f"[logikbrain] auto-fixed missing order_by: {query_config['order_by']}")

    # Auto-fix: breakdown/distribution questions → donut chart
    breakdown_keywords = {"breakdown", "distribution", "share", "proportion", "split", "mix", "composition"}
    if any(w in question.lower().split() for w in breakdown_keywords):
        if query_config.get("chart_type") not in ("pie", "donut"):
            query_config["chart_type"] = "donut"
            print(f"[logikbrain] auto-fixed chart_type to donut (breakdown question)")

    # Auto-fix: date x-axis → line chart + sort chronologically
    x_field = query_config.get("x_field", "")
    if any(kw in x_field.lower() for kw in ("date", "month", "year", "week", "day")):
        if query_config.get("chart_type") != "line":
            query_config["chart_type"] = "line"
            print(f"[logikbrain] auto-fixed chart_type to line (date x-axis)")
        query_config["order_by"] = f"{x_field} asc"
        print(f"[logikbrain] auto-fixed order_by to {x_field} asc (chronological)")

    # Auto-fix: ensure x_field is present in fields list
    x_field = query_config.get("x_field")
    if x_field and not any(x_field == f or f.startswith(x_field + " ") for f in fields):
        fields.insert(0, x_field)
        query_config["fields"] = fields
        print(f"[logikbrain] auto-added missing x_field '{x_field}' to fields")

    print(f"[logikbrain] query config:\n{json.dumps(query_config, indent=2)}\n")

    # Data fetch
    try:
        doctype = query_config["doctype"]
        q_fields = query_config.get("fields") or ["name"]
        q_filters = query_config.get("filters") or []
        q_group_by = query_config.get("group_by")
        q_order_by = query_config.get("order_by")
        q_limit = int(query_config.get("limit") or 20)

        print(f"[logikbrain] --- STEP 4: data fetch ---")

        # Validate that all column references exist in the actual table
        actual_columns = set(frappe.db.get_table_columns(doctype))
        SQL_KEYWORDS = {"as", "sum", "count", "avg", "max", "min", "distinct", "coalesce",
                        "ifnull", "if", "case", "when", "then", "else", "end", "round",
                        "nullif", "greatest", "least", "floor", "ceil", "abs"}
        bad_cols = []
        for field_expr in q_fields:
            # Strip the alias (everything after last " as ") before tokenising
            expr_no_alias = _re.split(r'\bas\b', field_expr, flags=_re.IGNORECASE)[0]
            # Strip string literals (e.g. 'Converted', "Open") so their contents aren't validated
            expr_no_strings = _re.sub(r"'[^']*'|\"[^\"]*\"", "", expr_no_alias)
            # Strip numeric literals
            expr_no_strings = _re.sub(r'\b\d+(\.\d+)?\b', '', expr_no_strings)
            tokens = _re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', expr_no_strings.lower())
            for tok in tokens:
                if tok not in SQL_KEYWORDS and tok not in actual_columns:
                    bad_cols.append(tok)
        if bad_cols:
            print(f"[logikbrain] invalid column(s): {bad_cols} — retrying with correction prompt")
            # Preserve chart_type already decided by post-processing before we overwrite query_config
            resolved_chart_type = query_config.get("chart_type")
            numeric_cols = [c for c in sorted(actual_columns) if not c.startswith("custom_")]
            correction_prompt = f"""The previous query used invalid column(s) {bad_cols} which do not exist in the DocType "{doctype}".

Available columns: {", ".join(numeric_cols)}

Original user question: {question}

Produce a corrected frappe query using ONLY the available columns above. Respond ONLY with valid JSON in this exact shape:
{{
  "doctype": "{doctype}",
  "filters": [],
  "fields": ["<group field>", "sum(<value field>) as <alias>"],
  "group_by": "<group field>",
  "order_by": "<alias> desc",
  "limit": 10,
  "chart_type": "bar",
  "x_field": "<group field>",
  "y_field": "<alias>",
  "title": "<descriptive title>"
}}"""
            print("[logikbrain] --- STEP 3b: correction retry ---")
            query_config = call_ollama(correction_prompt)
            # Restore the chart_type that post-processing already resolved
            if resolved_chart_type:
                query_config["chart_type"] = resolved_chart_type

            # Re-apply post-processing fixes to corrected config
            fields = query_config.get("fields") or []
            raw_filters = query_config.get("filters") or []
            clean_filters = [f for f in raw_filters if not (isinstance(f, list) and len(f) >= 3 and str(f[2]) in BOGUS_FILTER_VALUES)]
            query_config["filters"] = clean_filters
            has_aggregate = any(
                any(fn in f.lower() for fn in ("sum(", "count(", "avg(", "max(", "min("))
                for f in fields
            )
            if has_aggregate and not query_config.get("group_by"):
                non_aggregate = [f for f in fields if not any(fn in f.lower() for fn in ("sum(", "count(", "avg(", "max(", "min("))]
                if non_aggregate:
                    query_config["group_by"] = ", ".join(non_aggregate)
            if not query_config.get("order_by") and query_config.get("y_field"):
                query_config["order_by"] = f"{query_config['y_field']} desc"

            # Re-validate corrected fields
            doctype = query_config["doctype"]
            q_fields = query_config.get("fields") or ["name"]
            q_filters = query_config.get("filters") or []
            q_group_by = query_config.get("group_by")
            q_order_by = query_config.get("order_by")
            q_limit = int(query_config.get("limit") or 20)
            actual_columns = set(frappe.db.get_table_columns(doctype))

            bad_cols = []
            for field_expr in q_fields:
                expr_no_alias = _re.split(r'\bas\b', field_expr, flags=_re.IGNORECASE)[0]
                tokens = _re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', expr_no_alias.lower())
                for tok in tokens:
                    if tok not in SQL_KEYWORDS and tok not in actual_columns:
                        bad_cols.append(tok)
            if bad_cols:
                print(f"[logikbrain] still invalid after retry: {bad_cols}")
                raise frappe.ValidationError(
                    f"AI could not produce a valid query for '{doctype}'. Try rephrasing your question."
                )

        if has_aggregate:
            # frappe.db.get_list silently drops GROUP BY fields from results;
            # use raw SQL so all selected columns are returned correctly.
            field_sql = ", ".join(q_fields)
            sql = f"SELECT {field_sql} FROM `tab{doctype}`"
            params = []
            if q_filters:
                clauses = []
                for f in q_filters:
                    if isinstance(f, list) and len(f) == 3:
                        clauses.append(f"`{f[0]}` {f[1]} %s")
                        params.append(f[2])
                if clauses:
                    sql += " WHERE " + " AND ".join(clauses)
            if q_group_by:
                sql += f" GROUP BY {q_group_by}"
            if q_order_by:
                sql += f" ORDER BY {q_order_by}"
            sql += f" LIMIT {q_limit}"
            print(f"[logikbrain] SQL: {sql}  params={params}")
            data = frappe.db.sql(sql, params, as_dict=True)
        else:
            kwargs = {
                "doctype": doctype,
                "fields": q_fields,
                "filters": q_filters,
                "limit": q_limit,
            }
            if q_order_by:
                kwargs["order_by"] = q_order_by
            print(f"[logikbrain] frappe.db.get_list kwargs:\n{json.dumps(kwargs, indent=2, default=str)}\n")
            data = frappe.db.get_list(**kwargs)

        print(f"[logikbrain] got {len(data)} rows")
        print(f"[logikbrain] data sample (first 3): {json.dumps(data[:3], indent=2, default=str)}\n")
    except Exception as e:
        print(f"[logikbrain] ERROR in data fetch: {e}")
        raise frappe.ValidationError(
            f"Could not fetch data for '{query_config.get('doctype', 'unknown')}': {e}"
        )

    chart_type = query_config.get("chart_type", "bar")

    # Auto-fix: few categories on a bar → donut (e.g. "payment type", "stock entry type")
    x_field_final = query_config.get("x_field", "")
    is_date_axis = any(kw in x_field_final.lower() for kw in ("date", "month", "year", "week", "day"))
    if chart_type == "bar" and not is_date_axis and len(data) <= 5:
        chart_type = "donut"
        print(f"[logikbrain] auto-fixed chart_type to donut (≤5 categories)")

    result = {
        "data": data,
        "chart_type": chart_type,
        "x_field": x_field_final,
        "y_field": query_config.get("y_field", ""),
        "title": query_config.get("title", question),
        "currency": _get_default_currency(),
    }
    print(f"[logikbrain] returning result: chart_type={result['chart_type']}, x={result['x_field']}, y={result['y_field']}, rows={len(data)}")
    print(f"{'='*60}\n")
    return result

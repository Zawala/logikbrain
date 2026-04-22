# Logikbrain

**Plain-English analytics and visualisation for ERPNext — powered by a local AI model.**

Type a business question. Get a chart, a data table, and a one-sentence insight. No SQL, no report builder, no training required.

---

## What it does

Logikbrain is a web page that lives inside your ERPNext / Frappe site (`/logikbrain`). You type a question in plain English, and the tool:

1. Works out which ERPNext DocTypes are relevant to the question.
2. Uses an AI model (running locally via Ollama) to translate the question into a database query.
3. Executes the query against your live ERPNext data.
4. Renders the result as an interactive chart (bar, line, pie, or donut) with a scrollable data table underneath.
5. Generates a short plain-English insight about what the data shows.
6. Lets you export the whole result — chart, insight, table — as a print-ready PDF.

---

## Security

Access is protected by Frappe's built-in authentication. The page sets:

```python
login_required = 1
```

Any unauthenticated request is rejected before the page renders. The AI model and all database queries run entirely on your own server — no data leaves your infrastructure.

---

## Architecture

```
Browser
  │  plain-English question
  ▼
logikbrain.js  (frappe.call)
  │
  ▼
www/api.py  (ask_logikmind)
  │
  ├─ Step 1 · DocType routing
  │    Send question + DocType list → Ollama
  │    Receive: which DocTypes are relevant
  │
  ├─ Step 2 · Schema fetch
  │    Read live Frappe meta for those DocTypes
  │    Build a compact field list (name, type only)
  │
  ├─ Step 3 · Query build
  │    Send question + schema → Ollama
  │    Receive: doctype, fields, filters, group_by, order_by, chart_type, x_field, y_field, title
  │
  ├─ Step 3b · Auto-correction (if bad columns detected)
  │    Re-send with actual column list → Ollama retries once
  │
  ├─ Step 4 · Data fetch
  │    Execute query against MariaDB via frappe.db / raw SQL
  │
  └─ Step 5 · Insight generation (async, parallel in browser)
       Send question + data sample → Ollama
       Receive: 1-2 sentence business insight
  │
  ▼
logikbrain.js  renderChart()
  Apache ECharts 5  →  bar / line / pie / donut
```

Hard-coded short-circuits bypass the LLM entirely for two complex queries that require multi-table logic:

- **Month-over-month revenue comparison** — two date ranges joined in one SQL query, rendered as a grouped bar chart.
- **Cash position vs upcoming obligations** — reads GL Entry (bank/cash accounts) and Purchase Invoice (due dates), renders as a bar chart.

---

## AI Model

| Setting | Value |
|---|---|
| Runtime | [Ollama](https://ollama.com) |
| Model | `llama3.1:8b` |
| Endpoint | `http://localhost:11434/api/generate` |
| Response format | Structured JSON (Ollama `format: "json"` mode) |
| Request timeout | 300 seconds |

`llama3.1:8b` is Meta's 8-billion-parameter instruction-tuned model. It is the recommended choice for this tool because:

- It reliably outputs valid JSON when given a schema.
- It fits in 8 GB of VRAM (or runs on CPU with 16 GB RAM).
- It is fast enough for interactive use on modest hardware.

### Expected performance on a local Ollama instance

| Hardware | Routing step | Query-build step | Insight step | Total wall time |
|---|---|---|---|---|
| GPU with 8 GB VRAM (e.g. RTX 3070) | ~3 s | ~8 s | ~5 s | ~16 s |
| Apple Silicon (M1/M2, unified memory) | ~5 s | ~12 s | ~7 s | ~24 s |
| CPU only, 16 GB RAM | ~30 s | ~90 s | ~40 s | ~2.5 min |

These are estimates. Actual times depend on RAM bandwidth, thermal throttling, and Ollama's layer-offloading configuration. The insight step runs in parallel with chart rendering so it does not block the chart from appearing.

---

## Installation

### 1. Install Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Ollama supports Linux (x86-64, ARM64), macOS (Apple Silicon and Intel), and Windows (via WSL2).

### 2. Pull the model

```bash
ollama pull llama3.1:8b
```

Download size: ~4.7 GB. Stored in `~/.ollama/models/`.

### 3. Start Ollama

```bash
ollama serve
```

Ollama listens on `http://localhost:11434` by default. On most systems it starts automatically as a systemd service after installation.

### 4. Add Logikbrain to your Frappe app

Copy the `www/` folder contents into your custom Frappe app's `www/` directory:

```
your_app/
└── www/
    ├── logikbrain.py
    ├── logikbrain.html
    ├── logikbrain.js
    ├── logikbrain.json   (page metadata)
    └── api.py
```

Then run:

```bash
bench migrate
bench build
```

The page will be available at `https://your-site/logikbrain`.

### 5. Verify the pipeline

Open the page, log in, and ask:

> **Show me the top 10 customers by revenue this month**

If a bar chart appears within ~20 seconds, the full pipeline — Frappe auth → Ollama routing → schema fetch → query build → data fetch → chart render — is working end to end.

---

## Minimum machine requirements

| Component | Minimum | Recommended |
|---|---|---|
| RAM | 16 GB | 32 GB |
| VRAM | None (CPU mode) | 8 GB |
| Disk | 10 GB free (model + swap) | 20 GB |
| OS | Linux (Ubuntu 20.04+), macOS 12+ | Ubuntu 22.04 LTS |
| Frappe | v14 or v15 | v15 |
| Python | 3.10+ | 3.11 |

CPU-only mode works but is slow (see performance table above). A GPU is strongly recommended for production use.

---

## Supported DocTypes and questions

Logikbrain can route to these DocTypes:

| DocType | What it covers |
|---|---|
| Sales Invoice | Revenue, customers, invoices issued |
| Sales Invoice Item | Items sold, product-level revenue |
| Purchase Invoice | Supplier spend, procurement, bills |
| Purchase Invoice Item | Items purchased, goods received |
| Customer | Customer master data |
| Supplier | Supplier master data |
| Item | Item/product catalogue |
| Stock Entry | Warehouse transfers, stock movements |
| Payment Entry | Payments received or made |
| Journal Entry | Manual accounting entries |
| Opportunity | CRM pipeline, deals, prospects |
| Lead | CRM leads, enquiries |
| Sales Team | Salesperson allocation on invoices |

### Example questions by chart type

**Bar charts** — ranking or comparing categories

- Show me the top 10 customers by revenue this month
- Which suppliers have the highest total purchase value this year
- Show me the top 5 items by total quantity sold this quarter
- Compare total sales by customer group this year

**Line charts** — trends over time

- Show me monthly revenue trend for this year
- How has our total purchase spend changed month by month this year
- Show me daily sales totals for the last 30 days
- Track monthly stock entry values for the last 6 months

**Pie charts** — composition and share

- What is the revenue breakdown by customer group
- Show me purchase spend distribution by supplier
- What percentage of sales come from each territory
- Break down total inventory value by item group

**Donut charts** — split across a small number of categories

- Show me the proportion of paid vs unpaid sales invoices
- What is the split of stock entries by entry type
- Show me payment entries broken down by payment type

**Sales pipeline and CRM**

- Which quotations are most likely to close this week
- Which deals have been idle for more than 14 days
- Show me conversion rate by salesperson
- What is our pipeline coverage vs target (next 90 days)
- Which customers have not purchased in the last 6 months

**Finance and cash flow**

- What is our current cash position vs upcoming obligations (next 30 days)
- Which customers are overdue, and how much is at risk
- Show me top 10 revenue contributors this month vs last month
- What is our gross margin by product/service line
- Are there any unusual expense spikes this week

---

## How the AI model is used

The model is called twice (three times if a query correction is needed) for each question:

**Call 1 — DocType routing**
A short prompt listing all supported DocTypes. The model returns a JSON array of the ones relevant to the question. This keeps the second prompt focused and reduces hallucination.

**Call 2 — Query build**
A longer prompt containing the question, today's date, and the compressed schema (field names and types only) for the selected DocTypes. The model returns a JSON object describing the full query: doctype, fields, filters, group_by, order_by, limit, chart type, axis fields, and a chart title.

**Call 3 (if needed) — Query correction**
If the model references columns that do not exist in the actual MariaDB table, the tool sends a correction prompt with the real column list and asks the model to try again.

**Call 4 — Insight generation** (async, does not block the chart)
After the chart is rendered, a separate call sends the question and up to 10 rows of data. The model returns one or two sentences of plain-English business insight. If the data is straightforward it returns an empty string and no insight panel is shown.

All calls use Ollama's `format: "json"` parameter, which constrains the model's output to valid JSON. The tool validates the JSON structure, scrubs hallucinated filter values, and applies a set of deterministic post-processing fixes before executing any query.

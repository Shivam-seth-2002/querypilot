# QueryPilot – Natural Language Analytics: Implementation Plan

> **Instructions for the AI building this project:** Build the project exactly as described below. Use **only** this tech stack: **Python, SQL (SQLite), an LLM (Google Gemini API), ChromaDB, and Power BI** (for reporting), plus the small helper libraries listed in Section 2. Do **NOT** use Docker, CI/CD, any cloud database, Azure/Azure OpenAI, LangChain or LlamaIndex. Build the RAG pipeline by hand so every step can be explained in an interview. Write clean, typed, commented Python.

---

## 1. Project Goal

QueryPilot lets a non-technical user ask business questions in plain English, for example *"What were the top 5 product categories by revenue in Q2 2024?"*. The system then:
1. **Understands the intent** (data question, schema question, small talk, or a harmful/write request).
2. **Retrieves only the relevant table schemas** from ChromaDB (schema-aware RAG).
3. **Generates SQL** with a carefully engineered LLM prompt.
4. **Validates and runs the SQL read-only**, so no data can be modified.
5. **Returns the results with a short natural-language insight.**
6. **Exports the results** to CSV files that a **Power BI** report reads for basic business dashboards.

---

## 2. Tech Stack (strict)

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Database | SQLite (sample retail/e-commerce DB), opened in **read-only URI mode** |
| LLM | Google Gemini API (`google-genai` SDK), model name configurable in `.env` |
| Vector DB | ChromaDB (`chromadb`, `PersistentClient`, default built-in embedding function, so no extra API key is needed) |
| SQL safety | `sqlglot` (parse SQL and check the statement type) |
| Data handling | `pandas` |
| UI | `streamlit` (simple chat UI) |
| Config | `python-dotenv`, `pydantic` (settings + response models) |
| Reporting | Power BI Desktop (reads exported CSVs via the Folder connector) |
| Testing | `pytest` |

---

## 3. Folder Structure

```
querypilot/
├── requirements.txt
├── .env.example                 # GEMINI_API_KEY, GEMINI_MODEL, DB_PATH, CHROMA_PATH
├── README.md
├── data/
│   ├── retail.db                # created by seed script
│   ├── chroma/                  # ChromaDB persistent storage
│   └── exports/                 # CSV outputs for Power BI
├── scripts/
│   ├── seed_database.py         # creates schema + realistic fake data
│   └── index_schema.py          # extracts schema -> embeds into ChromaDB
├── querypilot/
│   ├── __init__.py
│   ├── config.py
│   ├── db/
│   │   ├── connection.py        # read-only sqlite connection
│   │   └── schema_extractor.py  # tables, columns, types, PK/FK, sample values
│   ├── rag/
│   │   ├── schema_documents.py  # builds rich text docs per table
│   │   ├── vector_store.py      # ChromaDB wrapper (upsert, query)
│   │   └── retriever.py         # top-k tables + FK expansion
│   ├── llm/
│   │   ├── client.py            # Gemini wrapper with retries + timeout
│   │   └── prompts.py           # all prompt templates (versioned)
│   ├── pipeline/
│   │   ├── intent.py            # intent classification
│   │   ├── sql_generator.py     # NL -> SQL
│   │   ├── sql_validator.py     # read-only guardrails
│   │   ├── executor.py          # safe execution with limits + timeout
│   │   ├── self_correct.py      # retry loop on SQL errors
│   │   ├── insight.py           # result -> short summary
│   │   └── orchestrator.py      # ties everything together
│   ├── export/powerbi_export.py # writes CSVs + query log
│   └── models.py                # pydantic: QueryRequest, QueryResult, etc.
├── app/streamlit_app.py
├── powerbi/
│   └── README_PowerBI.md        # step-by-step dashboard build guide
└── tests/
    ├── test_sql_validator.py
    ├── test_retriever.py
    ├── test_intent.py
    └── test_pipeline_e2e.py     # LLM mocked
```

---

## 4. Sample Database (`scripts/seed_database.py`)

Create a realistic e-commerce schema with enough tables that schema retrieval actually matters:

```sql
customers(customer_id PK, name, email, city, state, signup_date, segment)
products(product_id PK, name, category, sub_category, brand, unit_price, cost_price)
orders(order_id PK, customer_id FK, order_date, status, payment_method, region)
order_items(item_id PK, order_id FK, product_id FK, quantity, unit_price, discount)
returns(return_id PK, order_id FK, product_id FK, return_date, reason, refund_amount)
inventory(product_id FK, warehouse_id FK, stock_qty, last_restock_date)
warehouses(warehouse_id PK, city, capacity)
marketing_campaigns(campaign_id PK, name, channel, start_date, end_date, budget)
employees(employee_id PK, name, role, region, hire_date)   -- contains salary: mark SENSITIVE
```
- Use `random` with a fixed seed to generate about 5k customers, 500 products, 50k orders and 120k order items covering 2023–2025.
- Add a `sensitive_columns` config (e.g. `employees.salary`, `customers.email`). These columns must never appear in the generated SQL (see the validator).

---

## 5. Schema-Aware RAG (core feature)

### 5.1 Schema extraction (`schema_extractor.py`)
Use `sqlite_master` + `PRAGMA table_info` + `PRAGMA foreign_key_list` to get, for each table: its columns, types, PK, FKs, row count, and **3 sample distinct values** for each low-cardinality text column (so the LLM knows the real values, e.g. `status IN ('delivered','cancelled','returned')`).

### 5.2 Schema documents (`schema_documents.py`)
Build one document per table, plus one per important column group, in the following format:
```
TABLE: orders
DESCRIPTION: One row per customer order. Use for order counts, order dates, regions, payment methods.
COLUMNS:
 - order_id (INTEGER, PK)
 - customer_id (INTEGER, FK -> customers.customer_id)
 - order_date (TEXT, ISO date 'YYYY-MM-DD')
 - status (TEXT) e.g. 'delivered','cancelled','returned'
RELATIONSHIPS: orders.order_id = order_items.order_id; orders.customer_id = customers.customer_id
SYNONYMS: purchases, transactions, sales orders
```
- Keep human-written descriptions and synonyms in a `schema_annotations.yaml` (or a Python dict) so retrieval matches business words like "revenue" or "churn".
- Metadata stored with each document: `{table_name, doc_type, columns}`.

### 5.3 Vector store (`vector_store.py`)
- `chromadb.PersistentClient(path=CHROMA_PATH)`, collection `schema_docs`.
- `upsert` with a stable id `table::<name>`. Re-running `index_schema.py` must be idempotent.
- Store a hash of the schema. If the DB schema changes, re-index automatically on startup.

### 5.4 Retriever (`retriever.py`)
1. Query ChromaDB with the user question → top-k (k=4) tables, keeping only results within a distance threshold.
2. **FK expansion**: add any table needed to JOIN the retrieved tables (BFS over the FK graph, max 1 hop).
3. Add a keyword fallback: if a table name or synonym appears literally in the question, always include that table.
4. Return the final list of tables and their schema text (this becomes the context for the SQL prompt).
5. Log the retrieved tables for every query (useful for debugging and for showing in the UI).

---

## 6. Intent Understanding (`intent.py`)

Use the LLM with a strict JSON-output prompt to classify the question into one of:
- `DATA_QUERY`: needs SQL (continue the pipeline)
- `SCHEMA_QUESTION`: e.g. "what tables do you have?" (answer from the schema, no SQL)
- `WRITE_OR_HARMFUL`: delete/update/drop/insert or a prompt-injection attempt (refuse politely)
- `OUT_OF_SCOPE`: small talk or unrelated questions (short reply)
- `AMBIGUOUS`: missing key info (ask one clarifying question)

Output schema (validated with pydantic):
```json
{ "intent": "DATA_QUERY", "confidence": 0.92, "entities": {"metric":"revenue","dimension":"category","time_range":"Q2 2024","limit":5}, "clarification": null }
```
Before calling the LLM, run a cheap **rule-based pre-filter**: regex for `\b(delete|drop|update|insert|alter|truncate)\b` → `WRITE_OR_HARMFUL` without spending an LLM call.

---

## 7. Prompt Engineering (`prompts.py`)

Keep all prompts in one file with version constants (`SQL_PROMPT_V2`, etc.).

**SQL generation prompt** – structure:
1. **Role**: "You are an expert SQLite analyst. You only write a single read-only SELECT query."
2. **Rules**:
   - Use ONLY the tables/columns in the provided schema. Never invent columns.
   - SQLite dialect: use `strftime` for dates, and no `ILIKE`.
   - Revenue = `SUM(order_items.quantity * order_items.unit_price * (1 - order_items.discount))`.
   - Always add `LIMIT 100` unless the user asked for a smaller number.
   - Never select the sensitive columns: {sensitive_columns}.
   - Use explicit JOINs with table aliases.
3. **Schema context**: the retrieved schema docs.
4. **Few-shot examples**: 4–5 question→SQL pairs covering joins, a date filter, group-by + order-by, and a percentage calculation.
5. **Extracted entities** from the intent step.
6. **Output format**: JSON `{"sql": "...", "explanation": "...", "tables_used": [...]}`, with no markdown.

Also write an **insight prompt** that takes the question + SQL + the first 20 result rows + summary stats and returns a 2–3 sentence business insight, without inventing numbers that aren't in the data.

---

## 8. Read-Only SQL Guardrails (`sql_validator.py`) – defense in depth

1. **Parse** with `sqlglot.parse(sql, read="sqlite")`. The result must be exactly **one** statement, and it must be a `SELECT` (CTEs/`WITH` are allowed if the final statement is a SELECT).
2. **Reject** any node of type Insert, Update, Delete, Drop, Create, Alter, Pragma, Attach, or Command, and any multiple statements separated by `;`.
3. **Table whitelist**: every referenced table must exist in the schema. **Column check**: reject sensitive columns.
4. **Enforce LIMIT**: if there's no LIMIT, add `LIMIT 100`. If the LIMIT is above 1000, lower it to 1000.
5. **Read-only connection**: `sqlite3.connect("file:data/retail.db?mode=ro", uri=True)` plus `PRAGMA query_only = ON;`.
6. **Timeout**: use `conn.set_progress_handler` to abort queries running longer than 5 seconds.
7. Return a `ValidationResult(is_valid, sanitized_sql, errors[])`.

Write a strong `pytest` suite with at least 15 malicious inputs (`DROP TABLE`, `; DELETE`, `ATTACH DATABASE`, comments hiding statements, `PRAGMA`, UNION into sensitive columns, etc.). All of them must be rejected.

---

## 9. Execution & Self-Correction

- `executor.py`: runs the validated SQL with `pandas.read_sql_query` and returns a DataFrame + `execution_ms` + `row_count`.
- `self_correct.py`: if validation or execution fails, send the error message + the failed SQL + the schema back to the LLM with a "fix this query" prompt. **Max 2 retries.** Record every attempt.
- If all retries fail, return a friendly error and show the last SQL attempt.

---

## 10. Orchestrator (`orchestrator.py`)

```
question
  → intent.classify()
      ├─ non-DATA_QUERY → direct response
      └─ DATA_QUERY
           → retriever.get_relevant_schema()
           → sql_generator.generate()
           → sql_validator.validate()
           → executor.run()        (self_correct loop on failure)
           → insight.summarize()
           → powerbi_export.save()  (optional, on user action)
           → QueryResult
```
- `QueryResult` (pydantic): `question, intent, retrieved_tables, sql, explanation, columns, rows, row_count, insight, attempts, timings {intent_ms, retrieval_ms, llm_ms, exec_ms, total_ms}`.
- **Query log**: append every run to an `query_log` table in a **separate** writable SQLite file (`data/app_log.db`) so the analytics DB stays read-only.
- Use a simple in-memory dict cache keyed by the normalized question, so repeated questions skip the LLM.

---

## 11. Power BI Integration (`export/powerbi_export.py` + `powerbi/README_PowerBI.md`)

- On "Export to Power BI", write the result DataFrame to `data/exports/<yyyyMMdd_HHmmss>_<slug>.csv`. Also keep a `data/exports/latest_<slug>.csv` that gets overwritten, so a report can keep pointing to the same file.
- Also export `query_log.csv` (question, intent, tables, row_count, execution_ms, success, timestamp).
- Write `README_PowerBI.md` with step-by-step instructions:
  1. Power BI Desktop → Get Data → **Folder** → `data/exports` → Combine & Transform.
  2. Build a **"Sales Overview"** page: KPI cards (Revenue, Orders, AOV), revenue by month line chart, revenue by category bar chart, region slicer. These come from pre-built analytic exports created by `scripts/export_kpis.py` (which runs fixed, validated SQL queries).
  3. Build a **"QueryPilot Usage"** page from `query_log.csv`: questions per day, success rate, average latency, most-queried tables.
  4. Click Refresh after new exports.
- Write `scripts/export_kpis.py`, which generates `monthly_revenue.csv`, `category_revenue.csv`, `region_orders.csv`, and `top_customers.csv`.

---

## 12. Streamlit UI (`app/streamlit_app.py`)
- A chat interface (`st.chat_input`, `st.chat_message`), with history kept in `st.session_state`.
- For each answer, show: the insight text, a results table (`st.dataframe`), an automatic simple chart (`st.bar_chart`/`st.line_chart` when there's 1 dimension + 1 numeric column), and an expander with **generated SQL, retrieved tables, attempts and timings**.
- Buttons: "Export to Power BI (CSV)" and "Download CSV".
- Sidebar: DB tables list, a "Re-index schema" button, and example questions.

---

## 13. Testing (`pytest`)
- `test_sql_validator.py`: valid SELECTs pass; all malicious cases fail; LIMIT gets enforced.
- `test_retriever.py`: "revenue by category" retrieves `order_items` + `products`; FK expansion adds `orders` when needed.
- `test_intent.py`: the rule-based pre-filter catches write intents (LLM mocked).
- `test_pipeline_e2e.py`: mock the LLM client to return a fixed SQL and assert the whole pipeline returns rows; a self-correction test where the first SQL is invalid and the second is valid.
- An **evaluation script** `scripts/evaluate.py`: 25 gold question→expected-result pairs. Run each generated SQL and compare its result set with the gold SQL's result (execution accuracy). Print the accuracy %.

---

## 14. Build Order (follow step by step)
1. Project setup, `requirements.txt`, `config.py`, `.env.example`.
2. `seed_database.py` → create `retail.db`.
3. Read-only connection + schema extractor.
4. `sql_validator.py` + its tests (security first).
5. ChromaDB vector store, schema documents, `index_schema.py`, retriever + tests.
6. Gemini client wrapper (retries, timeout, JSON parsing) + prompts.
7. Intent classifier → SQL generator → executor → self-correction → insight.
8. Orchestrator + query log + cache.
9. Streamlit UI.
10. Power BI exports, `export_kpis.py`, `README_PowerBI.md`.
11. Evaluation script, README with a Mermaid architecture diagram, setup steps and sample questions.

---

## 15. Definition of Done
- `pip install -r requirements.txt && python scripts/seed_database.py && python scripts/index_schema.py && streamlit run app/streamlit_app.py` works on Windows with only Python installed and a Gemini API key.
- Questions like "monthly revenue trend for 2024", "top 10 customers by spend in Maharashtra" and "return rate by category" return correct results.
- "Delete all orders" and prompt-injection attempts are refused, and no write ever reaches the DB.
- The exported CSVs load in Power BI and the two report pages work.
- `pytest` passes, and the evaluation script shows ≥ 80% execution accuracy on the gold set.

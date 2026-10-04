# QueryPilot – Technical Interview Preparation Guide

This document is your comprehensive cheat-sheet and technical walkthrough for interviewing on **QueryPilot**. It explains every architectural decision, security guardrail, prompt engineering technique, and data pipeline flow in clear, simple language.

---

## 1. Executive Summary & Problem Statement

### What is QueryPilot?
QueryPilot is an enterprise-grade Natural Language Analytics engine that allows non-technical business stakeholders (product managers, operations leads, executives) to ask complex data questions in conversational English and receive verified SQL queries, interactive visual dashboards, and factual business summaries in milliseconds.

### Why not just use LangChain, LlamaIndex, or cloud solutions?
- **Explainability & Control:** In enterprise data settings, black-box agent frameworks frequently hallucinate table schemas, execute untested queries, or leak sensitive columns. Hand-crafting the RAG pipeline guarantees 100% explainability during code review and technical interviews.
- **Security & Zero Data Leaks:** Analytics queries run against an air-gapped, strictly read-only database. No write, alter, or drop statement can ever execute.
- **Portability:** Built entirely on Python, SQLite, local ChromaDB embeddings (no third-party embedding API costs), and Google Gemini.

---

## 2. The Full Pipeline Flow

When a user submits a query like *"What were the top 10 customers by spend in Maharashtra?"*, the request flows through 10 distinct stages:

```
[ User Question ]
       │
       ▼
1. Intent Classification ──( Destructive / Injection )──► [ ⛔ Refusal Response ]
       │                                                      (e.g., "delete all orders")
       ▼ (DATA_QUERY)
2. Schema-Aware RAG (ChromaDB) ──► Top-K Relevant Tables
       │
       ▼
3. Foreign Key Graph Expansion ──► 1-Hop BFS Table Bridging
       │
       ▼
4. Prompt Engineering ──► Dialect Rules + Formulas + Few-Shot Examples + Schema Context
       │
       ▼
5. Google Gemini API ──► Structured JSON with Generated SQL & Explanation
       │
       ▼
6. SQL AST Validator (sqlglot) ──( Error )──► 7. Self-Correction Loop (Max 2 Retries)
       │ (Passed)                                     │ (Fixes query & retries)
       ▼                                              ▲
8. Read-Only SQLite Engine ──────( Execution Error )──┘
       │ (Results DataFrame)
       ▼
9. Insight Generator ──► 2-3 Sentence Factual Business Summary
       │
       ▼
10. UI & Power BI Export ──► Streamlit Table + Charts + CSV Export + App Log DB
```

---

## 3. How Schema-Aware RAG Works with ChromaDB

### The Challenge of Large Schemas:
Passing all tables and columns into every prompt wastes LLM context window tokens, increases latency, and confuses the model when schemas grow to dozens or hundreds of tables.

### The 3-Tier Retrieval Strategy:
1. **Rich Semantic Schema Documents (`schema_documents.py`):**
   - Each database table is converted into a rich markdown document.
   - Crucially, it includes **business synonyms** (e.g. *orders* has synonyms *purchases, transactions, sales volume*; *order_items* has synonyms *revenue, GMV, discounts*).
   - Low-cardinality categorical values are pre-sampled (e.g., `status: ['delivered', 'shipped', 'cancelled']`, `state: ['Maharashtra', 'Karnataka']`).
2. **Vector Similarity Search (`vector_store.py`):**
   - Documents are embedded into a persistent ChromaDB collection using local MiniLM embeddings (ONNX-powered, zero external network calls).
   - Top-k tables (default $k=4$) are retrieved based on cosine distance.
3. **Keyword Fallback & Idempotency:**
   - If a business word (like "revenue" or "customer") appears literally in the prompt, a deterministic fallback ensures those tables are included.
   - A SHA-256 hash of the SQLite catalog is tracked; the vector store automatically re-indexes if and only if the schema changes.

### 1-Hop Foreign Key Graph Expansion (`retriever.py`):
- **Problem:** If a user asks *"Top customers by spend"*, the vector store might retrieve `customers` and `order_items` (because "spend" matches items and "customers" matches customers). However, `customers` has no foreign key to `order_items`! They can only be joined through `orders`.
- **Solution:** QueryPilot models the database schema as an undirected graph. If retrieved tables are disconnected, a Breadth-First Search (BFS) explores 1 hop to find common bridging tables and adds `orders` to the context.

---

## 4. Prompt Engineering Architecture

All prompts are version-controlled in `querypilot/llm/prompts.py`. The SQL generation prompt uses industry best practices:

1. **Role Conditioning:** Defines the LLM strictly as an expert SQLite analyst that outputs a single read-only `SELECT` statement.
2. **Dialect Specificity:** Explicitly instructs SQLite rules—use `strftime('%Y-%m', date)` for months, use `LIKE` (since `ILIKE` is not native to SQLite), and use `ROUND(..., 2)`.
3. **Canonical Business Metric Definitions:**
   - $\text{Revenue} = \sum(\text{quantity} \times \text{unit\_price} \times (1 - \text{discount}))$
   - $\text{Return Rate} = 100 \times \frac{\text{Count}(\text{distinct returns})}{\text{NullIf}(\text{Count}(\text{distinct sold items}), 0)}$
4. **Few-Shot In-Context Examples:** 4 curated question-SQL pairs demonstrating multi-table joins, date aggregation, group-by ranking, and percentage formulas.
5. **Sensitive Column Exclusion:** Injected dynamic blacklist `{sensitive_columns}` forbidding access to salary or email.
6. **Enforced JSON Output:** Uses Gemini's JSON mode (`response_mime_type="application/json"`) with a strict schema `{"sql": "...", "explanation": "...", "tables_used": [...]}` to eliminate parsing failures.

---

## 5. Defense-in-Depth Read-Only SQL Guardrails

QueryPilot implements **7 independent layers of security**. Even if a malicious prompt bypasses the LLM, the query is blocked before touching data.

| Layer | Component | Mechanism |
|---|---|---|
| **Layer 1** | Intent Regex Pre-Filter | Regex catches `delete`, `drop`, `update`, `insert`, `alter`, `truncate` and prompt injection strings before any LLM call. |
| **Layer 2** | LLM Intent Classification | Gemini classifies questions into `DATA_QUERY`, `WRITE_OR_HARMFUL`, `SCHEMA_QUESTION`, etc. |
| **Layer 3** | sqlglot AST Parser | Parses query into SQLite Abstract Syntax Tree. Multiple statements (`;`) are rejected immediately. |
| **Layer 4** | Node Whitelisting | Rejects AST nodes of type `Insert`, `Update`, `Delete`, `Drop`, `Alter`, `Create`, `Pragma`, `Command`, `Attach`, `Vacuum`. |
| **Layer 5** | Schema & Sensitive Column Masking | Every table must exist in `retail.db`. Column references to `salary` or `email`, as well as `SELECT *` on tables with sensitive columns, are blocked. |
| **Layer 6** | Mandatory LIMIT Guardrail | If `LIMIT` is absent, QueryPilot injects `LIMIT 100`. If `LIMIT > 1000`, it caps it to `LIMIT 1000`. |
| **Layer 7** | Operating System / Engine Level | SQLite is opened in **URI read-only mode** (`file:...db?mode=ro`) with `PRAGMA query_only = ON;`. A 5-second `progress_handler` aborts runaway queries. |

---

## 6. The Self-Correction Loop

- **When it triggers:** If the generated SQL fails either during **AST validation** (e.g. invalid table or missing alias) or during **SQLite execution** (e.g. `no such column`, type mismatch, or syntax error).
- **How it works:**
  1. The system captures the failed SQL, exact error message, user question, and schema context.
  2. It formats `SELF_CORRECT_PROMPT_V1` and asks Gemini to analyze the error and output a corrected query.
  3. The corrected query goes back through the SQL Validator and Executor.
  4. QueryPilot allows a **maximum of 2 retry attempts** (total 3 attempts).
  5. If all retries fail, it gracefully reports the exact attempt history and error without crashing.

---

## 7. How Evaluation Accuracy is Measured

Instead of comparing raw SQL strings (which is flawed because multiple different SQL queries can be equally valid), QueryPilot tests **Execution Accuracy**:

1. **Gold Benchmark Suite (`scripts/evaluate.py`):** 25 curated business questions with human-verified "gold" SQLite queries.
2. **Ground Truth Comparison:**
   - Both the generated SQL and gold SQL are executed against `retail.db`.
   - The result DataFrames are compared:
     - Dimension keys must match (e.g. top categories, month names, customer IDs).
     - Numeric metrics (revenue, order counts) are verified within a 1% floating-point tolerance ($\text{rel\_tol} = 0.01$).
     - Overlap ratio must be $\ge 80\%$ for top-k ranking queries.
3. **Definition of Done:** Benchmarks require $\ge 80\%$ execution accuracy.

---

## 8. Power BI Integration Flow

```
[ QueryPilot Streamlit / CLI ]
       │
       ▼ (pandas.DataFrame.to_csv)
  data/exports/
    ├── 20261004_120000_monthly_revenue.csv  (Timestamped audit trail)
    ├── latest_monthly_revenue.csv          (Fixed name for Power BI)
    ├── category_revenue.csv
    ├── region_orders.csv
    ├── top_customers.csv
    └── query_log.csv                       (Exported from data/app_log.db)
       │
       ▼ (Get Data -> Folder)
[ Power BI Desktop ]
    ├── Sales Overview Page (Revenue, Orders, AOV, Monthly Trend, Category Bar)
    └── QueryPilot Usage Page (Daily Queries, Latency, Success Rate, Table Usage)
```

1. **Dual Exporting:** Every export generates a timestamped file for historical versioning and a `latest_<slug>.csv` file.
2. **Seamless Refresh:** Power BI reports link to the `latest_*.csv` files. When new data is exported, clicking **Refresh** in Power BI immediately updates all visuals.
3. **Engine Telemetry:** `data/app_log.db` maintains an audit trail of every query, latency, intent, and success status, exported directly to `query_log.csv` for BI observability.

---

## 9. Top Interview Questions & Sample Answers

### Q1: "Why not use LangChain's SQLDatabaseChain?"
> *"LangChain's SQL chain is a quick prototyping wrapper, but for enterprise analytics it introduces high risk: it's hard to customize SQL dialect rules, lacks fine-grained AST inspection with sqlglot, doesn't enforce read-only URI connections at the driver level, and doesn't handle graph-based FK expansion when schemas get large. By implementing the RAG and validation pipeline by hand, every layer is testable, auditable, and modular."*

### Q2: "How do you prevent SQL injection if a user asks to drop tables?"
> *"We use defense-in-depth across 7 layers. First, a regex pre-filter catches dangerous keywords before calling the LLM. Second, the LLM classifies intent. Third, `sqlglot` parses the AST and rejects non-SELECT or multiple statements. Fourth, our table whitelist blocks arbitrary tables. Fifth, SQLite is opened in read-only mode (`?mode=ro`) with `PRAGMA query_only = ON`. Even if a raw `DROP TABLE` reached SQLite, the C-level engine aborts with `OperationalError: attempt to write a readonly database`."*

### Q3: "What happens when a question requires multiple tables that the vector store didn't retrieve together?"
> *"We built an undirected Foreign Key Graph on top of the SQLite catalog. After vector search and keyword fallback retrieve initial tables, our 1-hop BFS expansion inspects relationships. If `customers` and `order_items` are retrieved, BFS recognizes that `orders` is the necessary bridging table and automatically injects it into the LLM prompt context."*

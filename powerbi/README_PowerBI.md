# Power BI Reporting Guide for QueryPilot

This guide explains how to connect **Power BI Desktop** to QueryPilot's exported datasets and build an executive analytics dashboard.

---

## 1. Overview of Data Exports

QueryPilot exports analytics datasets to `data/exports/` in CSV format. These files are produced either by running `python scripts/export_kpis.py` or by clicking **"Export to Power BI (CSV)"** directly in the Streamlit UI.

| File | Purpose | Key Metrics / Columns |
|---|---|---|
| `monthly_revenue.csv` | Monthly financial trends | `month`, `total_revenue`, `total_orders`, `average_order_value` |
| `category_revenue.csv` | Category sales performance | `category`, `total_revenue`, `total_units_sold`, `total_orders` |
| `region_orders.csv` | Geographic order breakdown | `region`, `total_orders`, `total_revenue`, `unique_customers` |
| `top_customers.csv` | Customer spend ranking | `customer_id`, `name`, `city`, `state`, `segment`, `total_spend` |
| `query_log.csv` | QueryPilot engine observability | `timestamp`, `question`, `intent`, `row_count`, `execution_ms`, `success` |

---

## 2. Connecting Power BI to the Exports Folder

### Method A: Folder Connector (Recommended)
1. Open **Power BI Desktop**.
2. Click **Get Data** → **More...** → **Folder** → Click **Connect**.
3. Enter the absolute path to your `data/exports` folder (e.g., `C:\Projects\querypilot\data\exports`).
4. Click **OK** → Click **Transform Data** (Power Query Editor opens).
5. In Power Query, filter `[Extension]` to `.csv` and filter `[Name]` to the base files (`monthly_revenue.csv`, `category_revenue.csv`, `region_orders.csv`, `top_customers.csv`, `query_log.csv`).
6. Click the **Combine Files** icon next to the `Content` column, or right-click each CSV file and click **Reference** to create separate tables.

### Method B: Direct CSV Connector (Fastest)
1. In Power BI Desktop, click **Get Data** → **Text/CSV**.
2. Select `monthly_revenue.csv` and click **Load**.
3. Repeat for `category_revenue.csv`, `region_orders.csv`, and `query_log.csv`.

---

## 3. Building Dashboard Pages

### Page 1: "Sales Overview"
This dashboard visualizes retail sales KPIs and performance trends.

1. **Top KPI Cards (Header):**
   - **Card 1 - Total Revenue:** Field = `monthly_revenue[total_revenue]` (Sum). Format as Currency (`$#,##0` or `₹#,##0`).
   - **Card 2 - Total Orders:** Field = `monthly_revenue[total_orders]` (Sum).
   - **Card 3 - Average Order Value (AOV):** Field = `monthly_revenue[average_order_value]` (Average).
2. **Monthly Revenue Trend (Line Chart):**
   - **X-axis:** `monthly_revenue[month]` (Sorted ascending).
   - **Y-axis:** `monthly_revenue[total_revenue]`.
   - **Secondary Y-axis:** `monthly_revenue[total_orders]` (Line).
3. **Revenue by Category (Horizontal Clustered Bar Chart):**
   - **Y-axis:** `category_revenue[category]` (Sorted descending by revenue).
   - **X-axis:** `category_revenue[total_revenue]`.
4. **Geographic Slicer:**
   - **Slicer Visual:** Field = `region_orders[region]`. Style = Tile / Buttons.

---

### Page 2: "QueryPilot Usage & LLM Observability"
This page monitors how users interact with QueryPilot, query latency, and safety guardrails.

1. **Top Operational Cards:**
   - **Total Queries Asked:** Field = `query_log[id]` (Count).
   - **Query Success Rate:** Measure = `DIVIDE(CALCULATE(COUNT(query_log[id]), query_log[success] = 1), COUNT(query_log[id]))` (Format as %).
   - **Average Engine Latency:** Field = `query_log[execution_ms]` (Average, rounded to 1 decimal).
2. **Queries by Day / Month (Column Chart):**
   - **X-axis:** `query_log[timestamp]` (Date hierarchy).
   - **Y-axis:** Count of queries.
   - **Legend:** `query_log[intent]`.
3. **Most-Queried Database Tables (Bar Chart):**
   - Derived from `query_log[retrieved_tables]`.
4. **Recent Queries Audit Log (Table Visual):**
   - Fields: `timestamp`, `question`, `intent`, `row_count`, `execution_ms`, `success`.

---

## 4. Keeping Reports Up to Date

1. As you or business users ask questions in the Streamlit app and click **Export to Power BI**, the export folder is automatically updated.
2. In Power BI Desktop, simply click the **Refresh** button on the Home ribbon to pull in all newly exported data and query logs.

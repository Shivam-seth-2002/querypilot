"""Export pre-built business KPI datasets and query logs for Power BI reporting."""

import sys
from pathlib import Path
import pandas as pd

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from querypilot.config import settings
from querypilot.db.connection import get_readonly_connection
from querypilot.export.powerbi_export import PowerBIExporter

KPI_QUERIES = {
    "monthly_revenue": """
        SELECT
            strftime('%Y-%m', o.order_date) AS month,
            ROUND(SUM(oi.quantity * oi.unit_price * (1.0 - oi.discount)), 2) AS total_revenue,
            COUNT(DISTINCT o.order_id) AS total_orders,
            ROUND(SUM(oi.quantity * oi.unit_price * (1.0 - oi.discount)) / COUNT(DISTINCT o.order_id), 2) AS average_order_value
        FROM orders o
        JOIN order_items oi ON o.order_id = oi.order_id
        GROUP BY month
        ORDER BY month ASC
    """,
    "category_revenue": """
        SELECT
            p.category,
            ROUND(SUM(oi.quantity * oi.unit_price * (1.0 - oi.discount)), 2) AS total_revenue,
            SUM(oi.quantity) AS total_units_sold,
            COUNT(DISTINCT oi.order_id) AS total_orders
        FROM products p
        JOIN order_items oi ON p.product_id = oi.product_id
        GROUP BY p.category
        ORDER BY total_revenue DESC
    """,
    "region_orders": """
        SELECT
            o.region,
            COUNT(DISTINCT o.order_id) AS total_orders,
            ROUND(SUM(oi.quantity * oi.unit_price * (1.0 - oi.discount)), 2) AS total_revenue,
            COUNT(DISTINCT o.customer_id) AS unique_customers
        FROM orders o
        JOIN order_items oi ON o.order_id = oi.order_id
        GROUP BY o.region
        ORDER BY total_revenue DESC
    """,
    "top_customers": """
        SELECT
            c.customer_id,
            c.name,
            c.city,
            c.state,
            c.segment,
            COUNT(DISTINCT o.order_id) AS total_orders,
            ROUND(SUM(oi.quantity * oi.unit_price * (1.0 - oi.discount)), 2) AS total_spend
        FROM customers c
        JOIN orders o ON c.customer_id = o.customer_id
        JOIN order_items oi ON o.order_id = oi.order_id
        GROUP BY c.customer_id, c.name, c.city, c.state, c.segment
        ORDER BY total_spend DESC
        LIMIT 100
    """,
}


def export_all_kpis():
    """Execute standard analytic queries and output CSV files for Power BI."""
    exports_dir = Path(settings.exports_path)
    exports_dir.mkdir(parents=True, exist_ok=True)
    exporter = PowerBIExporter(exports_dir=str(exports_dir))

    conn = get_readonly_connection(settings.db_path)
    print(f"Exporting KPI datasets to {exports_dir}...")
    try:
        for name, sql in KPI_QUERIES.items():
            df = pd.read_sql_query(sql, conn)
            # Write base named CSV for straightforward Power BI table loading
            output_file = exports_dir / f"{name}.csv"
            df.to_csv(output_file, index=False, encoding="utf-8")
            # Also write timestamped and latest files
            ts_path, latest_path = exporter.export_dataframe(df, name)
            print(f"  [+] {name}.csv ({len(df)} rows)")

        # Export operational query log
        log_file = exporter.export_query_log()
        print(f"  [+] query_log.csv (from {settings.app_log_db_path})")

        print("\nAll Power BI exports generated successfully!")
    finally:
        conn.close()


if __name__ == "__main__":
    export_all_kpis()

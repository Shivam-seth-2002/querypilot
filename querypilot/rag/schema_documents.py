"""Build rich, annotated schema documents for vector embedding and retrieval."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from querypilot.db.schema_extractor import DatabaseSchema, TableInfo


class SchemaDocument(BaseModel):
    """Rich text document representing a database table for vector search."""
    table_name: str
    doc_id: str
    content: str
    columns: List[str] = Field(default_factory=list)
    relationships: List[str] = Field(default_factory=list)
    synonyms: List[str] = Field(default_factory=list)


TABLE_ANNOTATIONS: Dict[str, Dict[str, Any]] = {
    "customers": {
        "description": "Customer demographic and account details including geographic location (city, state), signup date, and customer segment.",
        "synonyms": ["users", "buyers", "clients", "shoppers", "accounts", "consumers", "patrons", "geography", "state", "city", "churn"],
        "usage": "Use when filtering or grouping by customer name, state (e.g. Maharashtra, Karnataka), city, customer segment, or computing customer lifetime spend.",
    },
    "products": {
        "description": "Product catalog containing item name, category, sub-category, brand, retail unit price, and cost price.",
        "synonyms": ["items", "catalog", "merchandise", "goods", "sku", "brand", "category", "subcategory", "pricing", "electronics", "clothing", "beauty", "books"],
        "usage": "Use when analyzing sales, pricing, or product returns by category, sub-category, brand, or individual product name.",
    },
    "orders": {
        "description": "Customer order transactions with order date, delivery/fulfillment status, payment method, and sales region.",
        "synonyms": ["purchases", "transactions", "sales orders", "order history", "order volume", "payment mode", "region", "delivery"],
        "usage": "Use for order counts, order dates, monthly/yearly sales trends (e.g. 2024), order fulfillment status, payment methods, and regional analysis.",
    },
    "order_items": {
        "description": "Order line item details including quantity ordered, unit price, and discount percentage.",
        "synonyms": ["order details", "line items", "item sales", "basket items", "cart items", "quantities", "discounts", "revenue", "sales volume", "gross merchandise value", "gmv"],
        "usage": "CRITICAL: Use to calculate revenue = SUM(order_items.quantity * order_items.unit_price * (1 - order_items.discount)). Bridges orders to products.",
    },
    "returns": {
        "description": "Product returns and refund transactions with return date, return reason, and refunded amount.",
        "synonyms": ["refunds", "returned orders", "product returns", "return rate", "reverse logistics", "item defects", "customer returns"],
        "usage": "Use for calculating return rates, return reasons, and total refund amounts by product, category, or order.",
    },
    "warehouses": {
        "description": "Storage warehouses and regional fulfillment centers with city location and unit capacity.",
        "synonyms": ["fulfillment centers", "distribution centers", "storage hubs", "facilities", "depots", "storage capacity"],
        "usage": "Use for warehouse locations, storage capacities, and fulfillment logistics.",
    },
    "inventory": {
        "description": "Current on-hand stock quantities and last restock dates for products across warehouses.",
        "synonyms": ["stock", "stock levels", "inventory counts", "on-hand quantity", "supply", "availability", "reorder", "restock"],
        "usage": "Use for checking stock availability, low-stock warnings, and warehouse restocking dates.",
    },
    "marketing_campaigns": {
        "description": "Marketing promotions, advertising channels (Google Ads, Instagram, YouTube, etc.), campaign durations, and budgets.",
        "synonyms": ["ads", "advertising", "campaigns", "promotions", "marketing spend", "channels", "ad budget", "digital marketing"],
        "usage": "Use for advertising spend, campaign schedules, and marketing channel budget analysis.",
    },
    "employees": {
        "description": "Internal staff and workforce directory with employee roles, sales regions, and hire dates.",
        "synonyms": ["staff", "workforce", "sales representatives", "team", "personnel", "workers", "headcount", "hiring"],
        "usage": "Use for workforce headcount, roles, and regional sales staffing. NOTE: salary is confidential/sensitive and cannot be queried.",
    },
}


def build_table_document(table_info: TableInfo) -> SchemaDocument:
    """Format a TableInfo instance into a rich text document for embedding."""
    tbl = table_info.table_name
    annotation = TABLE_ANNOTATIONS.get(tbl, {
        "description": f"Table storing {tbl} records.",
        "synonyms": [tbl],
        "usage": f"Query {tbl} for related business data.",
    })

    # Columns with PK, FK, type, and sample values
    col_lines: List[str] = []
    for col in table_info.columns:
        extras = []
        if col.is_pk:
            extras.append("PK")
        if col.name.endswith("_id") and not col.is_pk:
            extras.append("FK")
        if col.sample_values:
            samples_str = ", ".join(f"'{v}'" for v in col.sample_values[:3])
            extras.append(f"samples: [{samples_str}]")

        extra_str = f" ({', '.join(extras)})" if extras else ""
        col_lines.append(f"  - {col.name} ({col.data_type}{extra_str})")

    # Relationships
    rel_lines: List[str] = []
    for fk in table_info.foreign_keys:
        rel_lines.append(f"{tbl}.{fk.from_column} = {fk.to_table}.{fk.to_column}")

    synonyms = annotation["synonyms"]

    doc_text = f"""TABLE: {tbl}
DESCRIPTION: {annotation['description']}
ROW COUNT: {table_info.row_count:,}
COLUMNS:
{chr(10).join(col_lines)}
RELATIONSHIPS: {'; '.join(rel_lines) if rel_lines else 'None'}
SYNONYMS: {', '.join(synonyms)}
USAGE HINT: {annotation['usage']}
"""

    return SchemaDocument(
        table_name=tbl,
        doc_id=f"table::{tbl}",
        content=doc_text.strip(),
        columns=table_info.column_names,
        relationships=rel_lines,
        synonyms=synonyms,
    )


def build_all_schema_documents(schema: DatabaseSchema) -> List[SchemaDocument]:
    """Build schema documents for all tables in the database schema."""
    return [build_table_document(t_info) for t_info in schema.tables.values()]

"""Tests for schema-aware RAG retriever and FK graph expansion."""

import pytest
from querypilot.rag.retriever import SchemaRetriever


@pytest.fixture(scope="module")
def retriever():
    return SchemaRetriever()


def test_revenue_by_category_retrieves_order_items_and_products(retriever):
    result = retriever.retrieve("revenue by category")
    assert "order_items" in result.tables
    assert "products" in result.tables


def test_monthly_revenue_trend_retrieves_orders_and_order_items(retriever):
    result = retriever.retrieve("monthly revenue trend for 2024")
    assert "orders" in result.tables
    assert "order_items" in result.tables


def test_fk_expansion_bridges_customers_and_order_items(retriever):
    # If customers and order_items are queried, orders must be present to allow SQL JOIN
    result = retriever.retrieve("top 10 customers by spend in Maharashtra")
    assert "customers" in result.tables
    assert "order_items" in result.tables
    assert "orders" in result.tables


def test_return_rate_by_category_retrieves_returns_and_products(retriever):
    result = retriever.retrieve("return rate by category")
    assert "returns" in result.tables
    assert "products" in result.tables


def test_direct_fk_expansion_method(retriever):
    # Direct test on _expand_foreign_keys
    initial = {"customers", "order_items"}
    expanded = retriever._expand_foreign_keys(initial)
    assert "orders" in expanded


def test_keyword_fallback(retriever):
    keywords = retriever._keyword_fallback("Show warehouse inventory and capacity")
    assert "warehouses" in keywords or "inventory" in keywords

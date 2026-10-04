"""Tests for QueryPilotOrchestrator, query logging, and caching."""

from unittest.mock import MagicMock, patch
import pytest

from querypilot.llm.client import GeminiClient
from querypilot.models import IntentType
from querypilot.pipeline.orchestrator import QueryPilotOrchestrator, normalize_question
from querypilot.rag.retriever import RetrievedSchema


@pytest.fixture
def mock_llm():
    client = MagicMock(spec=GeminiClient)
    client.generate_json.side_effect = [
        # Call 1: Intent classification
        {
            "intent": "DATA_QUERY",
            "confidence": 0.95,
            "entities": {"metric": "revenue", "dimension": "category"},
        },
        # Call 2: SQL generator
        {
            "sql": "SELECT p.category, ROUND(SUM(oi.quantity * oi.unit_price * (1 - oi.discount)), 2) AS revenue FROM products p JOIN order_items oi ON p.product_id = oi.product_id GROUP BY p.category ORDER BY revenue DESC LIMIT 5",
            "explanation": "Category revenue breakdown",
            "tables_used": ["products", "order_items"],
        },
    ]
    client.generate.return_value = "Electronics and Clothing generate the highest revenue."
    return client


def test_orchestrator_refuses_destructive_request():
    orchestrator = QueryPilotOrchestrator(enable_cache=True)
    res = orchestrator.execute("delete all orders")
    assert res.success is False
    assert res.intent == IntentType.WRITE_OR_HARMFUL.value
    assert "refused" in res.insight.lower() or "prohibited" in res.insight.lower()


def test_orchestrator_handles_schema_question():
    orchestrator = QueryPilotOrchestrator(enable_cache=True)
    res = orchestrator.execute("what tables are available?")
    assert res.success is True
    assert res.intent == IntentType.SCHEMA_QUESTION.value
    assert len(res.retrieved_tables) == 9
    assert "customers" in res.retrieved_tables


def test_orchestrator_data_query_flow(mock_llm):
    orchestrator = QueryPilotOrchestrator(llm_client=mock_llm, enable_cache=True)
    res = orchestrator.execute("top categories by revenue")

    assert res.success is True
    assert res.row_count > 0
    assert "category" in res.columns
    assert "revenue" in res.columns
    assert len(res.rows) > 0
    assert res.timings.total_ms > 0
    assert "products" in res.retrieved_tables
    assert "order_items" in res.retrieved_tables


def test_orchestrator_cache_hit(mock_llm):
    orchestrator = QueryPilotOrchestrator(llm_client=mock_llm, enable_cache=True)
    q = "top categories by revenue"
    res1 = orchestrator.execute(q)

    # Second call should hit in-memory cache and not make LLM calls
    res2 = orchestrator.execute("Top Categories By Revenue?")
    assert res2.success is True
    assert "cache" in res2.explanation.lower()
    assert res2.rows == res1.rows

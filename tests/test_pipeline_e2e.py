"""End-to-end and component tests for query execution, self-correction, and insights."""

from unittest.mock import MagicMock
import pytest

from querypilot.llm.client import GeminiClient
from querypilot.pipeline.executor import SQLExecutor
from querypilot.pipeline.insight import InsightGenerator
from querypilot.pipeline.self_correct import SelfCorrector
from querypilot.pipeline.sql_validator import SQLValidator
from querypilot.rag.retriever import RetrievedSchema


@pytest.fixture
def executor():
    return SQLExecutor()


@pytest.fixture
def dummy_retrieved_schema():
    return RetrievedSchema(
        tables=["customers", "orders"],
        context_text="TABLE: customers (customer_id PK, name, city, state)\nTABLE: orders (order_id PK, customer_id FK, order_date)",
    )


def test_executor_successful_query(executor):
    sql = "SELECT customer_id, name, city, state FROM customers LIMIT 5"
    res = executor.run(sql)
    assert res.success is True
    assert res.row_count == 5
    assert len(res.rows) == 5
    assert res.columns == ["customer_id", "name", "city", "state"]
    assert res.execution_ms >= 0


def test_executor_prevents_write(executor):
    sql = "DELETE FROM customers WHERE customer_id = 1"
    res = executor.run(sql)
    assert res.success is False
    assert "readonly" in res.error.lower() or "attempt to write" in res.error.lower()


def test_self_correction_recovers_from_invalid_sql(executor, dummy_retrieved_schema):
    mock_llm = MagicMock(spec=GeminiClient)
    # The fix returns a valid SQL
    mock_llm.generate_json.return_value = {
        "sql": "SELECT customer_id, name FROM customers LIMIT 3",
        "explanation": "Fixed non-existent column error",
        "tables_used": ["customers"],
    }

    corrector = SelfCorrector(
        llm_client=mock_llm,
        validator=SQLValidator(),
        executor=executor,
        max_retries=2,
    )

    # Initial SQL references invalid column
    bad_sql = "SELECT invalid_column_xyz FROM customers"
    initial_error = "no such column: invalid_column_xyz"

    result = corrector.correct_and_execute(
        question="Show me 3 customers",
        failed_sql=bad_sql,
        initial_error=initial_error,
        retrieved_schema=dummy_retrieved_schema,
    )

    assert result.success is True
    assert result.attempts == 2
    assert len(result.attempt_history) == 2
    assert result.execution_result.row_count == 3


def test_insight_generator_fallback():
    generator = InsightGenerator(llm_client=None)
    columns = ["month", "monthly_revenue"]
    rows = [["2024-01", 154000.50], ["2024-02", 168200.00]]
    insight = generator.generate(
        question="monthly revenue trend",
        sql="SELECT ...",
        columns=columns,
        rows=rows,
        row_count=2,
    )
    assert "2024-01" in insight or "records" in insight

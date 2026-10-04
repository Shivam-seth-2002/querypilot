"""Orchestrator tying together intent classification, RAG, SQL generation, validation, execution, and logging."""

from datetime import datetime, timezone
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from querypilot.config import settings
from querypilot.db.connection import get_app_log_connection
from querypilot.llm.client import GeminiClient
from querypilot.models import IntentType, QueryResult, Timings
from querypilot.pipeline.executor import SQLExecutor
from querypilot.pipeline.insight import InsightGenerator
from querypilot.pipeline.intent import IntentClassifier
from querypilot.pipeline.self_correct import SelfCorrector
from querypilot.pipeline.sql_validator import SQLValidator
from querypilot.rag.retriever import SchemaRetriever

logger = logging.getLogger(__name__)


def normalize_question(q: str) -> str:
    """Normalize query text for deterministic in-memory caching."""
    clean = q.strip().lower().rstrip("?.,!")
    return re.sub(r"\s+", " ", clean)


class QueryPilotOrchestrator:
    """Main pipeline orchestrator coordinates the NL-to-SQL RAG lifecycle."""

    def __init__(
        self,
        retriever: Optional[SchemaRetriever] = None,
        llm_client: Optional[GeminiClient] = None,
        validator: Optional[SQLValidator] = None,
        executor: Optional[SQLExecutor] = None,
        enable_cache: bool = True,
    ):
        self.llm_client = llm_client or GeminiClient()
        self.retriever = retriever or SchemaRetriever()
        self.validator = validator or SQLValidator()
        self.executor = executor or SQLExecutor()
        self.intent_classifier = IntentClassifier(llm_client=self.llm_client)
        self.self_corrector = SelfCorrector(
            llm_client=self.llm_client,
            validator=self.validator,
            executor=self.executor,
            max_retries=2,
        )
        self.insight_generator = InsightGenerator(llm_client=self.llm_client)
        self.enable_cache = enable_cache
        self._cache: Dict[str, QueryResult] = {}

    def log_query(
        self,
        question: str,
        intent: str,
        retrieved_tables: List[str],
        sql: Optional[str],
        row_count: int,
        execution_ms: float,
        success: bool,
        error: Optional[str] = None,
    ) -> None:
        """Log pipeline execution metadata to separate application database."""
        try:
            conn = get_app_log_connection()
            try:
                conn.execute(
                    """
                    INSERT INTO query_log (
                        timestamp, question, intent, retrieved_tables, sql,
                        row_count, execution_ms, success, error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        datetime.now(timezone.utc).isoformat(),
                        question,
                        intent,
                        json.dumps(retrieved_tables),
                        sql or "",
                        row_count,
                        execution_ms,
                        1 if success else 0,
                        error or "",
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"Failed to record query log in app_log.db: {e}")

    def execute(self, question: str) -> QueryResult:
        """Execute the complete natural language analytics workflow."""
        start_pipeline = time.perf_counter()
        normalized_q = normalize_question(question)

        # 1. Check in-memory cache
        if self.enable_cache and normalized_q in self._cache:
            cached_result = self._cache[normalized_q].model_copy(deep=True)
            cached_result.explanation = (cached_result.explanation or "") + " (from cache)"
            return cached_result

        timings = Timings()

        # 2. Intent Classification
        t0 = time.perf_counter()
        intent_res = self.intent_classifier.classify(question)
        timings.intent_ms = round((time.perf_counter() - t0) * 1000, 2)

        # Handle non-DATA_QUERY intents directly
        if intent_res.intent == IntentType.WRITE_OR_HARMFUL:
            clarification = (
                intent_res.clarification
                or "Data modifications and malicious queries are strictly prohibited in QueryPilot."
            )
            timings.total_ms = round((time.perf_counter() - start_pipeline) * 1000, 2)
            res = QueryResult(
                question=question,
                intent=intent_res.intent.value,
                insight=f"⛔ Refused: {clarification}",
                explanation=clarification,
                success=False,
                error="Prohibited write or injection attempt",
                timings=timings,
            )
            self.log_query(question, intent_res.intent.value, [], None, 0, 0, False, res.error)
            return res

        if intent_res.intent == IntentType.SCHEMA_QUESTION:
            schema_overview = (
                "QueryPilot connects to a retail analytics database with 9 tables:\n"
                "- customers: Demographics, geographic locations (city, state), segments\n"
                "- products: Catalog, categories, sub-categories, brands, pricing\n"
                "- orders: Order history, dates (2023-2025), fulfillment status, payment modes\n"
                "- order_items: Order line items, quantities, discounts, and revenue data\n"
                "- returns: Customer returns, refund amounts, and return reasons\n"
                "- warehouses: Fulfillment locations and storage capacity\n"
                "- inventory: Stock quantities and restocking dates per warehouse\n"
                "- marketing_campaigns: Ad channels, budgets, and schedules\n"
                "- employees: Sales team, regions, and roles (salaries confidential)"
            )
            timings.total_ms = round((time.perf_counter() - start_pipeline) * 1000, 2)
            res = QueryResult(
                question=question,
                intent=intent_res.intent.value,
                retrieved_tables=list(self.retriever.schema.tables.keys()),
                insight=schema_overview,
                explanation="Schema overview request.",
                success=True,
                timings=timings,
            )
            self.log_query(question, intent_res.intent.value, res.retrieved_tables, None, 0, 0, True, None)
            return res

        if intent_res.intent == IntentType.OUT_OF_SCOPE:
            timings.total_ms = round((time.perf_counter() - start_pipeline) * 1000, 2)
            res = QueryResult(
                question=question,
                intent=intent_res.intent.value,
                insight="Hello! I am QueryPilot, your natural language analytics assistant. Ask me questions about retail revenue, customer orders, top products, or returns.",
                explanation="Out-of-scope query.",
                success=True,
                timings=timings,
            )
            return res

        if intent_res.intent == IntentType.AMBIGUOUS:
            clarification = intent_res.clarification or "Could you please specify the metric or time period you'd like to analyze?"
            timings.total_ms = round((time.perf_counter() - start_pipeline) * 1000, 2)
            return QueryResult(
                question=question,
                intent=intent_res.intent.value,
                insight=f"Clarification needed: {clarification}",
                explanation="Ambiguous query.",
                success=False,
                error=clarification,
                timings=timings,
            )

        # 3. Schema-Aware RAG Retrieval
        t0 = time.perf_counter()
        retrieved_schema = self.retriever.retrieve(question)
        timings.retrieval_ms = round((time.perf_counter() - t0) * 1000, 2)

        # 4. SQL Generation
        t0 = time.perf_counter()
        from querypilot.pipeline.sql_generator import SQLGenerator
        sql_gen = SQLGenerator(llm_client=self.llm_client)
        gen_sql_result = sql_gen.generate(
            question=question,
            retrieved_schema=retrieved_schema,
            entities=intent_res.entities,
        )
        timings.llm_ms = round((time.perf_counter() - t0) * 1000, 2)

        initial_sql = gen_sql_result.sql
        explanation = gen_sql_result.explanation
        attempts = 1
        final_sql = initial_sql
        execution_res = None

        # 5. SQL Validation
        val_res = self.validator.validate(initial_sql)

        if not val_res.is_valid:
            # Trigger self-correction on validation failure
            err_msg = "; ".join(val_res.errors)
            corr_res = self.self_corrector.correct_and_execute(
                question=question,
                failed_sql=initial_sql,
                initial_error=err_msg,
                retrieved_schema=retrieved_schema,
            )
            attempts = corr_res.attempts
            final_sql = corr_res.final_sql
            execution_res = corr_res.execution_result
            if not corr_res.success:
                timings.total_ms = round((time.perf_counter() - start_pipeline) * 1000, 2)
                res = QueryResult(
                    question=question,
                    intent=intent_res.intent.value,
                    retrieved_tables=retrieved_schema.tables,
                    sql=final_sql,
                    explanation=f"Validation failed: {corr_res.error}",
                    attempts=attempts,
                    error=corr_res.error,
                    success=False,
                    timings=timings,
                )
                self.log_query(question, intent_res.intent.value, retrieved_schema.tables, final_sql, 0, 0, False, corr_res.error)
                return res
        else:
            # 6. Execute Validated SQL
            sanitized_sql = val_res.sanitized_sql or initial_sql
            final_sql = sanitized_sql
            t0 = time.perf_counter()
            execution_res = self.executor.run(sanitized_sql)
            timings.exec_ms = execution_res.execution_ms

            if not execution_res.success:
                # Trigger self-correction on execution failure
                corr_res = self.self_corrector.correct_and_execute(
                    question=question,
                    failed_sql=sanitized_sql,
                    initial_error=execution_res.error or "Execution error",
                    retrieved_schema=retrieved_schema,
                )
                attempts = corr_res.attempts
                final_sql = corr_res.final_sql
                execution_res = corr_res.execution_result
                if not corr_res.success:
                    timings.total_ms = round((time.perf_counter() - start_pipeline) * 1000, 2)
                    res = QueryResult(
                        question=question,
                        intent=intent_res.intent.value,
                        retrieved_tables=retrieved_schema.tables,
                        sql=final_sql,
                        explanation=f"Execution failed: {corr_res.error}",
                        attempts=attempts,
                        error=corr_res.error,
                        success=False,
                        timings=timings,
                    )
                    self.log_query(question, intent_res.intent.value, retrieved_schema.tables, final_sql, 0, 0, False, corr_res.error)
                    return res

        # 7. Generate Natural Language Insight
        insight_text = self.insight_generator.generate(
            question=question,
            sql=final_sql,
            columns=execution_res.columns,
            rows=execution_res.rows,
            row_count=execution_res.row_count,
        )

        timings.total_ms = round((time.perf_counter() - start_pipeline) * 1000, 2)

        result = QueryResult(
            question=question,
            intent=intent_res.intent.value,
            retrieved_tables=retrieved_schema.tables,
            sql=final_sql,
            explanation=explanation,
            columns=execution_res.columns,
            rows=execution_res.rows,
            row_count=execution_res.row_count,
            insight=insight_text,
            attempts=attempts,
            timings=timings,
            success=True,
            error=None,
        )

        # Log query to separate database
        self.log_query(
            question=question,
            intent=intent_res.intent.value,
            retrieved_tables=retrieved_schema.tables,
            sql=final_sql,
            row_count=execution_res.row_count,
            execution_ms=timings.exec_ms,
            success=True,
            error=None,
        )

        # Save to cache
        if self.enable_cache:
            self._cache[normalized_q] = result

        return result

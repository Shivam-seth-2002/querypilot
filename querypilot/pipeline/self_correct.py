"""Self-correction loop for automatically fixing invalid or failing SQL queries."""

import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from querypilot.llm.client import GeminiClient
from querypilot.llm.prompts import SELF_CORRECT_PROMPT_V1
from querypilot.pipeline.executor import ExecutionResult, SQLExecutor
from querypilot.pipeline.sql_validator import SQLValidator
from querypilot.rag.retriever import RetrievedSchema

logger = logging.getLogger(__name__)


class AttemptRecord(BaseModel):
    """Record of a single SQL generation / execution attempt."""
    attempt_number: int
    sql: str
    stage: str  # "validation" or "execution"
    error: Optional[str] = None
    success: bool = False


class SelfCorrectionResult(BaseModel):
    """Result of self-correction retry workflow."""
    success: bool
    final_sql: str
    execution_result: Optional[ExecutionResult] = None
    attempts: int = 1
    attempt_history: List[AttemptRecord] = Field(default_factory=list)
    error: Optional[str] = None


class SelfCorrector:
    """Orchestrates query self-correction with up to max_retries retries."""

    def __init__(
        self,
        llm_client: Optional[GeminiClient] = None,
        validator: Optional[SQLValidator] = None,
        executor: Optional[SQLExecutor] = None,
        max_retries: int = 2,
    ):
        self.llm_client = llm_client or GeminiClient()
        self.validator = validator or SQLValidator()
        self.executor = executor or SQLExecutor()
        self.max_retries = max_retries

    def correct_and_execute(
        self,
        question: str,
        failed_sql: str,
        initial_error: str,
        retrieved_schema: RetrievedSchema,
    ) -> SelfCorrectionResult:
        """Attempt to fix failed SQL using Gemini and re-execute (max 2 retries)."""
        history: List[AttemptRecord] = [
            AttemptRecord(
                attempt_number=1,
                sql=failed_sql,
                stage="initial",
                error=initial_error,
                success=False,
            )
        ]

        current_sql = failed_sql
        current_error = initial_error

        for retry in range(1, self.max_retries + 1):
            attempt_num = retry + 1
            logger.info(f"Self-correction retry {retry}/{self.max_retries} for SQL: {current_sql}")

            prompt = SELF_CORRECT_PROMPT_V1.format(
                question=question,
                failed_sql=current_sql,
                error_message=current_error,
                schema_context=retrieved_schema.context_text,
            )

            try:
                response = self.llm_client.generate_json(prompt=prompt, temperature=0.0)
                corrected_sql = response.get("sql", "").strip()
            except Exception as e:
                history.append(
                    AttemptRecord(
                        attempt_number=attempt_num,
                        sql=current_sql,
                        stage="llm_fix_generation",
                        error=f"LLM correction generation failed: {e}",
                        success=False,
                    )
                )
                current_error = str(e)
                continue

            if not corrected_sql:
                history.append(
                    AttemptRecord(
                        attempt_number=attempt_num,
                        sql="",
                        stage="empty_sql",
                        error="LLM returned empty SQL on self-correction",
                        success=False,
                    )
                )
                continue

            current_sql = corrected_sql

            # 1. Validate corrected query
            val_res = self.validator.validate(current_sql)
            if not val_res.is_valid:
                current_error = "; ".join(val_res.errors)
                history.append(
                    AttemptRecord(
                        attempt_number=attempt_num,
                        sql=current_sql,
                        stage="validation",
                        error=current_error,
                        success=False,
                    )
                )
                continue

            # 2. Execute corrected query
            sanitized_sql = val_res.sanitized_sql or current_sql
            exec_res = self.executor.run(sanitized_sql)
            if not exec_res.success:
                current_error = exec_res.error or "Unknown database error"
                history.append(
                    AttemptRecord(
                        attempt_number=attempt_num,
                        sql=sanitized_sql,
                        stage="execution",
                        error=current_error,
                        success=False,
                    )
                )
                continue

            # Succeeded!
            history.append(
                AttemptRecord(
                    attempt_number=attempt_num,
                    sql=sanitized_sql,
                    stage="completed",
                    error=None,
                    success=True,
                )
            )

            return SelfCorrectionResult(
                success=True,
                final_sql=sanitized_sql,
                execution_result=exec_res,
                attempts=attempt_num,
                attempt_history=history,
                error=None,
            )

        # All retries failed
        friendly_error = (
            f"Query failed after {len(history)} attempts. Last error: {current_error}"
        )
        return SelfCorrectionResult(
            success=False,
            final_sql=current_sql,
            execution_result=None,
            attempts=len(history),
            attempt_history=history,
            error=friendly_error,
        )

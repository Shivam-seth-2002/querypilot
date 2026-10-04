"""Pydantic data models for QueryPilot pipeline."""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class IntentType(str, Enum):
    """Supported user query intent types."""
    DATA_QUERY = "DATA_QUERY"
    SCHEMA_QUESTION = "SCHEMA_QUESTION"
    WRITE_OR_HARMFUL = "WRITE_OR_HARMFUL"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    AMBIGUOUS = "AMBIGUOUS"


class IntentResult(BaseModel):
    """Result of intent classification."""
    intent: IntentType = IntentType.DATA_QUERY
    confidence: float = 1.0
    entities: Dict[str, Any] = Field(default_factory=dict)
    clarification: Optional[str] = None


class ValidationResult(BaseModel):
    """Result of SQL validation checks."""
    is_valid: bool
    sanitized_sql: Optional[str] = None
    errors: List[str] = Field(default_factory=list)


class Timings(BaseModel):
    """Pipeline stage execution times in milliseconds."""
    intent_ms: float = 0.0
    retrieval_ms: float = 0.0
    llm_ms: float = 0.0
    exec_ms: float = 0.0
    total_ms: float = 0.0


class QueryResult(BaseModel):
    """Final result returned by QueryPilot orchestrator."""
    question: str
    intent: str
    retrieved_tables: List[str] = Field(default_factory=list)
    sql: Optional[str] = None
    explanation: Optional[str] = None
    columns: List[str] = Field(default_factory=list)
    rows: List[List[Any]] = Field(default_factory=list)
    row_count: int = 0
    insight: Optional[str] = None
    attempts: int = 1
    timings: Timings = Field(default_factory=Timings)
    error: Optional[str] = None
    success: bool = True

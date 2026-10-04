"""SQL generation module translating natural language questions to SQLite SELECT queries."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from querypilot.config import settings
from querypilot.llm.client import GeminiClient
from querypilot.llm.prompts import SQL_SYSTEM_PROMPT_V1
from querypilot.rag.retriever import RetrievedSchema


class GeneratedSQL(BaseModel):
    """Result from the LLM SQL generator."""
    sql: str
    explanation: str = ""
    tables_used: List[str] = Field(default_factory=list)


class SQLGenerator:
    """Generates SQLite SELECT queries using Gemini and retrieved schema context."""

    def __init__(self, llm_client: Optional[GeminiClient] = None):
        self.llm_client = llm_client or GeminiClient()

    def generate(
        self,
        question: str,
        retrieved_schema: RetrievedSchema,
        entities: Optional[Dict[str, Any]] = None,
    ) -> GeneratedSQL:
        """Generate a SQLite query for a user question with retrieved schema context."""
        sensitive_cols_str = ", ".join(settings.sensitive_columns)
        system_instruction = SQL_SYSTEM_PROMPT_V1.format(
            sensitive_columns=sensitive_cols_str
        )

        entities_text = f"\nExtracted Entities: {entities}" if entities else ""

        prompt = f"""User Question: {question}{entities_text}

Relevant Database Schema:
{retrieved_schema.context_text}

Generate the SQLite query in JSON format:"""

        response = self.llm_client.generate_json(
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=0.0,
        )

        sql = response.get("sql", "").strip()
        explanation = response.get("explanation", "")
        tables_used = response.get("tables_used", [])

        return GeneratedSQL(
            sql=sql,
            explanation=explanation,
            tables_used=tables_used,
        )

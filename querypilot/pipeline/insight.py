"""Natural language insight generator summarizing query results."""

import logging
from typing import Any, List, Optional
import pandas as pd

from querypilot.llm.client import GeminiClient
from querypilot.llm.prompts import INSIGHT_PROMPT_V1

logger = logging.getLogger(__name__)


class InsightGenerator:
    """Generates concise, factual natural language business insights from query results."""

    def __init__(self, llm_client: Optional[GeminiClient] = None):
        self.llm_client = llm_client or GeminiClient()

    def generate(
        self,
        question: str,
        sql: str,
        columns: List[str],
        rows: List[List[Any]],
        row_count: int,
    ) -> str:
        """Generate a 2-3 sentence business summary of the results."""
        if row_count == 0 or not rows:
            return "No matching records were found for this query in the database."

        # Format first 20 rows for prompt context
        sample_rows = rows[:20]
        sample_df = pd.DataFrame(sample_rows, columns=columns)
        data_sample_str = sample_df.to_string(index=False)

        prompt = INSIGHT_PROMPT_V1.format(
            question=question,
            sql=sql,
            row_count=row_count,
            data_sample=data_sample_str,
        )

        try:
            insight = self.llm_client.generate(prompt=prompt, temperature=0.2)
            if insight:
                return insight.strip()
        except Exception as e:
            logger.warning(f"LLM insight generation failed, using rule-based fallback: {e}")

        # Fallback factual summary if LLM call fails or API key is absent
        if len(columns) >= 2:
            first_val = rows[0][0]
            second_val = rows[0][1]
            return f"Query returned {row_count} records. Top entry is '{first_val}' with value '{second_val}'."
        return f"Query completed successfully returning {row_count} record(s)."

"""Intent classification module with rule-based pre-filtering and LLM fallback."""

import re
from typing import Optional
from querypilot.llm.client import GeminiClient
from querypilot.llm.prompts import INTENT_SYSTEM_PROMPT_V1
from querypilot.models import IntentResult, IntentType

# Fast rule-based pre-filter regex for write/destructive commands and prompt injections
WRITE_AND_DESTRUCTIVE_PATTERN = re.compile(
    r"\b(delete\s+from|delete\s+all|drop\s+table|drop\s+database|update\s+\w+\s+set|"
    r"insert\s+into|alter\s+table|truncate\s+table|create\s+table|attach\s+database|"
    r"detach\s+database|replace\s+into)\b",
    re.IGNORECASE,
)

INJECTION_PATTERN = re.compile(
    r"(ignore\s+(all\s+)?(previous|prior)\s+instructions|disregard\s+(all\s+)?prior|"
    r"system\s+prompt|jailbreak|bypass\s+(guardrails|security)|dan\s+mode|as\s+an\s+unfiltered\s+ai)",
    re.IGNORECASE,
)

SCHEMA_QUESTION_PATTERN = re.compile(
    r"^(what\s+tables|list\s+tables|show\s+tables|what\s+data\s+is\s+available|describe\s+schema|what\s+is\s+the\s+schema)\b",
    re.IGNORECASE,
)


class IntentClassifier:
    """Classifies user intent using fast rule-based pre-filters followed by Gemini LLM."""

    def __init__(self, llm_client: Optional[GeminiClient] = None):
        self.llm_client = llm_client or GeminiClient()

    def classify(self, question: str) -> IntentResult:
        """Classify user question into IntentResult."""
        clean_q = question.strip()

        # 1. Rule-based pre-filter for write/destructive actions
        if WRITE_AND_DESTRUCTIVE_PATTERN.search(clean_q):
            return IntentResult(
                intent=IntentType.WRITE_OR_HARMFUL,
                confidence=1.0,
                clarification="Database modifications (DELETE, DROP, UPDATE, INSERT) are strictly prohibited. QueryPilot is a read-only analytics system.",
            )

        # 2. Rule-based pre-filter for prompt injection attempts
        if INJECTION_PATTERN.search(clean_q):
            return IntentResult(
                intent=IntentType.WRITE_OR_HARMFUL,
                confidence=1.0,
                clarification="System instruction overrides and prompt injection attempts are refused.",
            )

        # 3. Rule-based shortcut for common schema questions
        if SCHEMA_QUESTION_PATTERN.search(clean_q):
            return IntentResult(
                intent=IntentType.SCHEMA_QUESTION,
                confidence=1.0,
                entities={"topic": "database_tables"},
            )

        # 4. LLM Classification fallback
        try:
            prompt = f"User Query: {clean_q}"
            response = self.llm_client.generate_json(
                prompt=prompt,
                system_instruction=INTENT_SYSTEM_PROMPT_V1,
            )

            intent_str = response.get("intent", "DATA_QUERY").upper()
            try:
                intent_enum = IntentType(intent_str)
            except ValueError:
                intent_enum = IntentType.DATA_QUERY

            return IntentResult(
                intent=intent_enum,
                confidence=float(response.get("confidence", 0.9)),
                entities=response.get("entities", {}) or {},
                clarification=response.get("clarification"),
            )
        except Exception:
            # Safe fallback default: treat as DATA_QUERY
            return IntentResult(
                intent=IntentType.DATA_QUERY,
                confidence=0.8,
                entities={},
            )

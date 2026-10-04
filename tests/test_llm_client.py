"""Unit tests for GeminiClient wrapper and JSON parser."""

import pytest
from unittest.mock import MagicMock, patch
from querypilot.llm.client import GeminiClient, GeminiAPIKeyMissingError


def test_extract_json_plain():
    text = '{"name": "QueryPilot", "count": 42}'
    data = GeminiClient.extract_json(text)
    assert data["name"] == "QueryPilot"
    assert data["count"] == 42


def test_extract_json_markdown_fence():
    text = """```json
    {
        "sql": "SELECT * FROM orders",
        "explanation": "test explanation"
    }
    ```"""
    data = GeminiClient.extract_json(text)
    assert data["sql"] == "SELECT * FROM orders"
    assert data["explanation"] == "test explanation"


def test_extract_json_with_surrounding_text():
    text = """Here is the query you requested:
    {"key": "value"}
    Hope this helps!"""
    data = GeminiClient.extract_json(text)
    assert data["key"] == "value"


def test_missing_api_key_raises_informative_error():
    client = GeminiClient(api_key="")
    assert not client.is_configured
    with pytest.raises(GeminiAPIKeyMissingError):
        client.generate("test prompt")


def test_mocked_gemini_generation():
    client = GeminiClient(api_key="mock_test_key")
    mock_response = MagicMock()
    mock_response.text = '{"sql": "SELECT 1", "tables_used": ["orders"]}'

    with patch.object(client, "_get_client") as mock_get_client:
        mock_genai_client = MagicMock()
        mock_genai_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_genai_client

        result = client.generate_json("Generate query")
        assert result["sql"] == "SELECT 1"
        assert result["tables_used"] == ["orders"]

"""Configuration settings for QueryPilot."""

from pathlib import Path
from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Google Gemini API
    gemini_api_key: str = Field(default="", validation_alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", validation_alias="GEMINI_MODEL")

    # Data paths
    db_path: str = Field(default="data/retail.db", validation_alias="DB_PATH")
    app_log_db_path: str = Field(default="data/app_log.db", validation_alias="APP_LOG_DB_PATH")
    chroma_path: str = Field(default="data/chroma", validation_alias="CHROMA_PATH")
    exports_path: str = Field(default="data/exports", validation_alias="EXPORTS_PATH")

    # Execution limits & guardrails
    query_timeout_seconds: int = Field(default=5, validation_alias="QUERY_TIMEOUT_SECONDS")
    default_row_limit: int = Field(default=100, validation_alias="DEFAULT_ROW_LIMIT")
    max_row_limit: int = Field(default=1000, validation_alias="MAX_ROW_LIMIT")

    # Sensitive columns that must never be selected
    sensitive_columns: List[str] = Field(
        default=["employees.salary", "customers.email"]
    )

    # RAG settings
    top_k_tables: int = Field(default=4)


# Global settings singleton
settings = Settings()

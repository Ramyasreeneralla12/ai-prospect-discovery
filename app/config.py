from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AI-Powered Multi-Platform Prospect Discovery API"
    app_env: str = "development"
    search_provider: str = "tavily"
    tavily_api_key: str = ""
    llm_provider: str = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    gemini_quota_cooldown_seconds: int = Field(default=86400, ge=60, le=86400)
    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    search_results_per_query: int = Field(default=8, ge=1, le=20)
    max_search_queries: int = Field(default=6, ge=1, le=12)
    min_relevance_score: float = Field(default=0.58, ge=0, le=1)
    request_timeout_seconds: float = Field(default=15, gt=0, le=60)


@lru_cache
def get_settings() -> Settings:
    return Settings()

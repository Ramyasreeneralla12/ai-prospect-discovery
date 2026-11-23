from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class DiscoveryRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    query: str = Field(min_length=3, max_length=500, description="Natural-language prospect search")

    @field_validator("query")
    @classmethod
    def query_must_contain_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be empty")
        return value


class Location(BaseModel):
    city: str | None = None
    state: str | None = None
    country: str | None = None

    def display(self) -> str | None:
        parts = [self.city, self.state, self.country]
        result = ", ".join(p for p in parts if p)
        return result or None


class QueryIntent(BaseModel):
    interest: str
    audience: str
    location: Location = Field(default_factory=Location)
    target_type: Literal["individual", "business", "unknown"] = "unknown"
    keywords: list[str] = Field(default_factory=list)


class SocialLink(BaseModel):
    platform: Literal["LinkedIn", "Instagram", "YouTube", "X", "Facebook", "Threads", "WhatsApp", "Email", "Phone", "Website"]
    link: str


class Prospect(BaseModel):
    name: str
    location: str | None = None
    social_link: list[SocialLink] = Field(default_factory=list)


class DiscoveryResponse(BaseModel):
    success: bool = True
    query: str
    total_prospects: int
    prospects: list[Prospect]
    sources_checked: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SearchResult(BaseModel):
    title: str
    url: HttpUrl
    snippet: str = ""
    source: str = "Tavily Search"


class ProspectEvidence(BaseModel):
    prospect: Prospect
    evidence_urls: list[str]
    score: float = Field(ge=0, le=1)
    rationale: str

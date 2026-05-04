"""
Pydantic schemas for AI Visibility Grader.
All data flowing between services and the API is typed here.
"""

from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class Product(BaseModel):
    asin: str
    brand: str
    title: str
    category: str
    bullets: list[str] = Field(default_factory=list)
    image_url: Optional[str] = None


class QueryResult(BaseModel):
    query: str
    gpt4_response: str
    claude_response: str
    gemini_response: str


class ModelMentions(BaseModel):
    gpt4: bool = False
    claude: bool = False
    gemini: bool = False


class ModelPositions(BaseModel):
    gpt4: Optional[int] = None
    claude: Optional[int] = None
    gemini: Optional[int] = None


class ParsedQueryResult(BaseModel):
    query: str
    mentions: ModelMentions
    position: ModelPositions
    competitors_mentioned: list[str] = Field(default_factory=list)
    attributes: dict[str, list[str]] = Field(default_factory=dict)


class Competitor(BaseModel):
    brand: str
    mention_count: int


class Score(BaseModel):
    overall: int = Field(ge=0, le=100)
    gpt4: int = Field(ge=0, le=100)
    claude: int = Field(ge=0, le=100)
    gemini: int = Field(ge=0, le=100)
    top_competitors: list[Competitor] = Field(default_factory=list)
    # How many queries were actually scored (may be < 10 if timeout hit)
    queries_used: int = 10


class Recommendation(BaseModel):
    title: str
    description: str
    priority: str


class DiagnoseRequest(BaseModel):
    # Exact listing identifier: accepts a raw ASIN or an Amazon product URL.
    asin: Optional[str] = Field(default=None)
    amazon_url: Optional[str] = None
    brand: Optional[str] = None
    title: Optional[str] = None
    category: Optional[str] = None

    @property
    def listing_input(self) -> Optional[str]:
        return self.amazon_url or self.asin


class QuerySummary(BaseModel):
    query: str
    mentions: ModelMentions
    winners: list[str]
    your_position: Optional[int] = None


class DiagnoseResponse(BaseModel):
    product: Product
    score: Score
    queries: list[QuerySummary]
    top_competitors: list[Competitor]
    recommendations: list[Recommendation]

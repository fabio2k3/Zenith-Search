from pydantic import BaseModel, Field
from typing import Optional


class SearchRequest(BaseModel):
    query: str
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=5, ge=1, le=20)


class SearchResult(BaseModel):
    score: float
    file_name: str
    relative_path: str
    text: str
    pdf_url: Optional[str] = None
    chunk_id: Optional[int] = None
    doc_id: Optional[int] = None
    bm25_score: float = 0.0
    vector_score: float = 0.0
    bm25_rank: Optional[int] = None
    vector_rank: Optional[int] = None


class SearchResponse(BaseModel):
    query: str
    page: int
    page_size: int
    results: list[SearchResult]
    did_you_mean: Optional[str] = None
    has_more: bool = False
    next_page: Optional[int] = None
    prev_page: Optional[int] = None
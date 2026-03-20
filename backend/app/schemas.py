from pydantic import BaseModel, Field
from typing import Optional


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Consulta del usuario")
    top_k: int = Field(5, ge=1, le=20, description="Número de resultados a devolver")


class SearchResult(BaseModel):
    score: float
    file_name: str
    relative_path: str
    text: str

    pdf_url: Optional[str] = None
    chunk_id: Optional[str] = None
    doc_id: Optional[str] = None
    bm25_score: float = 0.0
    vector_score: float = 0.0
    bm25_rank: Optional[int] = None
    vector_rank: Optional[int] = None


class SearchResponse(BaseModel):
    query: str
    top_k: int
    results: list[SearchResult]
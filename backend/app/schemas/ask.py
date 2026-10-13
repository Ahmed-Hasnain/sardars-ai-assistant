from pydantic import BaseModel


class SourceCitation(BaseModel):
    number: int
    source_id: str
    title: str
    url: str
    fetched_at: str | None


class AskResponse(BaseModel):
    answer: str
    sources: list[SourceCitation]

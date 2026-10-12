from pydantic import BaseModel


class SourceCitation(BaseModel):
    title: str
    url: str


class AskResponse(BaseModel):
    answer: str
    sources: list[SourceCitation]

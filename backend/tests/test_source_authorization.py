import asyncio
from hashlib import sha256
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models import SourceRegistration
from app.llm.base import ChatResult
from app.rag.answer_seed import FALLBACK
from app.retrieval.authorization import authorized_points
from app.retrieval.search_seed import search_for_role
from app.services.company_answer import answer_company


URL = "https://sardarandco.com/pages/about-us"
SOURCE_ID = sha256(URL.encode()).hexdigest()
CONTENT_SHA256 = sha256(b"test source content").hexdigest()


def _point(visibility: str = "public") -> dict:
    return {"payload": {
        "source_id": SOURCE_ID,
        "url": URL,
        "source_type": "pages",
        "content_sha256": CONTENT_SHA256,
        "visibility": visibility,
        "review_status": "approved",
        "prototype_only": False,
        "text": "A test sentence",
    }}


def test_registry_enforces_role_and_exact_source_metadata() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        source = SourceRegistration(
            source_id=SOURCE_ID, url=URL, source_type="pages",
            content_sha256=CONTENT_SHA256,
            visibility="admin", authorization_basis="test_source_authorization",
        )
        db.add(source)
        db.commit()

        admin_point = _point("admin")
        assert authorized_points(db, "admin", [admin_point]) == [admin_point]
        assert authorized_points(db, "staff", [admin_point]) == []
        assert authorized_points(db, "admin", [_point("public")]) == []
        assert authorized_points(db, "admin", [{"payload": {**admin_point["payload"], "url": URL + "-other"}}]) == []
        assert authorized_points(db, "admin", [{"payload": {**admin_point["payload"], "content_sha256": "0" * 64}}]) == []
        assert authorized_points(db, "admin", [{"payload": {**admin_point["payload"], "source_id": []}}]) == []
        source.is_active = False
        db.commit()
        assert authorized_points(db, "admin", [admin_point]) == []
    engine.dispose()


def test_role_search_prefilters_only_allowed_visibilities() -> None:
    with patch("app.retrieval.search_seed._query", return_value=[]) as query:
        assert search_for_role("Which brands?", "staff") == []
        assert query.call_args.args[2] == {"public", "staff"}
        assert search_for_role("Which brands?", "admin") == []
        assert query.call_args.args[2] == {"public", "staff", "admin"}
        query.reset_mock()
        assert search_for_role("Which brands?", "unknown") == []
        query.assert_not_called()


def test_company_answer_keeps_admin_only_source_from_staff_prompt() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    point = _point("admin")
    point["payload"].update({
        "title": "About Us",
        "text": "Sardars mentions brands like Bongio and Grohe.",
    })
    with sessions() as db:
        db.add(SourceRegistration(
            source_id=SOURCE_ID, url=URL, source_type="pages",
            content_sha256=CONTENT_SHA256, visibility="admin",
            authorization_basis="test_source_authorization",
        ))
        db.commit()
        model = AsyncMock()
        model.chat.return_value = ChatResult(FALLBACK, "test-model", None, None, None)
        with patch("app.services.company_answer.search_for_role", return_value=[point]):
            staff_result = asyncio.run(answer_company("Which brands?", "staff", db, model))
            admin_result = asyncio.run(answer_company("Which brands?", "admin", db, model))

    assert staff_result.text == FALLBACK
    assert staff_result.sources == []
    assert "Bongio" in admin_result.text
    assert admin_result.sources[0].source_id == SOURCE_ID
    model.chat.assert_awaited_once()
    engine.dispose()

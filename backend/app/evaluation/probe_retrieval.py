"""Read-only candidate-rank probe for the saved full-site questions.

Run with local services: python -m app.evaluation.probe_retrieval
"""

from pathlib import Path

from app.db.session import SessionLocal
from app.evaluation.run_coverage import load_cases
from app.retrieval import search_seed
from app.retrieval.authorization import authorized_points
from app.retrieval.selection import select_authorized_points
from app.rag.answer_seed import _approved_excerpts, _matching_sentences


def main() -> None:
    cases = load_cases(Path(__file__).with_name("full_site_cases.json"))
    hits = 0
    top_eight_hits = 0
    reranked_hits = 0
    supported = 0
    for case in cases:
        if case.control or not case.expected_source:
            continue
        supported += 1
        candidates = search_seed.search_for_role(case.question, case.role)
        with SessionLocal() as db:
            points = authorized_points(db, case.role, candidates)
            selected = select_authorized_points(db, case.role, case.question, candidates)
        urls = [point["payload"].get("url") for point in points]
        rank = urls.index(case.expected_source) + 1 if case.expected_source in urls else None
        hits += rank is not None
        top_eight_hits += rank is not None and rank <= 8
        new_urls = [point["payload"].get("url") for point in selected]
        new_rank = new_urls.index(case.expected_source) + 1 if case.expected_source in new_urls else None
        reranked_hits += new_rank is not None
        print(f"{case.id}: semantic {rank or '>32'}; selected {new_rank or '>8'}", flush=True)
    print(f"Authorized semantic top-8: {top_eight_hits}/{supported}; "
          f"top-32: {hits}/{supported}; selected top-8: {reranked_hits}/{supported}")
    storage = next(case for case in cases if case.id == "storage")
    public_candidates = search_seed.search_approved(storage.question)
    with SessionLocal() as db:
        selected = select_authorized_points(db, "staff", storage.question, public_candidates)
    print("Public seed storage selected URLs:",
          [point["payload"].get("url") for point in selected])
    print("Public seed storage lexical match URLs:",
          [excerpt.url for excerpt in _matching_sentences(storage.question, _approved_excerpts(selected))])


if __name__ == "__main__":
    main()

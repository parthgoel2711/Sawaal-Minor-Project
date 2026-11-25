from __future__ import annotations

import pytest

from app.documents import DocumentError, DocumentStore, chunk_page, extract_pages, tokenize

POLICY = (
    "Leave policy\n\nEmployees get 24 days of paid leave each year. Unused leave carries over up to 10 days.\n\n"
    "Notice period\n\nThe notice period for resignation is 30 days. Managers must give 60 days notice."
)
OTHER = "Travel policy\n\nFlights must be booked 14 days in advance. Hotel stays are capped at 6000 rupees a night."


def test_tokenize_drops_stopwords():
    assert tokenize("What is the notice period?") == ["notice", "period"]


def test_chunking_respects_size_and_keeps_text():
    long = " ".join(f"Sentence number {i} says something useful." for i in range(80))
    chunks = chunk_page(long, size=300)
    assert all(len(c) <= 300 for c in chunks)
    assert "".join(chunks).replace(" ", "") == long.replace(" ", "")
    assert chunk_page("   \n\n  ") == []


def test_unbroken_text_is_split():
    assert all(len(c) <= 100 for c in chunk_page("x" * 450, size=100))


def test_extract_text_and_reject_unknown():
    assert extract_pages("a.txt", "héllo".encode()) == ["héllo"]
    with pytest.raises(DocumentError):
        extract_pages("a.exe", b"MZ")
    with pytest.raises(DocumentError):
        extract_pages("a.pdf", b"not a pdf")


@pytest.fixture
def store(tmp_path):
    s = DocumentStore(tmp_path / "docs.db")
    s.add("hr.txt", POLICY.encode())
    s.add("travel.txt", OTHER.encode())
    return s


def test_search_ranks_relevant_passage_first(store):
    top = store.search("how long is the notice period for resignation")[0]
    assert top.document == "hr.txt" and "30 days" in top.text
    assert store.search("hotel cap per night")[0].document == "travel.txt"


def test_search_can_be_limited_to_documents(store):
    travel_id = next(d.id for d in store.list() if d.name == "travel.txt")
    assert {p.document for p in store.search("days", [travel_id])} == {"travel.txt"}
    assert store.search("zebra unicorn") == []


def test_delete_removes_passages(store):
    hr = next(d for d in store.list() if d.name == "hr.txt")
    store.delete(hr.id)
    assert store.search("notice period") == []
    with pytest.raises(KeyError):
        store.delete(hr.id)


def test_empty_file_is_rejected(tmp_path):
    with pytest.raises(DocumentError, match="No text"):
        DocumentStore(tmp_path / "d.db").add("e.txt", b"  \n ")


def test_pdf_roundtrip(tmp_path):
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(200, 200)
    import io

    buf = io.BytesIO()
    w.write(buf)
    with pytest.raises(DocumentError, match="No text"):  # a blank page has no text
        DocumentStore(tmp_path / "d.db").add("blank.pdf", buf.getvalue())


def test_endpoints(client, fake_generator):
    r = client.post("/api/documents", files={"file": ("hr.txt", POLICY.encode(), "text/plain")})
    assert r.status_code == 201 and r.json()["chunks"] >= 1
    assert client.get("/api/documents").json()[0]["name"] == "hr.txt"
    ans = client.post("/api/documents/ask", json={"question": "notice period for resignation"}).json()
    assert ans["found"] and "[1]" in ans["answer"] and ans["sources"][0]["document"] == "hr.txt"
    assert "30 days" in fake_generator.doc_calls[0]["passages"][0]
    miss = client.post("/api/documents/ask", json={"question": "zebra unicorn"}).json()
    assert miss["found"] is False and miss["sources"] == []
    bad = client.post("/api/documents", files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert bad.status_code == 400
    assert client.delete(f"/api/documents/{r.json()['id']}").status_code == 204
    assert client.delete(f"/api/documents/{r.json()['id']}").status_code == 404


def test_ask_with_database_adds_data_source(client, fake_generator):
    client.post("/api/documents", files={"file": ("hr.txt", POLICY.encode(), "text/plain")})
    dbs = client.get("/api/databases").json()
    shop = next(d for d in dbs if d["id"] == "ecommerce")["id"]
    ans = client.post("/api/documents/ask", json={"question": "notice period", "database_id": shop}).json()
    assert any(s["kind"] == "database" for s in ans["sources"])
    assert ans["sql"] and fake_generator.doc_calls[-1]["data_context"]


def test_without_ai_returns_passages_only(client_without_llm):
    c = client_without_llm
    c.post("/api/documents", files={"file": ("hr.txt", POLICY.encode(), "text/plain")})
    ans = c.post("/api/documents/ask", json={"question": "notice period"}).json()
    assert ans["answer"] is None and ans["sources"]

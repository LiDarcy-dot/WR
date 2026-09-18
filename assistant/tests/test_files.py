from __future__ import annotations

from pathlib import Path

from app.db import connect, init_db
from app.db import repo
from app.files.extract import extract_text_pages, pages_to_chunks
from app.files.ingest import index_file, save_telegram_bytes
from app.files.query import build_docs_context, list_files_html
from app.files import store as file_store
from app.intent import classify_intent
from app.storage_layout import ensure_data_layout


def test_intent_file_flows() -> None:
    assert classify_intent("сейчас скину файлы, сохрани").kind == "ingest_start"
    assert classify_intent("сохрани мануалы по КТ").kind == "ingest_start"
    assert classify_intent("готово").kind == "ingest_end"
    assert classify_intent("какие файлы").kind == "list_files"
    assert (
        classify_intent("как выполнить Aging? посмотри в мануалах что я скинул").kind
        == "ask_docs"
    )
    assert classify_intent("пароль к файлу 3: secret").kind == "file_password"
    # do not steal normal chat
    assert classify_intent("как сделать чай").kind == "chat"
    # look-in-storage must not open ingest
    assert classify_intent("посмотри в хранилище про Aging").kind == "ask_docs"
    # temp read: wait for file, do not search library yet
    assert (
        classify_intent(
            "сейчас я скину файл- не сохраняй его а прочитай и напиши "
            "как будешь ответить на вопросы я задам пару вопросов по этому файлу"
        ).kind
        == "temp_read_start"
    )
    assert classify_intent("скину файл, только прочитай").kind == "temp_read_start"
    assert classify_intent("забей").kind == "abort"
    assert classify_intent("передумал").kind == "abort"


def test_txt_ingest_and_search(tmp_path: Path) -> None:
    root = tmp_path / "data"
    ensure_data_layout(root)
    db = root / "db" / "t.sqlite3"
    init_db(db)
    conn = connect(db)
    repo.ensure_runtime_schema(conn)

    sid = file_store.open_ingest_session(conn, chat_id=1, category="ct_manuals")
    file_store.set_pending_comment(conn, sid, "мануал GE")
    comment = file_store.take_pending_comment(conn, sid)
    assert comment == "мануал GE"

    raw = (
        b"Aging Procedure\n"
        b"Page content: To perform Aging, open Service menu and select Aging.\n"
        b"Confirm start and wait until complete.\n"
    )

    async def _run():
        return await save_telegram_bytes(
            conn=conn,
            data_root=root,
            raw=raw,
            original_name="ct_aging.txt",
            mime="text/plain",
            category="ct_manuals",
            comment=comment,
            session_id=sid,
        )

    import asyncio

    file_id, msg = asyncio.run(_run())
    assert file_id > 0
    assert "сохранён" in msg or "уже был" in msg
    indexed = index_file(conn, root, file_id)
    assert "проиндексирован" in indexed
    conn.commit()

    hits = file_store.search_chunks(conn, "Aging procedure Service menu", limit=5)
    assert hits
    assert any("Aging" in h["text"] for h in hits)
    ctx = build_docs_context(hits)
    assert "Aging" in ctx
    rows = file_store.list_files(conn, category="ct_manuals")
    html = list_files_html(rows)
    assert "ct_aging" in html
    file_store.close_ingest_session(conn, sid)
    assert file_store.get_open_ingest(conn, 1) is None


def test_pdf_password_and_chunks(tmp_path: Path) -> None:
    from pypdf import PdfWriter

    path = tmp_path / "sample.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.encrypt("secret")
    writer.write(path)

    pages, err = extract_text_pages(path, password=None)
    assert err == "password"
    pages, err = extract_text_pages(path, password="wrong")
    assert err == "password"
    pages, err = extract_text_pages(path, password="secret")
    assert err is None

    chunks = pages_to_chunks([(1, "hello " * 400), (2, "Aging start")])
    assert len(chunks) >= 2
    assert chunks[-1][0] == 2


def test_password_reindex(tmp_path: Path) -> None:
    from pypdf import PdfWriter

    root = tmp_path / "data"
    ensure_data_layout(root)
    db = root / "db" / "p.sqlite3"
    init_db(db)
    conn = connect(db)
    repo.ensure_runtime_schema(conn)

    path = root / "documents" / "manuals"
    path.mkdir(parents=True, exist_ok=True)
    pdf = path / "locked.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt("pw123")
    writer.write(pdf)

    fid = file_store.insert_file(
        conn,
        relative_path="documents/manuals/locked.pdf",
        original_name="locked.pdf",
        mime="application/pdf",
        sha256="abc",
        category="manuals",
        comment=None,
        session_id=None,
    )
    msg = index_file(conn, root, fid)
    assert "пароль" in msg
    row = file_store.get_file(conn, fid)
    assert row["needs_password"] == 1

    file_store.set_file_password(conn, fid, "pw123")
    msg2 = index_file(conn, root, fid)
    # blank pdf has no extractable text
    assert "пароль" not in msg2 or "нет текста" in msg2 or "проиндексирован" in msg2
    row2 = file_store.get_file(conn, fid)
    assert row2["needs_password"] == 0


def test_password_candidates_unlock(tmp_path: Path) -> None:
    from pypdf import PdfWriter

    from app.files.ingest import try_unlock_pending
    from app.files.store import parse_password_candidates

    assert classify_intent("возможные пароли a b c").kind == "password_candidates"
    assert parse_password_candidates("возможные пароли alpha beta") == [
        "alpha",
        "beta",
    ]
    assert parse_password_candidates('пароли: one, "two three", four') == [
        "two three",
        "one",
        "four",
    ]

    root = tmp_path / "data"
    ensure_data_layout(root)
    db = root / "db" / "c.sqlite3"
    init_db(db)
    conn = connect(db)
    repo.ensure_runtime_schema(conn)

    path = root / "documents" / "manuals"
    path.mkdir(parents=True, exist_ok=True)
    pdf = path / "locked2.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt("rightpass")
    writer.write(pdf)

    fid = file_store.insert_file(
        conn,
        relative_path="documents/manuals/locked2.pdf",
        original_name="locked2.pdf",
        mime="application/pdf",
        sha256="def",
        category="manuals",
        comment=None,
        session_id=None,
    )
    assert "пароль" in index_file(conn, root, fid)

    added = file_store.add_password_candidates(
        conn, ["wrong1", "rightpass", "wrong2"], source="user"
    )
    assert added == 3
    lines = try_unlock_pending(conn, root)
    assert lines
    row = file_store.get_file(conn, fid)
    assert row["needs_password"] == 0
    assert file_store.get_file_password(conn, fid) == "rightpass"


def test_temp_session_keeps_path(tmp_path: Path) -> None:
    from app.files import temp_session as ts
    from app.media.images import is_image_name

    assert is_image_name("IMG_9545.HEIC")
    bot_data: dict = {}
    root = tmp_path / "data"
    root.mkdir()
    raw = b"hello"
    path = ts.save_raw_temp(root, raw, "note.txt")
    assert Path(path).exists()
    ts.start_waiting(bot_data, 1, note="read")
    ts.mark_ready(
        bot_data,
        1,
        name="note.txt",
        text="hello",
        path=path,
        kind="text",
    )
    assert Path(path).exists()
    sess = ts.get_session(bot_data, 1)
    assert sess and sess["status"] == "ready"
    assert sess["text"] == "hello"
    # empty text but image must still be ready
    ts.mark_ready(
        bot_data,
        1,
        name="pic.jpg",
        text="",
        path=path,
        kind="image",
        image_data_url="data:image/jpeg;base64,xx",
    )
    sess2 = ts.get_session(bot_data, 1)
    assert sess2["status"] == "ready"
    assert sess2["image_data_url"]
    assert Path(path).exists()

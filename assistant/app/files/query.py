from __future__ import annotations


DOCS_SYSTEM = """Ты помощник по личной библиотеке файлов пользователя.
Отвечай по-русски. Опирайся ТОЛЬКО на переданные фрагменты.
Если в разных мануалах ответы похожи — объедини и перечисли отличия.
Если есть несколько разных процедур — покажи ВСЕ варианты без выдуманных повторов.
Для каждого варианта укажи источник: имя файла и страницу (если есть).
Формат:
1) Краткий ответ
2) Варианты / шаги
3) Источники: файл, стр. N
Если данных мало — скажи чего не хватает.
"""


def build_docs_context(rows: list) -> str:
    lines = ["Фрагменты из хранилища:"]
    seen = set()
    for r in rows:
        key = (r["file_id"], r["page"], r["text"][:120])
        if key in seen:
            continue
        seen.add(key)
        page = r["page"] or "?"
        name = r["title"] or r["original_name"]
        lines.append(f"— {name} · стр. {page}")
        lines.append(r["text"][:1500])
        lines.append("")
    return "\n".join(lines)


def list_files_html(rows: list) -> str:
    if not rows:
        return (
            "В хранилище пока пусто.\n"
            "Скажи «сейчас скину файлы, сохрани» и пришли файлы."
        )
    lines = [f"<b>Файлы</b> · {len(rows)}"]
    for r in rows:
        name = r["title"] or r["original_name"] or "file"
        cat = r["category"] or "general"
        comment = f"\n  <i>{_esc(r['comment'])}</i>" if r["comment"] else ""
        flag = ""
        if r["needs_password"]:
            flag = " · нужен пароль"
        elif not r["indexed_at"]:
            flag = " · не проиндексирован"
        lines.append(
            f"• <b>{_esc(name)}</b> · {_esc(cat)} · id={r['id']}{flag}{comment}"
        )
    return "\n".join(lines)


def _esc(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

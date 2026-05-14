# -*- coding: utf-8 -*-

import sys
from pathlib import Path

from tools import repair_library_catalog as repair_tool


def test_repair_script_bootstraps_repo_root_on_sys_path():
    assert repair_tool.REPO_ROOT == Path(repair_tool.__file__).resolve().parents[1]
    assert str(repair_tool.REPO_ROOT) in sys.path


def test_repair_script_rebuilds_from_library_files(tmp_path):
    library_dir = tmp_path / "library"
    files_dir = library_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    source = files_dir / "rebuild_me.txt"
    source.write_text("repair script should rebuild from original source file", encoding="utf-8")

    payload = repair_tool.rebuild_from_files(library_dir)

    assert payload["books"]
    book = payload["books"][0]
    assert book["source_path"]
    assert Path(book["text_path"]).exists()
    assert "原始文件" in book["warnings"][0]


def test_repair_script_merges_missing_books_into_existing_catalog(tmp_path):
    library_dir = tmp_path / "library"
    books_dir = library_dir / "books"
    files_dir = library_dir / "files"
    books_dir.mkdir(parents=True, exist_ok=True)
    files_dir.mkdir(parents=True, exist_ok=True)

    existing_text = books_dir / "kept.txt"
    existing_text.write_text("existing text", encoding="utf-8")
    source = files_dir / "missing_source.txt"
    source.write_text("recover this missing source too", encoding="utf-8")

    current = {
        "version": 1,
        "books": [
            {
                "id": "kept",
                "title": "kept",
                "text_path": str(existing_text),
                "source_path": "",
                "created_at_ms": 1,
                "updated_at_ms": 1,
            }
        ],
    }
    rebuilt = repair_tool.rebuild_from_files(library_dir)
    merged, added = repair_tool.merge_missing_books(current, rebuilt)

    assert added == 1
    assert len(merged["books"]) == 2
    assert any("missing_source" in str(row.get("id") or "") for row in merged["books"])


def test_repair_script_prefers_seeded_title_and_cursor_from_reviews(tmp_path):
    library_dir = tmp_path / "library"
    books_dir = library_dir / "books"
    review_dir = library_dir / "reviews" / "book_1778"
    books_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)

    text_path = books_dir / "book_1778.txt"
    text_path.write_text("0123456789abcdefghij", encoding="utf-8")
    (review_dir / "review_a.json").write_text(
        """
        {
          "id": "review_a",
          "book_id": "book_1778",
          "book_title": "千字文",
          "title": "千字文 1",
          "range": {"start": 0, "end": 10},
          "summary": "片段总结",
          "understanding": "片段总结",
          "created_at_ms": 123456
        }
        """,
        encoding="utf-8",
    )
    seed = {
        "version": 1,
        "books": [
            {
                "id": "book_1778",
                "title": "book_1778",
                "summary": "",
                "text_path": str(text_path),
                "source_path": "",
                "cursor": 0,
                "read_chars": 0,
                "read_tick_count": 4,
                "last_read_at_ms": 0,
            }
        ],
    }

    payload = repair_tool.rebuild_from_files(library_dir, seed_catalog=seed)

    assert payload["books"]
    book = payload["books"][0]
    assert book["title"] == "千字文"
    assert book["cursor"] == 10
    assert book["read_chars"] == 10
    assert book["reviews"][0]["book_title"] == "千字文"

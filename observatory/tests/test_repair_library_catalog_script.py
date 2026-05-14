# -*- coding: utf-8 -*-

from pathlib import Path

from tools import repair_library_catalog as repair_tool


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

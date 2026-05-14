# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def book_count(payload) -> int:
    if isinstance(payload, list):
        return len([row for row in payload if isinstance(row, dict)])
    if isinstance(payload, dict):
        return len([row for row in payload.get("books", []) if isinstance(row, dict)])
    return 0


def slug(value: str, fallback: str) -> str:
    import re

    text = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(value or "").strip().lower())
    text = re.sub(r"_+", "_", text).strip("._-")
    return text[:48] or fallback


def backups_for(path: Path) -> list[Path]:
    if not path.parent.exists():
        return []
    rows = [item for item in path.parent.glob(f"{path.name}*.bak") if item.is_file()]
    rows.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return rows


def normalize_catalog(payload) -> dict:
    if isinstance(payload, list):
        payload = {"version": 1, "books": payload}
    if not isinstance(payload, dict):
        payload = {"version": 1, "books": []}
    payload["books"] = [row for row in payload.get("books", []) if isinstance(row, dict)]
    payload["version"] = payload.get("version") or 1
    payload["updated_at_ms"] = int(time.time() * 1000)
    return payload


def compact_review_for_catalog(library_dir: Path, book_id: str, review: dict) -> tuple[dict, bool]:
    review = dict(review or {})
    review_id = str(review.get("id") or f"review_{int(time.time() * 1000)}")
    body = str(review.get("understanding") or review.get("summary") or review.get("content") or "")
    review_path = str(review.get("review_path") or review.get("path") or "").strip()
    changed = False
    if body and (len(body) > 900 or not review_path):
        safe_book_id = slug(book_id, "book")
        safe_review_id = slug(review_id, f"review_{int(time.time() * 1000)}")
        out = library_dir / "reviews" / safe_book_id / f"{safe_review_id}.json"
        write_json(out, review)
        review_path = str(out.relative_to(library_dir)).replace("\\", "/")
        changed = True
    summary = body[:900]
    compact = {
        "id": review_id,
        "book_id": str(review.get("book_id") or book_id or ""),
        "book_title": str(review.get("book_title") or ""),
        "title": str(review.get("title") or ""),
        "range": review.get("range") or {},
        "created_at_ms": int(review.get("created_at_ms") or time.time() * 1000),
        "summary": summary,
        "understanding": summary,
        "excerpt": str(review.get("excerpt") or "")[:800],
        "ap_tick_count": int(review.get("ap_tick_count") or 0),
        "chunk_count": int(review.get("chunk_count") or 0),
        "review_tick_target": int(review.get("review_tick_target") or 0),
        "llm_generated": bool(review.get("llm_generated")),
        "model": str(review.get("model") or ""),
    }
    if review_path:
        compact["review_path"] = review_path
    return compact, changed


def compact_catalog_reviews(library_dir: Path, payload: dict) -> tuple[dict, int]:
    catalog = normalize_catalog(payload)
    changed_count = 0
    for index, book in enumerate(catalog.get("books", [])):
        if not isinstance(book, dict):
            continue
        book_id = slug(str(book.get("id") or book.get("title") or f"book_{index + 1}"), f"book_{index + 1}")
        book["id"] = book_id
        compact_reviews = []
        for review in [row for row in book.get("reviews", []) if isinstance(row, dict)][-300:]:
            compact, changed = compact_review_for_catalog(library_dir, book_id, review)
            compact_reviews.append(compact)
            if changed:
                changed_count += 1
        book["reviews"] = compact_reviews
    catalog["updated_at_ms"] = int(time.time() * 1000)
    return catalog, changed_count


def rebuild_from_files(library_dir: Path) -> dict:
    books_dir = library_dir / "books"
    reviews_dir = library_dir / "reviews"
    books = []
    if books_dir.exists():
        for text_path in sorted(books_dir.glob("*.txt"), key=lambda item: item.stat().st_mtime, reverse=True):
            book_id = slug(text_path.stem, f"book_{len(books) + 1}")
            try:
                text_chars = len(text_path.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                text_chars = 0
            stat = text_path.stat()
            reviews = []
            review_dir = reviews_dir / book_id
            if review_dir.exists():
                for review_path in sorted(review_dir.glob("*.json"), key=lambda item: item.stat().st_mtime):
                    try:
                        review = read_json(review_path)
                    except Exception:
                        continue
                    if isinstance(review, dict):
                        review.setdefault("review_path", str(review_path.relative_to(library_dir)).replace("\\", "/"))
                        summary = str(review.get("understanding") or review.get("summary") or "")[:900]
                        reviews.append(
                            {
                                "id": str(review.get("id") or review_path.stem),
                                "book_id": book_id,
                                "book_title": str(review.get("book_title") or text_path.stem),
                                "title": str(review.get("title") or review_path.stem),
                                "range": review.get("range") or {},
                                "created_at_ms": int(review.get("created_at_ms") or stat.st_mtime * 1000),
                                "summary": summary,
                                "understanding": summary,
                                "review_path": str(review_path.relative_to(library_dir)).replace("\\", "/"),
                            }
                        )
            books.append(
                {
                    "id": book_id,
                    "title": text_path.stem,
                    "summary": "",
                    "source_path": "",
                    "source_type": "txt",
                    "text_path": str(text_path),
                    "asset_dir": "",
                    "text_chars": text_chars,
                    "cursor": 0,
                    "read_chars": 0,
                    "read_tick_count": 0,
                    "last_read_at_ms": 0,
                    "status": "ready",
                    "tags": [],
                    "warnings": ["由一键修复脚本从残留正文文件重建目录。"],
                    "assets": [],
                    "reviews": reviews[-300:],
                    "created_at_ms": int(stat.st_ctime * 1000),
                    "updated_at_ms": int(stat.st_mtime * 1000),
                    "source": "repair_library_catalog.py",
                }
            )
    return {"version": 1, "updated_at_ms": int(time.time() * 1000), "books": books}


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    library_dir = repo / "observatory" / "outputs" / "agent" / "library"
    catalog = library_dir / "agent_library.json"
    report_lines = [
        "[PA] 图书馆目录修复工具",
        f"[PA] 仓库目录: {repo}",
        f"[PA] 图书馆目录: {library_dir}",
    ]

    library_dir.mkdir(parents=True, exist_ok=True)
    current = None
    current_error = ""
    if catalog.exists():
        try:
            current = read_json(catalog)
        except Exception as exc:
            current_error = str(exc)
    if current is not None and isinstance(current, dict) and current.get("truncated"):
        current_error = "catalog is truncated preview"
        current = None
    if current is not None and book_count(current) > 0:
        report_lines.append(f"[OK] 当前 agent_library.json 可读取，包含 {book_count(current)} 本书。")
        backup = catalog.with_name(catalog.name + ".repair-check.bak")
        shutil.copy2(catalog, backup)
        report_lines.append(f"[OK] 已额外留下检查备份: {backup}")
        compacted, changed_count = compact_catalog_reviews(library_dir, current)
        if changed_count > 0:
            write_json(catalog, compacted)
            report_lines.append(f"[OK] 已整理 {changed_count} 条段落理解：完整正文外置到 library/reviews，目录保留轻量索引。")
        else:
            report_lines.append("[OK] 段落理解索引已经是轻量结构，无需整理。")
    else:
        if current_error:
            report_lines.append(f"[WARN] 当前目录不可用: {current_error}")
        recovered = None
        recovered_from = ""
        for backup in backups_for(catalog):
            try:
                payload = read_json(backup)
            except Exception:
                continue
            if isinstance(payload, dict) and payload.get("truncated"):
                continue
            if book_count(payload) > 0:
                recovered = normalize_catalog(payload)
                recovered_from = str(backup)
                break
        if recovered is None:
            recovered = rebuild_from_files(library_dir)
            recovered_from = "library/books + library/reviews"
        if book_count(recovered) > 0:
            if catalog.exists():
                bad = catalog.with_name(f"{catalog.name}.{time.strftime('%Y%m%d-%H%M%S')}.before-repair.bak")
                shutil.copy2(catalog, bad)
                report_lines.append(f"[OK] 已备份修复前目录: {bad}")
            write_json(catalog, recovered)
            report_lines.append(f"[OK] 已恢复 {book_count(recovered)} 本书。来源: {recovered_from}")
        else:
            report_lines.append("[FAIL] 没有找到可恢复的书籍目录、备份或正文文件。")

    report = library_dir / "repair_report.txt"
    report.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print("\n".join(report_lines))
    print(f"[PA] 修复报告: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

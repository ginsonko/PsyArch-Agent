# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path


def _ensure_repo_root_on_path() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)
    return repo_root


REPO_ROOT = _ensure_repo_root_on_path()

from observatory import agent_runtime as ar


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


def looks_like_default_book_title(value: str) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return True
    return text.startswith("book_") or text in {"book", "untitled", "unknown", "txt"}


def choose_best_book_title(*values: str) -> str:
    fallback = ""
    for raw in values:
        text = str(raw or "").strip()
        if not text:
            continue
        if not fallback:
            fallback = text
        if not looks_like_default_book_title(text):
            return text
    return fallback


def review_dir_candidates(book_id: str, text_stem: str) -> list[str]:
    rows: list[str] = []
    for value in (book_id, text_stem, slug(text_stem, text_stem or "book")):
        text = str(value or "").strip()
        if text and text not in rows:
            rows.append(text)
    return rows


def book_metadata_by_text_path(payload: dict) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for book in [row for row in normalize_catalog(payload).get("books", []) if isinstance(row, dict)]:
        text_path = str(book.get("text_path") or "").strip()
        if text_path:
            rows[str(Path(text_path))] = book
    return rows


def book_metadata_by_id(payload: dict) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for book in [row for row in normalize_catalog(payload).get("books", []) if isinstance(row, dict)]:
        book_id = str(book.get("id") or "").strip()
        if book_id:
            rows[book_id] = book
    return rows


def load_review_summaries(library_dir: Path, keys: list[str], *, default_book_title: str, default_created_at_ms: int) -> list[dict]:
    reviews_dir = library_dir / "reviews"
    rows: list[dict] = []
    seen_paths: set[str] = set()
    for key in keys:
        review_dir = reviews_dir / key
        if not review_dir.exists():
            continue
        for review_path in sorted(review_dir.glob("*.json"), key=lambda item: item.stat().st_mtime):
            resolved = str(review_path.resolve())
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            try:
                review = read_json(review_path)
            except Exception:
                continue
            if not isinstance(review, dict):
                continue
            summary = str(review.get("understanding") or review.get("summary") or "")[:900]
            rows.append(
                {
                    "id": str(review.get("id") or review_path.stem),
                    "book_id": str(review.get("book_id") or ""),
                    "book_title": str(review.get("book_title") or default_book_title),
                    "title": str(review.get("title") or review_path.stem),
                    "range": review.get("range") or {},
                    "created_at_ms": int(review.get("created_at_ms") or default_created_at_ms),
                    "summary": summary,
                    "understanding": summary,
                    "review_path": str(review_path.relative_to(library_dir)).replace("\\", "/"),
                }
            )
    return rows


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


def rebuild_from_files(library_dir: Path, seed_catalog: dict | None = None) -> dict:
    books_dir = library_dir / "books"
    files_dir = library_dir / "files"
    seed_by_text_path = book_metadata_by_text_path(seed_catalog or {})
    seed_by_id = book_metadata_by_id(seed_catalog or {})
    books = []
    seen_ids: set[str] = set()
    if books_dir.exists():
        for text_path in sorted(books_dir.glob("*.txt"), key=lambda item: item.stat().st_mtime, reverse=True):
            book_id = slug(text_path.stem, f"book_{len(books) + 1}")
            seen_ids.add(book_id)
            seeded = seed_by_text_path.get(str(text_path)) or seed_by_id.get(book_id) or {}
            try:
                text_body = text_path.read_text(encoding="utf-8", errors="replace")
                text_chars = len(text_body)
            except Exception:
                text_body = ""
                text_chars = 0
            stat = text_path.stat()
            reviews = load_review_summaries(
                library_dir,
                review_dir_candidates(book_id, text_path.stem),
                default_book_title=str(seeded.get("title") or text_path.stem),
                default_created_at_ms=int(stat.st_mtime * 1000),
            )
            source_path = str(seeded.get("source_path") or "").strip()
            source_name = Path(source_path).stem if source_path else ""
            review_book_title = next((str(item.get("book_title") or "").strip() for item in reviews if str(item.get("book_title") or "").strip()), "")
            title = choose_best_book_title(
                str(seeded.get("title") or ""),
                review_book_title,
                source_name,
                text_path.stem,
                book_id,
            ) or text_path.stem
            summary = str(seeded.get("summary") or "").strip()
            if not summary and text_body.strip():
                summary = ar._short(text_body.strip().replace("\n", " "), 180)
            cursor = max(0, int(seeded.get("cursor") or seeded.get("read_chars") or 0))
            if cursor <= 0:
                range_ends = [int((item.get("range") or {}).get("end") or 0) for item in reviews if isinstance(item, dict)]
                cursor = max(range_ends, default=0)
            cursor = max(0, min(text_chars, cursor))
            last_read_at_ms = max(0, int(seeded.get("last_read_at_ms") or 0))
            if not last_read_at_ms and reviews:
                last_read_at_ms = max(int(item.get("created_at_ms") or 0) for item in reviews)
            warnings = [str(item) for item in seeded.get("warnings", []) if str(item or "").strip()] if isinstance(seeded.get("warnings"), list) else []
            warnings.append("由一键修复脚本从残留正文文件重建目录。")
            books.append(
                {
                    "id": book_id,
                    "title": title,
                    "summary": summary,
                    "source_path": source_path,
                    "source_type": str(seeded.get("source_type") or ("txt" if not source_path else Path(source_path).suffix.lower().lstrip(".") or "file")),
                    "text_path": str(text_path),
                    "asset_dir": str(seeded.get("asset_dir") or ""),
                    "text_chars": text_chars,
                    "cursor": cursor,
                    "read_chars": cursor,
                    "read_tick_count": max(0, int(seeded.get("read_tick_count") or 0)),
                    "last_read_at_ms": last_read_at_ms,
                    "status": str(seeded.get("status") or ("reading" if cursor and cursor < text_chars else "ready")),
                    "tags": [str(item) for item in seeded.get("tags", []) if str(item or "").strip()][:20] if isinstance(seeded.get("tags"), list) else [],
                    "warnings": list(dict.fromkeys(warnings))[:12],
                    "assets": [row for row in seeded.get("assets", [])[:200] if isinstance(row, dict)] if isinstance(seeded.get("assets"), list) else [],
                    "reviews": reviews[-300:],
                    "created_at_ms": int(seeded.get("created_at_ms") or stat.st_ctime * 1000),
                    "updated_at_ms": int(stat.st_mtime * 1000),
                    "source": "repair_library_catalog.py",
                }
            )
    if files_dir.exists():
        extractor = object.__new__(ar.AgentRuntime)
        for source_path in sorted(files_dir.glob("*"), key=lambda item: item.stat().st_mtime, reverse=True):
            if not source_path.is_file():
                continue
            candidate_id = slug(source_path.stem, f"book_{len(books) + 1}")
            if candidate_id in seen_ids:
                continue
            try:
                extracted = ar.AgentRuntime._extract_book_from_path(extractor, source_path, book_id=candidate_id)
            except Exception as exc:
                extracted = {"text": "", "assets": [], "warnings": [f"re-extract failed: {exc}"], "asset_dir": ""}
            text = str(extracted.get("text") or "").replace("\x00", "").strip()
            if not text:
                continue
            book_id = candidate_id
            text_path = books_dir / f"{book_id}.txt"
            suffix = 2
            while text_path.exists():
                book_id = slug(f"{candidate_id}_{suffix}", f"{candidate_id}_{suffix}")
                text_path = books_dir / f"{book_id}.txt"
                suffix += 1
            text_path.parent.mkdir(parents=True, exist_ok=True)
            text_path.write_text(text, encoding="utf-8")
            seen_ids.add(book_id)
            stat = source_path.stat()
            books.append(
                {
                    "id": book_id,
                    "title": source_path.stem,
                    "summary": ar._short(text.replace("\n", " "), 180),
                    "source_path": str(source_path),
                    "source_type": source_path.suffix.lower().lstrip(".") or "file",
                    "text_path": str(text_path),
                    "asset_dir": str(extracted.get("asset_dir") or ""),
                    "text_chars": len(text),
                    "cursor": 0,
                    "read_chars": 0,
                    "read_tick_count": 0,
                    "last_read_at_ms": 0,
                    "status": "ready",
                    "tags": [],
                    "warnings": [f"由一键修复脚本从原始文件 {source_path.name} 重新提取正文。"]
                    + [str(item) for item in extracted.get("warnings", []) if str(item or "").strip()][:8],
                    "assets": [row for row in extracted.get("assets", [])[:200] if isinstance(row, dict)],
                    "reviews": [],
                    "created_at_ms": int(stat.st_ctime * 1000),
                    "updated_at_ms": int(stat.st_mtime * 1000),
                    "source": "repair_library_catalog.py",
                }
            )
    return {"version": 1, "updated_at_ms": int(time.time() * 1000), "books": books}


def merge_missing_books(existing: dict, recovered: dict) -> tuple[dict, int]:
    catalog = normalize_catalog(existing)
    books = [row for row in catalog.get("books", []) if isinstance(row, dict)]
    known_ids = {str(row.get("id") or "") for row in books}
    known_text_paths = {str(row.get("text_path") or "") for row in books if str(row.get("text_path") or "").strip()}
    known_source_paths = {str(row.get("source_path") or "") for row in books if str(row.get("source_path") or "").strip()}
    added = 0
    for row in [item for item in normalize_catalog(recovered).get("books", []) if isinstance(item, dict)]:
        book_id = str(row.get("id") or "")
        text_path = str(row.get("text_path") or "")
        source_path = str(row.get("source_path") or "")
        if book_id and book_id in known_ids:
            continue
        if text_path and text_path in known_text_paths:
            continue
        if source_path and source_path in known_source_paths:
            continue
        books.append(row)
        if book_id:
            known_ids.add(book_id)
        if text_path:
            known_text_paths.add(text_path)
        if source_path:
            known_source_paths.add(source_path)
        added += 1
    books.sort(key=lambda item: (int(item.get("updated_at_ms") or 0), int(item.get("created_at_ms") or 0)), reverse=True)
    catalog["books"] = books
    catalog["updated_at_ms"] = int(time.time() * 1000)
    return catalog, added


def main() -> int:
    repo = REPO_ROOT
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
        rebuilt = rebuild_from_files(library_dir, seed_catalog=compacted)
        compacted, recovered_added = merge_missing_books(compacted, rebuilt)
        if changed_count > 0:
            report_lines.append(f"[OK] 已整理 {changed_count} 条段落理解：完整正文外置到 library/reviews，目录保留轻量索引。")
        else:
            report_lines.append("[OK] 段落理解索引已经是轻量结构，无需整理。")
        if recovered_added > 0:
            report_lines.append(f"[OK] 目录可读取但存在缺失，已从 books/files 残留数据补回 {recovered_added} 本书。")
        if changed_count > 0 or recovered_added > 0:
            write_json(catalog, compacted)
        else:
            report_lines.append("[OK] 当前目录不需要额外修复写回。")
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
            recovered_from = "library/books + library/files + library/reviews"
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

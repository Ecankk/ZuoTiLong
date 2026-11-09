from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .common import (
    descendants,
    first_descendant,
    node_text,
    parse_html_fragment,
    require_revision,
    sha256_bytes,
    sha256_file,
)


SOURCE_ID = "S03"
REPOSITORY = "https://github.com/jlshdsdk/zhangyu-1000t"
KNOWN_REVISION = "19f626daefe25fe0e0d76abc30413b697fe4ce24"
QUESTION_RE = re.compile(
    r'<article\b(?=[^>]*\bclass=["\'][^"\']*\bquestion\b[^"\']*["\'])[^>]*>.*?</article>',
    re.IGNORECASE | re.DOTALL,
)
YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


def _chapter_subject(chapter: int) -> str:
    if 1 <= chapter <= 19:return "高等数学"
    if 20 <= chapter <= 25:return "线性代数"
    if 26 <= chapter <= 31:return "概率论与数理统计"
    if 68 <= chapter <= 71:return "综合"
    if 32 <= chapter <= 49:
        return "高等数学"
    if 50 <= chapter <= 58:
        return "线性代数"
    if 59 <= chapter <= 67:
        return "概率论与数理统计"
    raise ValueError(f"chapter-{chapter:02d} is outside the reviewed 2026 strengthening range 32-67")


def chapter_part(chapter: int) -> str:
    if 1 <= chapter <= 31:return "基础篇"
    if 32 <= chapter <= 67:return "强化篇"
    if 68 <= chapter <= 71:return "综合篇"
    raise ValueError(f"chapter-{chapter:02d} is outside the pinned book")


def _article_record(
    article_html: str,
    *,
    source_file: Path,
    source_file_sha256: str,
    revision: str,
    chapter: int,
    book_title: str,
    edition_claim: str | None,
    chapter_title: str,
    expected_count: int | None,
    math_type: int,
) -> dict[str, Any]:
    root = parse_html_fragment(article_html)
    article = next(descendants(root, tag="article"), None)
    if article is None:
        raise ValueError(f"{source_file}: question fragment has no article element")

    local_number = article.attrs.get("data-no") or article.attrs.get("id", "").removeprefix("q")
    if not local_number.isdigit():
        raise ValueError(f"{source_file}: question has no numeric source-local number")
    number = int(local_number)
    if article.attrs.get("id") not in (None, "", f"q{number}"):
        raise ValueError(f"{source_file}: question id and data-no disagree")

    number_node = first_descendant(article, tag="span", class_name="q-no")
    type_node = first_descendant(article, tag="span", class_name="q-kind")
    stem_node = first_descendant(article, tag="div", class_name="q-stem")
    explanation_node = first_descendant(article, tag="div", class_name="analysis-body")
    answer_node = first_descendant(article, tag="span", class_name="answer-body")
    if number_node and node_text(number_node).isdigit() and int(node_text(number_node)) != number:
        raise ValueError(f"{source_file}: q-no and data-no disagree")

    stem = node_text(stem_node, skip_class="options")
    explanation = node_text(explanation_node)
    options: list[dict[str, str]] = []
    if stem_node:
        for option in descendants(stem_node, tag="span", class_name="opt"):
            key_node = first_descendant(option, tag="b", class_name="opt-key")
            value_node = first_descendant(option, tag="span", class_name="opt-val")
            key = node_text(key_node).strip("()（） ")
            value = node_text(value_node)
            if key or value:
                options.append({"key": key, "value": value})

    image_refs = [
        node.attrs["src"]
        for node in descendants(article, tag="img")
        if node.attrs.get("src")
    ]
    answer = node_text(answer_node) or None
    if not stem:
        raise ValueError(f"{source_file}: q{number} has an empty stem")
    if not explanation and chapter_part(chapter)=="强化篇":
        raise ValueError(f"{source_file}: q{number} has no explanation block")

    relative_file = source_file.as_posix()
    locator = f"{relative_file}#q{number}"
    fragment_hash = sha256_bytes(article_html.encode("utf-8"))
    book_id = f"xb-s03-{revision[:8]}-c{chapter:02d}-q{number:03d}"
    return {
        "schema": "mathlens.extra-bank-staging/v1",
        "bank_id": book_id,
        "source": {
            "source_id": SOURCE_ID,
            "repository": REPOSITORY,
            "revision": revision,
            "source_uid": locator,
            "source_file": relative_file,
            "source_file_sha256": source_file_sha256,
            "source_fragment_sha256": fragment_hash,
            "source_question_number": number,
        },
        "identity": {
            "kind": "book_exercise",
            "book_title_claimed": book_title,
            "book_identity_status": "claimed_by_upstream_page",
            "edition_label_claimed": edition_claim,
            "edition_verified_against_print": False,
            "math_types_applicable": [math_type],
            "part": chapter_part(chapter),
            "book_group": None,
            "requested_b_group_mapping": "unverified_for_this_book_title_and_printing",
            "book_question_number": None,
            "chapter_local_number": number,
            "source_chapter": chapter,
            "chapter_title": chapter_title,
            "subject": _chapter_subject(chapter),
            "exam_year": None,
            "printed_page": None,
        },
        "content": {
            "stem": stem,
            "options": options,
            "answer": answer,
            "explanation": explanation,
            "source_fragment_html": article_html,
            "illustrations": image_refs,
        },
        "availability": {
            "stem_present": bool(stem),
            "illustrations_present": bool(image_refs),
            "answer_state": "explicit_final_answer" if answer else "not_separately_present",
            "explanation_present": bool(explanation),
            "math_review_status": "not_reviewed",
        },
        "upstream": {
            "display_question_number": node_text(number_node) or str(number),
            "question_type": node_text(type_node) or None,
            "chapter_expected_question_count": expected_count,
        },
    }


def adapt_zhangyu(
    source_root: Path,
    revision: str = KNOWN_REVISION,
    *,
    chapters: range | tuple[int, ...] = range(32, 68),
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Create staging records from explicitly labelled pinned book chapters."""
    revision = require_revision(revision)
    source_root = Path(source_root)
    root_index = source_root / "index.html"
    if not root_index.is_file():
        raise FileNotFoundError(f"missing upstream index: {root_index}")
    index_text = root_index.read_text(encoding="utf-8")
    title_match = re.search(r"<title>(.*?)</title>", index_text, re.IGNORECASE | re.DOTALL)
    book_title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""
    year_match = YEAR_RE.search(book_title)
    edition_claim = year_match.group(1) if year_match else None
    math_type = 1 if "数学一" in book_title or "数学一" in index_text else 0
    if not book_title or math_type != 1:
        raise ValueError("index does not identify the claimed book title and 数学一 scope")

    records: list[dict[str, Any]] = []
    for chapter in chapters:
        chapter_file = source_root / "chapters" / f"chapter-{chapter:02d}.html"
        if not chapter_file.is_file():
            raise FileNotFoundError(f"missing reviewed strengthening chapter: {chapter_file}")
        source = chapter_file.read_text(encoding="utf-8")
        part=chapter_part(chapter)
        chapter_hash = sha256_file(chapter_file)
        document = parse_html_fragment(source)
        title_node = first_descendant(document, tag="div", class_name="top-title")
        header = node_text(title_node)
        if not re.match('^'+part+r'\s*[·・]',header):raise ValueError(f"{chapter_file}: page is not explicitly marked {part}")
        chapter_title = re.sub('^'+part+r"\s*[·・]\s*", "", header)
        chapter_title = re.sub(r"[（(]\s*\d+\s*题[）)]\s*$", "", chapter_title).strip()
        count_match = re.search(r"[（(](\d+)题[）)]", header)
        expected_count = int(count_match.group(1)) if count_match else None

        matches = list(QUESTION_RE.finditer(source))
        local_numbers: set[int] = set()
        for match in matches:
            record = _article_record(
                match.group(0),
                source_file=Path("chapters") / chapter_file.name,
                source_file_sha256=chapter_hash,
                revision=revision,
                chapter=chapter,
                book_title=book_title,
                edition_claim=edition_claim,
                chapter_title=chapter_title,
                expected_count=expected_count,
                math_type=math_type,
            )
            question_number = record["identity"]["chapter_local_number"]
            if question_number in local_numbers:
                raise ValueError(f"{chapter_file}: duplicate source-local question number {question_number}")
            local_numbers.add(question_number)
            records.append(record)
            if limit is not None and len(records) >= limit:
                return records

        if expected_count is not None and len(matches) != expected_count:
            raise ValueError(
                f"{chapter_file}: page declares {expected_count} questions but contains {len(matches)} question blocks"
            )
    return records

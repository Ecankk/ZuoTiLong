from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from .common import canonical_json_sha256, require_revision, sha256_file


SOURCE_ID = "S02"
REPOSITORY = "https://github.com/diamond-pickaxe/cxy-daguan"
KNOWN_REVISION = "7e79423253454dfb32246b6a84c7d6fd6efaa5b8"
ASSET_REF_RE = re.compile(r"^asset://sha256/([0-9a-f]{64})$")
YEAR_RE = re.compile(r"(?P<year>(?:19|20)\d{2})")
MATH_TYPE_RE = re.compile(r"(?:数学|数)\s*([一二三])")
COMBINED_MATH_TYPES_RE = re.compile(r"(?:数学|数)\s*一\s*二\s*三")
GENERIC_EXAM_RE = re.compile(
    r"(?P<year>(?:19|20)\d{2})\s*年?\s*(?:全国\s*)?(?:考研(?:数学)?|数学)?\s*真题(?!同源)"
)
BOOK_MARKERS = (
    ("武忠祥基础", "严选", "武忠祥基础篇严选"),
    ("武忠祥强化", "严选", "武忠祥强化篇严选"),
    ("武忠祥", "严选", "武忠祥严选"),
    ("张宇", "1000", "张宇1000候选"),
    ("李林六套", None, "李林六套卷"),
    ("李林四套", None, "李林四套卷"),
    ("李林880", None, "李林880候选"),
    ("李艳芳", "三套", "李艳芳三套卷"),
    ("合工大超越", None, "合工大超越模拟卷"),
    ("合工大共创", None, "合工大共创模拟卷"),
    ("押题王", "六套", "押题王六套卷"),
    ("方浩", "三套", "方浩三套卷"),
    ("王普", "三套", "王普三套卷"),
    ("周洋鑫", "四套", "周洋鑫四套卷"),
    ("欧几里得", "三套", "欧几里得三套卷"),
    ("张宇八套", None, "张宇八套卷"),
    ("张宇30讲", None, "张宇30讲"),
    ("张宇线代9讲", None, "张宇线代9讲"),
    ("0.9k", None, "0.9k来源（作者未确认）"),
    ("0.66k", None, "0.66k来源（作者未确认）"),
    ("1k", None, "1000题候选"),
    ("0.88k", None, "0.88k来源（李林880候选，版本未核）"),
    ("880", None, "880来源（作者/版本待核）"),
    ("姜晓千真题同源150", None, "姜晓千《真题同源150》练习集"),
    ("真题同源150", None, "《真题同源150》练习集"),
    ("姜晓千强化例题", None, "姜晓千强化例题"),
    ("姜晓千基础例题", None, "姜晓千基础例题"),
    ("李正元全书例题", None, "李正元全书例题"),
    ("李正元例题", None, "李正元例题"),
    ("李永乐线代辅导讲义", None, "李永乐线代辅导讲义"),
    ("李永乐六套", None, "李永乐六套卷"),
    ("余炳森五套", None, "余炳森五套卷"),
    ("汤家凤五套", None, "汤家凤五套卷"),
    ("Euclid模考", None, "Euclid模考卷"),
    ("郭伟模考", None, "郭伟模考卷"),
    ("郭伟强化45讲", None, "郭伟强化45讲"),
    ("108考点", None, "108考点"),
    ("1800题", None, "1800题"),
    ("复习全书（红）", None, "复习全书（红）"),
    ("魔法练习册", None, "魔法练习册"),
    ("线岱杨强化例题", None, "线岱杨强化例题"),
    ("基础例题", None, "基础例题"),
    ("李林", None, "李林资料候选"),
)
CHINESE_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}


def _chapter_value(text: str) -> int | None:
    if text.isdigit():
        return int(text)
    total = 0
    section = 0
    digit = 0
    for char in text:
        if char in CHINESE_DIGITS:
            digit = CHINESE_DIGITS[char]
        elif char in {"十", "百"}:
            unit = 10 if char == "十" else 100
            section += (digit or 1) * unit
            digit = 0
        else:
            return None
    value = total + section + digit
    return value or None


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _lineage_segments(question: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("source", "original_source", "source_details"):
        value = question.get(key)
        if isinstance(value, str):
            values.extend(re.split(r"[;；]", value))
    tags = question.get("source_tags")
    if isinstance(tags, list):
        values.extend(str(item) for item in tags)
    return _unique(values)


def _claims(segments: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    exams: list[dict[str, Any]] = []
    books: list[dict[str, Any]] = []
    for segment in segments:
        years = list(YEAR_RE.finditer(segment))
        for index, year_match in enumerate(years):
            year = int(year_match.group("year"))
            end = years[index + 1].start() if index + 1 < len(years) else len(segment)
            claim_text = segment[year_match.start():end]
            combined_match = COMBINED_MATH_TYPES_RE.search(claim_text)
            combined_numbers: dict[int, list[int]] = {1: [], 2: [], 3: []}
            if combined_match:
                suffix = claim_text[combined_match.end():]
                for number_match in re.finditer(r"([一二三])\s*(\d{1,2})", suffix):
                    math_type = {"一": 1, "二": 2, "三": 3}[number_match.group(1)]
                    combined_numbers[math_type].append(int(number_match.group(2)))
                math_types = (1, 2, 3)
            else:
                math_types = tuple(
                    dict.fromkeys(
                        {"一": 1, "二": 2, "三": 3}[match.group(1)]
                        for match in MATH_TYPE_RE.finditer(claim_text)
                    )
                )
            if not math_types:
                generic_exam = next(
                    (item for item in GENERIC_EXAM_RE.finditer(segment) if int(item.group("year")) == year),
                    None,
                )
                if generic_exam:
                    math_types = (None,)

            for math_type in math_types:
                if combined_match:
                    claimed_numbers = combined_numbers.get(math_type, [])
                else:
                    number_match = re.search(r"第\s*(\d{1,2})\s*题", claim_text)
                    if number_match is None:
                        number_match = re.search(r"[（(]\s*(\d{1,2})\s*[)）]", claim_text)
                    claimed_numbers = [int(number_match.group(1))] if number_match else []
                claim = next(
                    (
                        item for item in exams
                        if item["year_claimed"] == year and item["math_type_claimed"] == math_type
                    ),
                    None,
                )
                if claim is None:
                    claim = {
                        "year_claimed": year,
                        "math_type_claimed": math_type,
                        "question_number_claimed": None,
                        "question_numbers_claimed": [],
                        "raw_segments": [],
                        "verified_as_original_exam": False,
                    }
                    exams.append(claim)
                for claimed_number in claimed_numbers:
                    if claimed_number not in claim["question_numbers_claimed"]:
                        claim["question_numbers_claimed"].append(claimed_number)
                if segment not in claim["raw_segments"]:
                    claim["raw_segments"].append(segment)

        label = None
        for marker, required, candidate_label in BOOK_MARKERS:
            if marker.lower() in segment.lower() and (required is None or required in segment):
                label = candidate_label
                break
        if not label:
            continue

        chapter = re.search(r"第\s*(\d+|[零〇一二两三四五六七八九十百]+)\s*章", segment)
        number = re.search(r"(?:第\s*)?(\d+(?:-\d+)?)\s*题", segment)
        group = re.search(r"([ABC])\s*组", segment, re.IGNORECASE)
        edition = re.search(r"(20\d{2}|\d{2})\s*版", segment)
        claim = {
            "book_claim": label,
            "edition_label_claimed": edition.group(1) if edition else None,
            "chapter_claimed": _chapter_value(chapter.group(1)) if chapter else None,
            "group_claimed": group.group(1).upper() if group else None,
            "question_number_claimed": number.group(1) if number else None,
            "raw_segments": [],
            "verified_against_print": False,
        }
        existing = next(
            (
                item for item in books
                if all(item[key] == claim[key] for key in (
                    "book_claim", "edition_label_claimed", "chapter_claimed",
                    "group_claimed", "question_number_claimed",
                ))
            ),
            None,
        )
        if existing is None:
            existing = claim
            books.append(existing)
        if segment not in existing["raw_segments"]:
            existing["raw_segments"].append(segment)
    typed_exam_years = {
        claim["year_claimed"] for claim in exams if claim["math_type_claimed"] is not None
    }
    exams = [
        claim for claim in exams
        if claim["math_type_claimed"] is not None or claim["year_claimed"] not in typed_exam_years
    ]
    for claim in exams:
        claim["question_numbers_claimed"].sort()
        if len(claim["question_numbers_claimed"]) == 1:
            claim["question_number_claimed"] = claim["question_numbers_claimed"][0]
    return exams, books


def _asset_records(question: dict[str, Any], asset_map: dict[str, str], source_root: Path) -> list[dict[str, Any]]:
    document = question.get("document") or {}
    refs = document.get("asset_refs") or []
    result = []
    for ref in refs:
        ref = str(ref)
        uri_match = ASSET_REF_RE.fullmatch(ref)
        mapped = asset_map.get(ref)
        relative = None
        exists = False
        checksum_ok = False
        if mapped:
            relative = PurePosixPath("public", mapped.lstrip("/"))
            candidate = source_root.joinpath(*relative.parts).resolve()
            try:
                candidate.relative_to(source_root.resolve())
            except ValueError:
                candidate = None
            if candidate is not None:
                exists = candidate.is_file()
                checksum_ok = bool(exists and uri_match and sha256_file(candidate) == uri_match.group(1))
        result.append({
            "asset_ref": ref,
            "declared_sha256": uri_match.group(1) if uri_match else None,
            "source_relative_path": relative.as_posix() if relative else None,
            "exists": exists,
            "sha256_matches_ref": checksum_ok,
        })
    return result


def adapt_cxy(
    source_root: Path,
    revision: str = KNOWN_REVISION,
    *,
    question_ids: set[int] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Convert cxy-daguan JSON rows without collapsing mixed source lineage."""
    revision = require_revision(revision)
    source_root = Path(source_root)
    data_file = source_root / "library" / "bundled-library.json"
    if not data_file.is_file():
        raise FileNotFoundError(f"missing upstream library: {data_file}")
    data_bytes = data_file.read_bytes()
    data_sha = hashlib.sha256(data_bytes).hexdigest()
    root = json.loads(data_bytes.decode("utf-8"))
    questions = root.get("questions")
    asset_map = root.get("assetMap") or {}
    if not isinstance(questions, list) or not isinstance(asset_map, dict):
        raise ValueError("bundled-library.json does not have the expected questions/assetMap structure")

    if question_ids is not None:
        known_ids = {int(item["id"]) for item in questions if "id" in item}
        unknown_ids = question_ids - known_ids
        if unknown_ids:
            raise ValueError(f"unknown source question IDs: {sorted(unknown_ids)}")

    records: list[dict[str, Any]] = []
    for question in questions:
        try:
            source_uid = int(question["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("upstream row has no integer id") from exc
        if question_ids is not None and source_uid not in question_ids:
            continue

        document = question.get("document") or {}
        stem = question.get("stem") or document.get("stem_md") or ""
        answer_obj = question.get("answer") or document.get("answer") or {}
        answer = question.get("correct_answer") or answer_obj.get("reference_answer_md") or ""
        explanation = question.get("answer_explanation") or document.get("explanation_md") or ""
        segments = _lineage_segments(question)
        year_type_claims, book_claims = _claims(segments)
        category_path = question.get("category_full_path") or document.get("category_full_path")
        exam_source_evidence: list[dict[str, Any]] = []
        exam_years: set[int] = set()
        for segment in segments:
            for match in GENERIC_EXAM_RE.finditer(segment):
                year = int(match.group("year"))
                exam_years.add(year)
                evidence = {"kind": "year_exam_source_label", "year_claimed": year, "raw_segment": segment}
                if evidence not in exam_source_evidence:
                    exam_source_evidence.append(evidence)
        history_exam_path = isinstance(category_path, str) and "历年真题" in category_path
        if history_exam_path:
            path_years = sorted({int(match.group("year")) for match in YEAR_RE.finditer(category_path)})
            if path_years:
                exam_source_evidence.extend({
                    "kind": "upstream_historical_exam_category",
                    "year_claimed": year,
                    "category_path": category_path,
                } for year in path_years)
            else:
                exam_source_evidence.append({
                    "kind": "upstream_historical_exam_category",
                    "category_path": category_path,
                })
        exam_claims = [
            claim for claim in year_type_claims
            if claim["year_claimed"] in exam_years or history_exam_path
        ]
        year_type_source_claims = [claim for claim in year_type_claims if claim not in exam_claims]
        assets = _asset_records(question, asset_map, source_root)
        applicable = question.get("exam_subjects") or document.get("exam_subjects") or []
        upstream_record_hash = canonical_json_sha256(question)
        record = {
            "schema": "mathlens.extra-bank-staging/v1",
            "bank_id": f"xb-s02-{revision[:8]}-{source_uid}",
            "source": {
                "source_id": SOURCE_ID,
                "repository": REPOSITORY,
                "revision": revision,
                "source_uid": str(source_uid),
                "source_file": "library/bundled-library.json",
                "source_file_sha256": data_sha,
                "source_record_sha256": upstream_record_hash,
            },
            "identity": {
                "kind": "mixed_catalog_record",
                "source_identity_status": "review_required" if len(segments) > 1 or exam_source_evidence else "upstream_label_only",
                "lineage_conflict_or_multiple_claims": len(segments) > 1 or len(exam_claims) + len(book_claims) > 1,
                "raw_source": question.get("source"),
                "raw_original_source": question.get("original_source"),
                "raw_source_details": question.get("source_details"),
                "raw_source_tags": question.get("source_tags") or [],
                "lineage_segments": segments,
                "exam_claims": exam_claims,
                "book_claims": book_claims,
                "year_type_source_claims": year_type_source_claims,
                "exam_source_evidence": exam_source_evidence,
                "upstream_serial_number": question.get("serial_number"),
                "printed_page": document.get("source_page", question.get("source_page")),
                "math_types_applicable_claimed": list(applicable),
                "exam_year": None,
                "math_type": None,
            },
            "content": {
                "stem": stem,
                "options": question.get("options") or document.get("options") or [],
                "answer": answer or None,
                "explanation": explanation or None,
                "illustrations": assets,
                "upstream_content_hash": question.get("content_hash"),
                "upstream_category_path": question.get("category_full_path"),
                "question_type": question.get("question_type") or document.get("question_type"),
            },
            "availability": {
                "stem_present": bool(stem.strip()) if isinstance(stem, str) else bool(stem),
                "answer_present": bool(answer),
                "explanation_present": bool(explanation),
                "illustrations_expected": len(assets),
                "illustrations_resolved": sum(item["exists"] and item["sha256_matches_ref"] for item in assets),
                "math_review_status": "not_reviewed",
            },
            "upstream": {
                "upstream_id": source_uid,
                "category_id": question.get("category_id") or document.get("category_id"),
                "category_full_path": category_path,
                "exam_subjects": list(applicable),
                "format_version": document.get("format_version"),
            },
        }
        records.append(record)
        if limit is not None and len(records) >= limit:
            break
    return records

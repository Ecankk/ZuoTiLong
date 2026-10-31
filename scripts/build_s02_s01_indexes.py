from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any


GROUPS = {1: "数学一", 2: "数学二", 3: "数学三"}
YEAR_RANGE = (2009, 2025)
TOPIC_ROOTS = {"高等数学", "线性代数", "概率统计", "概率论", "概率论与数理统计"}
MATH_SCOPE_LABELS = {"数一", "数二", "数三", "数学一", "数学二", "数学三"}

TAG_LABELS = {
    "0.88k": "李林880候选（版本未核）",
    "0.9k": "0.9k题库来源（作者/版本待核）",
    "0.66k": "0.66k题库来源（作者/版本待核）",
    "1k": "1000题来源（作者/版本待核）",
    "张宇八套": "张宇八套卷（版本待核）",
    "姜晓千真题同源150": "姜晓千《真题同源150》练习集",
    "姜晓千强化例题": "姜晓千强化例题",
    "姜晓千基础例题": "姜晓千基础例题",
    "李艳芳三套": "李艳芳三套卷",
    "张宇30讲": "张宇30讲",
    "姜晓千基础例题": "姜晓千基础例题",
    "武忠祥基础严选": "武忠祥基础篇严选",
    "武忠祥强化严选": "武忠祥强化篇严选",
    "Euclid模考": "Euclid模拟卷",
    "李永乐六套": "李永乐六套卷",
    "108考点": "108考点",
    "李林六套": "李林六套卷",
    "魔法练习册": "魔法练习册",
    "复习全书（红）": "复习全书（红）",
    "余丙森五套": "余炳森五套卷",
    "李林四套": "李林四套卷",
    "1800题": "1800题来源（作者/版本待核）",
    "张宇线代9讲": "张宇线代9讲",
    "武忠祥严选": "武忠祥严选（篇章待核）",
    "真题同源150": "《真题同源150》练习集（原作者待核）",
    "郭伟模考": "郭伟模拟卷",
    "线岱杨强化例题": "线岱杨强化例题",
    "汤家凤五套": "汤家凤五套卷",
    "李正元全书例题": "李正元全书例题",
    "李永乐线代辅导讲义": "李永乐线代辅导讲义",
    "郭伟强化45讲": "郭伟强化45讲",
    "基础例题": "基础例题（作者待核）",
    "竞赛题": "数学竞赛题（非全国统考真题）",
}

BOOK_LABELS = {
    "0.88k来源（李林880候选，版本未核）": "李林880候选（版本未核）",
    "880来源（作者/版本待核）": "880题来源（作者待核）",
    "李林880候选": "李林880候选（版本未核）",
    "1000题候选": "1000题来源（作者/版本待核）",
    "张宇1000候选": "张宇1000题候选（版本待核）",
    "李林资料候选": "李林资料（具体系列待核）",
    "武忠祥严选": "武忠祥严选（篇章待核）",
    "武忠祥基础篇严选": "武忠祥基础篇严选",
    "武忠祥强化篇严选": "武忠祥强化篇严选",
    "张宇八套卷": "张宇八套卷（版本待核）",
    "张宇30讲": "张宇30讲",
    "张宇线代9讲": "张宇线代9讲",
    "李林六套卷": "李林六套卷",
    "李林四套卷": "李林四套卷",
    "李艳芳三套卷": "李艳芳三套卷",
    "合工大超越模拟卷": "合工大超越模拟卷",
    "合工大共创模拟卷": "合工大共创模拟卷",
    "押题王六套卷": "押题王六套卷",
    "方浩三套卷": "方浩三套卷",
    "王普三套卷": "王普三套卷",
    "周洋鑫四套卷": "周洋鑫四套卷",
    "欧几里得三套卷": "欧几里得三套卷",
    "余炳森五套卷": "余炳森五套卷",
    "汤家凤五套卷": "汤家凤五套卷",
    "李永乐六套卷": "李永乐六套卷",
    "李永乐线代辅导讲义": "李永乐线代辅导讲义",
    "108考点": "108考点",
    "1800题": "1800题来源（作者/版本待核）",
    "姜晓千《真题同源150》练习集": "姜晓千《真题同源150》练习集（练习题来源）",
    "《真题同源150》练习集": "《真题同源150》练习集（练习题来源）",
    "姜晓千强化例题": "姜晓千强化例题",
    "姜晓千基础例题": "姜晓千基础例题",
    "李正元全书例题": "李正元全书例题",
    "李正元例题": "李正元例题",
    "Euclid模考卷": "Euclid模拟卷",
    "郭伟模考卷": "郭伟模拟卷",
    "郭伟强化45讲": "郭伟强化45讲",
    "复习全书（红）": "复习全书（红）",
    "魔法练习册": "魔法练习册",
    "线岱杨强化例题": "线岱杨强化例题",
    "基础例题": "基础例题（作者待核）",
}

SOURCE_PATTERNS = (
    (re.compile(r"武忠祥\s*基础\s*严选"), "武忠祥基础篇严选"),
    (re.compile(r"武忠祥\s*强化\s*严选"), "武忠祥强化篇严选"),
    (re.compile(r"武忠祥.*严选"), "武忠祥严选（篇章待核）"),
    (re.compile(r"(?:0\.88k|李林\s*880)"), "李林880候选（版本未核）"),
    (re.compile(r"(?<!\d)880题"), "880题来源（作者待核）"),
    (re.compile(r"0\.9k"), "0.9k题库来源（作者/版本待核）"),
    (re.compile(r"0\.66k"), "0.66k题库来源（作者/版本待核）"),
    (re.compile(r"(?<![A-Za-z])1k(?![A-Za-z])"), "1000题来源（作者/版本待核）"),
    (re.compile(r"张宇.{0,8}1000|张宇1000"), "张宇1000题候选（版本待核）"),
    (re.compile(r"张宇.{0,8}八套|张宇.{0,8}四套|张宇.{0,8}套卷"), "张宇套卷（具体系列见原始来源）"),
    (re.compile(r"张宇\s*30讲"), "张宇30讲"),
    (re.compile(r"张宇线代9讲"), "张宇线代9讲"),
    (re.compile(r"李林.{0,6}六套"), "李林六套卷"),
    (re.compile(r"李林.{0,6}四套"), "李林四套卷"),
    (re.compile(r"李艳芳.{0,8}三套"), "李艳芳三套卷"),
    (re.compile(r"合工大.{0,8}超越"), "合工大超越模拟卷"),
    (re.compile(r"合工大.{0,8}共创"), "合工大共创模拟卷"),
    (re.compile(r"押题王.{0,8}六套"), "押题王六套卷"),
    (re.compile(r"方浩.{0,8}三套"), "方浩三套卷"),
    (re.compile(r"王普.{0,8}三套"), "王普三套卷"),
    (re.compile(r"周洋鑫.{0,8}四套"), "周洋鑫四套卷"),
    (re.compile(r"(?:欧几里得|Euclid).{0,8}(?:三套|模考)"), "欧几里得/Euclid模拟卷"),
    (re.compile(r"余炳森.{0,8}五套"), "余炳森五套卷"),
    (re.compile(r"汤家凤.{0,8}五套"), "汤家凤五套卷"),
    (re.compile(r"李永乐.{0,8}六套"), "李永乐六套卷"),
    (re.compile(r"李永乐.{0,8}线代.{0,8}讲义"), "李永乐线代辅导讲义"),
    (re.compile(r"姜晓千.{0,12}真题同源150"), "姜晓千《真题同源150》练习集（练习题来源）"),
    (re.compile(r"真题同源150"), "《真题同源150》练习集（练习题来源）"),
    (re.compile(r"姜晓千.{0,10}强化例题"), "姜晓千强化例题"),
    (re.compile(r"姜晓千.{0,10}基础例题"), "姜晓千基础例题"),
    (re.compile(r"李正元.{0,10}全书.{0,8}例题"), "李正元全书例题"),
    (re.compile(r"李正元.{0,8}例题"), "李正元例题"),
    (re.compile(r"郭伟.{0,10}45讲"), "郭伟强化45讲"),
    (re.compile(r"郭伟.{0,8}模考"), "郭伟模拟卷"),
    (re.compile(r"108考点"), "108考点"),
    (re.compile(r"1800题"), "1800题来源（作者/版本待核）"),
    (re.compile(r"复习全书.{0,4}红"), "复习全书（红）"),
    (re.compile(r"魔法练习册"), "魔法练习册"),
    (re.compile(r"竞赛题|竞赛"), "数学竞赛题（非全国统考真题）"),
    (re.compile(r"经典题"), "经典题（作者/出处待核）"),
)

SOURCE_LABEL_ALIASES = {
    "0.66k来源（作者未确认）": "0.66k题库来源（作者/版本待核）",
    "0.9k来源（作者未确认）": "0.9k题库来源（作者/版本待核）",
    "《真题同源150》练习集（练习题来源）": "《真题同源150》练习集（原作者待核）",
    "姜晓千《真题同源150》练习集（练习题来源）": "姜晓千《真题同源150》练习集",
    "李林880候选（S02标记0.88k，版本未核）": "李林880候选（版本未核）",
}

MANUAL_S01_CHECKS = {
    ("7896", 2025, 1, 5): "S01 数学一 2025 Q5 与 S02 UID 7896 为同一二次型题。S01 的答案是 B=1，S02 的选项 A=1；两边选项顺序不同，数学答案一致。已对照 S01 题图、解析和 S02 解析。",
    ("8053", 2023, 3, 5): "S01 数学三 2023 Q5 与 S02 UID 8053 为同一伴随矩阵题。S01 的答案是 B，S02 的答案是 D；两边对应矩阵表达式相同，选项顺序不同。已对照 S01 题图、解析和 S02 解析。",
    ("8053", 2023, 2, 8): "S01 数学二 2023 Q8 与 S02 UID 8053 为同一伴随矩阵题。两边答案均为 D，题干与解法相符。已对照 S01 题图、解析和 S02 解析。",
}

MANUAL_S02_MATH_CHECKS = {
    "1088": {
        "status": "answer_manually_checked",
        "note": "已查看图资源并手算两块面积均为 b^3/12，答案 B 正确。此记录不代表同来源其他题已核验。",
    },
    "2314": {
        "status": "answer_manually_checked_source_unresolved",
        "note": "已手算曲线围成面积为 3/2，与解析一致；1987 数一、李林880、武忠祥严选来源主张仍冲突未解。",
    },
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def _canonical_book_label(label: str, identity: dict[str, Any]) -> str:
    normalized = BOOK_LABELS.get(label, label)
    raw_text = " ".join(str(identity.get(key) or "") for key in (
        "raw_source", "raw_original_source", "raw_source_details"
    ))
    if label == "880来源（作者/版本待核）":
        if "0.88k" in raw_text or "李林880" in raw_text or "李林 880" in raw_text:
            return "李林880候选（版本未核）"
    return normalized


def _source_labels(identity: dict[str, Any], category_path: str | None) -> list[str]:
    labels: set[str] = set()
    tags = [str(tag).strip() for tag in identity.get("raw_source_tags") or []]
    for tag in tags:
        if re.fullmatch(r"(?:19|20)\d{2}年真题", tag):
            continue
        labels.add(TAG_LABELS.get(tag, tag))
    for claim in identity.get("book_claims") or []:
        labels.add(_canonical_book_label(str(claim.get("book_claim") or ""), identity))
    lineage_text = "\n".join(identity.get("lineage_segments") or [])
    for pattern, label in SOURCE_PATTERNS:
        if pattern.search(lineage_text):
            labels.add(label)
    labels = {SOURCE_LABEL_ALIASES.get(label, label) for label in labels}

    # Prefer a specific author/title over the generic aliases that often appear beside it.
    specific = set(labels)
    if any(label.startswith("李林880候选") or label == "李林六套卷" or label == "李林四套卷" for label in specific):
        labels.discard("李林资料（具体系列待核）")
        labels.discard("880题来源（作者待核）")
    if "张宇1000题候选（版本待核）" in specific:
        labels.discard("1000题来源（作者/版本待核）")
    if "姜晓千《真题同源150》练习集" in specific:
        labels.discard("《真题同源150》练习集（原作者待核）")
        labels.discard("《真题同源150》练习集（练习题来源）")
    if "姜晓千基础例题" in specific:
        labels.discard("基础例题（作者待核）")
    if "武忠祥基础篇严选" in specific or "武忠祥强化篇严选" in specific:
        labels.discard("武忠祥严选（篇章待核）")
    if "张宇八套卷（版本待核）" in specific:
        labels.discard("张宇套卷（具体系列见原始来源）")
    if "李正元全书例题" in specific:
        labels.discard("李正元例题")
    if "欧几里得三套卷" in specific:
        labels.discard("欧几里得/Euclid模拟卷")

    if not labels:
        first_level = (category_path or "").split(" / ", 1)[0]
        if first_level == "模拟卷":
            labels.add("模拟卷（系列未归并，原文保留）")
        elif "竞赛" in lineage_text:
            labels.add("数学竞赛题（非全国统考真题）")
        elif lineage_text.strip():
            labels.add("来源待归并（见原始来源字段）")
        else:
            labels.add("来源缺失待补")
    return sorted(label for label in labels if label)


def _question_type(record: dict[str, Any]) -> int | None:
    kind = str(record["content"].get("question_type") or "").lower()
    if any(token in kind for token in ("single_choice", "choice", "选择")):
        return 1
    if kind in {"subjective", "fill_blank", "填空", "解答"} or kind:
        return 2
    return None


def _normalize_chapter_part(part: str) -> str:
    """Drop exam-scope notes from chapter labels while preserving the raw path."""
    normalized = re.sub(
        r"[（(]\s*(?:仅\s*)?(?:数学|数)[一二三]+(?:[、和及/]\s*(?:数学|数)[一二三]+)*\s*[）)]$",
        "",
        part.strip(),
    ).strip()
    if re.fullmatch(r"(?:数学|数)[一二三]+专项", normalized):
        return ""
    return normalized


def _chapter_tags(topic_path: str | None) -> tuple[list[str], list[str], str]:
    """Return S01-like chapter tags, non-chapter source context tags, and status."""
    if not topic_path:
        return [], ["chapter:待标注"], "missing"
    parts = [
        normalized
        for part in topic_path.split(" / ")
        if (normalized := _normalize_chapter_part(part))
    ]
    if parts and parts[0] in TOPIC_ROOTS:
        compact: list[str] = []
        for part in parts:
            if not compact or compact[-1] != part:
                compact.append(part)
        chapter_tags = [
            f"chapter:{' / '.join(compact[:depth])}"
            for depth in range(1, len(compact) + 1)
        ]
        return chapter_tags, [], "tagged"
    if parts and parts[0] == "模拟卷":
        context = [part for part in parts if part not in MATH_SCOPE_LABELS]
        context_tags = ["material:模拟卷"]
        if context:
            context_tags.append(f"source_context:{' / '.join(context)}")
        return [], context_tags, "source_path_only"
    return [], [f"topic_path:{topic_path}"], "unmapped_path"


def _source_review_label(identity: dict[str, Any]) -> str:
    status = identity.get("source_identity_status")
    if status == "review_required":
        return "待核来源身份"
    if status == "upstream_label_only":
        return "仅有上游来源标签"
    return "来源状态未知"


def _s01_indexes(s01_root: Path) -> dict[tuple[int, int, int], dict[str, Any]]:
    result: dict[tuple[int, int, int], dict[str, Any]] = {}
    for math_type, group in GROUPS.items():
        index_file = s01_root / "kaoyan_math_images" / group / "answers.json"
        data = json.loads(index_file.read_text(encoding="utf-8"))
        for key, row in data.items():
            result[(math_type, int(row["paper"]), int(row["index"]))] = {"key": key, **row}
    return result


def _s01_crosswalk(
    records: list[dict[str, Any]], s01_root: Path, lookup: dict[tuple[int, int, int], dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[tuple[str, int, int, int], dict[str, Any]]]:
    crosswalk: list[dict[str, Any]] = []
    by_claim: dict[tuple[str, int, int, int], dict[str, Any]] = {}
    for record in records:
        uid = str(record["source"]["source_uid"])
        for claim in record["identity"].get("exam_claims") or []:
            math_type = claim.get("math_type_claimed")
            numbers = claim.get("question_numbers_claimed") or []
            if math_type not in GROUPS or len(numbers) != 1:
                continue
            year, number = int(claim["year_claimed"]), int(numbers[0])
            if not YEAR_RANGE[0] <= year <= YEAR_RANGE[1]:
                continue
            s01 = lookup.get((math_type, year, number))
            if not s01:
                continue
            prefix = f"Q{number:02d}_id{s01['question_id']}"
            group_path = PurePosixPath("kaoyan_math_images", GROUPS[math_type], str(year))
            s01_answer = str(s01.get("answer") or "").strip()
            s02_answer = str(record["content"].get("answer") or "").strip()
            if s01_answer and s02_answer:
                answer_relation = "same_answer_text" if s01_answer.casefold() == s02_answer.casefold() else "answer_label_differs_option_order_or_content_needs_review"
            else:
                answer_relation = "not_comparable_from_answer_field"
            manual_note = MANUAL_S01_CHECKS.get((uid, year, math_type, number))
            status = "manually_verified_same_question" if manual_note else "s01_location_match_content_not_yet_compared"
            item = {
                "s02_source_uid": uid,
                "year_claimed": year,
                "math_type_claimed": math_type,
                "question_number_claimed": number,
                "s02_source_claim": claim,
                "s02_answer": record["content"].get("answer"),
                "s01_key": s01["key"],
                "s01_question_id": s01["question_id"],
                "s01_answer": s01.get("answer"),
                "s01_knowledge_point": s01.get("knowledge_point"),
                "s01_question_path": (group_path / f"{prefix}.png").as_posix(),
                "s01_analysis_path": (group_path / "analysis" / f"{prefix}_analysis.png").as_posix(),
                "s01_answer_path": (group_path / "answers" / f"{prefix}_answer.png").as_posix(),
                "answer_relation": answer_relation,
                "review_status": status,
                "manual_review_note": manual_note,
            }
            crosswalk.append(item)
            by_claim[(uid, year, math_type, number)] = item
    return crosswalk, by_claim


def _entry(
    record: dict[str, Any], *, set_kind: str,
    exam_claims: list[dict[str, Any]] | None = None,
    cross_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    identity = record["identity"]
    content = record["content"]
    source = record["source"]
    uid = int(source["source_uid"])
    math_check = MANUAL_S02_MATH_CHECKS.get(str(uid))
    claims = exam_claims or []
    source_labels = _source_labels(identity, content.get("upstream_category_path"))
    topic_path = content.get("upstream_category_path")
    chapter_tags, context_tags, topic_status = _chapter_tags(topic_path)
    question_type = content.get("question_type")
    math_review_status = math_check["status"] if math_check else "not_reviewed"
    category = "练习题" if set_kind.startswith("exercise") else "真题候选"
    source_review_label = _source_review_label(identity)
    tags = [f"category:{category}", *(f"source:{label}" for label in source_labels), *chapter_tags, *context_tags]
    if question_type:
        tags.append(f"question_type:{question_type}")
    tags.extend((
        f"topic_status:{topic_status}",
        f"source_status:{source_review_label}",
        f"source_identity:{identity.get('source_identity_status') or 'unknown'}",
        f"math_review:{math_review_status}",
    ))
    for claim in claims:
        if claim.get("year_claimed") is not None:
            tags.append(f"exam_year_claimed:{claim['year_claimed']}")
        for number in claim.get("question_numbers_claimed") or []:
            tags.append(f"exam_question_number_claimed:{number}")
    key = f"S02_{uid}"
    return {
        "group": None,
        "paper": None,
        "index": None,
        "question_id": uid,
        "type": _question_type(record),
        "answer": content.get("answer"),
        "score": None,
        "knowledge_point": topic_path,
        "source_id": source["source_id"],
        "source_revision": source["revision"],
        "source_uid": source["source_uid"],
        "source_record_sha256": source["source_record_sha256"],
        "source_kind": set_kind,
        "math_review_status": math_review_status,
        "math_review_note": math_check["note"] if math_check else None,
        "source_labels_claimed": source_labels,
        "source_identity_status": identity.get("source_identity_status"),
        "source_claims": {
            "raw_source": identity.get("raw_source"),
            "raw_original_source": identity.get("raw_original_source"),
            "raw_source_details": identity.get("raw_source_details"),
            "raw_source_tags": identity.get("raw_source_tags") or [],
            "book_claims": identity.get("book_claims") or [],
            "year_type_source_claims": identity.get("year_type_source_claims") or [],
            "exam_source_evidence": identity.get("exam_source_evidence") or [],
            "exam_claims": identity.get("exam_claims") or [],
            "math_types_applicable_claimed": identity.get("math_types_applicable_claimed") or [],
        },
        "exam_claims_claimed": claims,
        "exam_identity_verified": bool(claims) and all(claim.get("verified_as_original_exam") for claim in claims),
        "s01_cross_references": cross_refs or [],
        "question_type": content.get("question_type"),
        "stem_md": content.get("stem"),
        "options": content.get("options") or [],
        "explanation_md": content.get("explanation"),
        "illustrations": content.get("illustrations") or [],
        "upstream_category_path": content.get("upstream_category_path"),
        "upstream_serial_number": identity.get("upstream_serial_number"),
        "printed_page_claimed": identity.get("printed_page"),
        "staging_key": key,
        "classification": {
            "category": category,
            "source_labels_claimed": source_labels,
            "chapter_tags": chapter_tags,
            "topic_path_claimed": topic_path,
            "topic_tag_status": topic_status,
            "source_review_label": source_review_label,
            "question_type_claimed": question_type,
            "source_identity_status": identity.get("source_identity_status"),
            "math_review_status": math_review_status,
            "exam_claims": claims,
        },
        "tags": sorted(set(tags)),
    }


def _source_slug(label: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", label).strip(" .")
    safe = safe[:72].rstrip(" .") or "source"
    suffix = hashlib.sha256(label.encode("utf-8")).hexdigest()[:8]
    return f"{safe}__{suffix}"


def build(staging_dir: Path, s01_root: Path, output_dir: Path) -> dict[str, Any]:
    practice = _read_jsonl(staging_dir / "s02-practice-candidates.jsonl")
    exams = _read_jsonl(staging_dir / "s02-exam-claims-review.jsonl")
    unclassified = _read_jsonl(staging_dir / "s02-scope-unclassified.jsonl")
    practice_records = [
        (record, "exercise_source_candidate") for record in practice
    ] + [
        (record, "exercise_source_candidate_topic_unclassified") for record in unclassified
    ]
    s01_lookup = _s01_indexes(s01_root)
    crosswalk, _ = _s01_crosswalk(exams, s01_root, s01_lookup)

    by_set_and_source: dict[str, dict[str, dict[str, dict[str, Any]]]] = {
        "practice": defaultdict(dict),
        "exam_claims": defaultdict(dict),
    }
    practice_records_with_images = 0
    source_labels_used: Counter[str] = Counter()
    topic_tag_status_counts: Counter[str] = Counter()
    topic_root_counts: Counter[str] = Counter()

    for record, set_kind in practice_records:
        practice_records_with_images += bool(record["content"].get("illustrations"))
        labels = _source_labels(record["identity"], record["content"].get("upstream_category_path"))
        topic_path = record["content"].get("upstream_category_path")
        _, _, topic_status = _chapter_tags(topic_path)
        topic_tag_status_counts[topic_status] += 1
        if topic_path:
            root = topic_path.split(" / ", 1)[0]
            topic_root_counts[root] += 1
        entry = _entry(record, set_kind=set_kind)
        key = entry["staging_key"]
        for label in labels:
            source_labels_used[label] += 1
            by_set_and_source["practice"][label][key] = entry

    exam_claim_entries = 0
    crosswalk_by_uid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in crosswalk:
        crosswalk_by_uid[row["s02_source_uid"]].append(row)
    for record in exams:
        uid = str(record["source"]["source_uid"])
        claims = record["identity"].get("exam_claims") or []
        exam_claim_entries += len(claims)
        entry = _entry(
            record,
            set_kind="unverified_exam_source_claim",
            exam_claims=claims,
            cross_refs=crosswalk_by_uid.get(uid, []),
        )
        key = entry["staging_key"]
        for label in entry["source_labels_claimed"]:
            by_set_and_source["exam_claims"][label][key] = entry

    output_dir.mkdir(parents=True, exist_ok=True)
    set_directories = {
        "practice": "练习题/按来源",
        "exam_claims": "真题候选/按来源",
    }
    source_index_labels: dict[str, Any] = {}
    for set_name, sources in by_set_and_source.items():
        for label, rows in sorted(sources.items()):
            slug = _source_slug(label)
            relative_path = f"{set_directories[set_name]}/{slug}/answers.json"
            _write_json(output_dir / Path(relative_path), rows)
            info = source_index_labels.setdefault(label, {
                "directory_key": slug,
                "entries_by_set": {},
                "unique_source_uid_counts_by_set": {},
                "files_by_set": {},
                "source_labels_are_claims_not_print_verification": True,
            })
            info["entries_by_set"][set_name] = len(rows)
            info["unique_source_uid_counts_by_set"][set_name] = len({entry["source_uid"] for entry in rows.values()})
            info["files_by_set"][set_name] = relative_path

    _write_jsonl(output_dir / "S01交叉索引.jsonl", crosswalk)
    manual = [row for row in crosswalk if row["manual_review_note"]]
    _write_jsonl(output_dir / "人工核对样例.jsonl", manual)

    source_index = {
        "source_id": "S02",
        "revision": "7e79423253454dfb32246b6a84c7d6fd6efaa5b8",
        "source_labels_are_claims_not_print_verification": True,
        "lookup_instructions": "先按 category 区分练习题或真题候选，再按 source、chapter、question_type、source_status 和 math_review 标签筛选；题目以 question_id/S02_UID 为键。",
        "by_source_label": dict(sorted(source_index_labels.items())),
    }
    _write_json(output_dir / "source_index.json", source_index)

    manual_uids = {row["s02_source_uid"] for row in manual}
    canonical_records = {
        entry["question_id"]: entry
        for source_sets in by_set_and_source.values()
        for rows in source_sets.values()
        for entry in rows.values()
    }
    math_review_counts = Counter(entry["math_review_status"] for entry in canonical_records.values())
    source_uid_counts_by_set = {
        set_name: len({entry["question_id"] for rows in sources.values() for entry in rows.values()})
        for set_name, sources in by_set_and_source.items()
    }
    manifest = {
        "schema": "mathlens.s02-source-tagged-index/v2",
        "source_id": "S02",
        "revision": "7e79423253454dfb32246b6a84c7d6fd6efaa5b8",
        "source_repository": "https://github.com/diamond-pickaxe/cxy-daguan",
        "staging_root": str(staging_dir.resolve()),
        "s01_root": str(s01_root.resolve()),
        "s01_coverage_years": list(YEAR_RANGE),
        "unique_practice_records": len(practice_records),
        "unique_records_by_set": source_uid_counts_by_set,
        "practice_records_with_illustrations": practice_records_with_images,
        "practice_source_labels_overlap": dict(source_labels_used),
        "practice_topic_tag_status_counts": dict(topic_tag_status_counts),
        "practice_upstream_category_root_counts": dict(topic_root_counts),
        "source_index_label_count": len(source_index_labels),
        "unique_exam_source_review_records": len(exams),
        "exam_claim_entries": exam_claim_entries,
        "exam_records_with_out_of_s01_range_claim": sum(
            any(c["year_claimed"] < YEAR_RANGE[0] or c["year_claimed"] > YEAR_RANGE[1] for c in r["identity"].get("exam_claims") or [])
            for r in exams
        ),
        "s01_exact_year_type_question_number_crosswalk_entries": len(crosswalk),
        "s01_crosswalk_rows_by_review_status": dict(Counter(row["review_status"] for row in crosswalk)),
        "manually_checked_s02_records": sorted(manual_uids, key=int),
        "manually_math_checked_s02_uids": sorted(MANUAL_S02_MATH_CHECKS, key=int),
        "practice_records_without_upstream_topic_path": len(unclassified),
        "math_review_status": "not_all_records_reviewed; see manual-check examples",
        "math_review_status_counts_by_unique_record": dict(math_review_counts),
        "exam_identity_status": "source claims retained; only the listed manual examples were matched visually to S01",
        "database_written": False,
        "original_s02_assets_copied": False,
        "directories": {
            "practice": set_directories["practice"] + "/<来源目录>/answers.json",
            "exam_claims": set_directories["exam_claims"] + "/<来源目录>/answers.json",
            "source_index": "source_index.json",
            "s01_crosswalk": "S01交叉索引.jsonl",
            "manual_samples": "人工核对样例.jsonl",
        },
    }
    _write_json(output_dir / "manifest.json", manifest)
    readme = '# S02 按来源和考点标签组织的额外题库候选\n\n只分两类：练习题和真题候选。目录按来源组织，不按数学一/二/三拆分。同一题若有多个来源声明，会出现在多个来源目录中；每个来源文件内部按 S02 UID 去重。\n\n- `练习题/按来源/<来源目录>/answers.json`：题干、答案和文字解析齐全的练习候选；44 条原先因缺少类别标记而单列的记录已并入。\n- `真题候选/按来源/<来源目录>/answers.json`：S02 声称有历年真题来源的记录，身份尚未逐题确认。\n- `source_index.json`：按来源标签查找两类题目及文件路径。\n- `S01交叉索引.jsonl`：可按 S01 年份、类别和题号定位的真题来源声明。仅 3 条已人工对照原题；其余只是元数据位置对应。\n\n## 每题标签\n\n`category:` 标记练习题或真题候选；`source:` 标记来源声明；`chapter:` 根据 S02 上游考点路径拆成逐级标签，并在检索标签中去掉“数学一/二/三”范围字样；完整上游路径仍保留在来源字段，方便追溯；`question_type:` 标记题型；`source_status:` 标记来源身份状态；`math_review:` 标记解答是否人工核验；`exam_year_claimed:` 保留真题年份主张。数一/二/三不用于目录和检索标签，原始上游主张保留在 `source_claims` 供追溯。\n\nS02 考点路径是上游标签，主要覆盖高数、线代、概率统计等。3,380 条练习题有章节考点标签；850 条模拟卷记录只有试卷/来源位置，不能当作章节标签；44 条没有考点路径，标为 `chapter:待标注`。Agent 可按题目内容判断考点，缺少标签不表示题目没有考点。\n\n## “来源待核”是什么意思\n\n这是**来源身份待核**：上游写了作者、书名、年份或题号，但还没逐题对照原书/原卷，或暂时不能归到具体作者/版本。多本教材可能转载同一道题，所以多个来源标签本身不等于互相冲突；只有原件能证明说法互斥时才标为冲突。它也不表示题干、答案或解析已经发现错误。无法归到具体作者/书名的记录标为“来源待归并”；像 0.9k、0.66k、通用1000题有粗略来源标签，但作者或版本不明。真题候选要核对题目内容及年份、类别和题号后，才能称为已核实真题。\n\n## 核对边界\n\n所有练习候选都有题干、答案和文字解析；字段齐全不等于数学正确。原隔离小样曾手算 UID 1088 和 2314；后续 15 题采用抽样另核 14 题结论，UID 1816 因题干与必要图的导数阶数不一致而隔离。完整清单见 `docs/local/extra-bank/ADOPTION-REVIEW-2026-10-24.md`；全库仍未逐题核验。真题声明共 3,071 条，其中 1,283 条可定位到 S01，只有 3 条经人工逐题对照。选用题目时核对来源版本、必要图片和答案解析，不需要先人工审完全库。\n\nS02 图片未复制，记录保留来源相对路径和 SHA256；需从固定 revision 本地 checkout 取图。索引便于 Agent 检索与逐题复核，目前没有接入 MathLens 的 `catalog/read_bank`。\n'
    (output_dir / "README.md").write_text(readme, encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build source-first indexes from the local S02 staging sets.")
    parser.add_argument("--staging-dir", type=Path, required=True)
    parser.add_argument("--s01-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = build(args.staging_dir, args.s01_root, args.output_dir)
    summary = {
        "unique_practice_records": manifest["unique_practice_records"],
        "practice_topic_tag_status_counts": manifest["practice_topic_tag_status_counts"],
        "unique_records_by_set": manifest["unique_records_by_set"],
        "unique_exam_source_review_records": manifest["unique_exam_source_review_records"],
        "exam_claim_entries": manifest["exam_claim_entries"],
        "s01_crosswalk_entries": manifest["s01_exact_year_type_question_number_crosswalk_entries"],
        "manual_samples": manifest["manually_checked_s02_records"],
        "output": str(args.output_dir.resolve()),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from extra_bank_adapters.cxy_daguan import KNOWN_REVISION, adapt_cxy


KNOWN_MATH_TYPES = {"math_1", "math_2", "math_3"}


def _assets_are_resolved(record: dict[str, Any]) -> bool:
    assets = record["content"].get("illustrations") or []
    return all(item.get("exists") and item.get("sha256_matches_ref") for item in assets)


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def extract(source_root: Path, output_dir: Path, revision: str) -> dict[str, Any]:
    records = adapt_cxy(source_root, revision)
    exam_records: list[dict[str, Any]] = []
    exam_outside_s01_records: list[dict[str, Any]] = []
    practice_records: list[dict[str, Any]] = []
    unclassified_scope_records: list[dict[str, Any]] = []
    exclusions: Counter[str] = Counter()
    claim_counts: Counter[str] = Counter()

    for record in records:
        identity = record["identity"]
        claims = identity.get("exam_claims") or []
        exam_evidence = identity.get("exam_source_evidence") or []
        if claims or exam_evidence:
            exam_records.append(record)
            evidence_years = {
                item.get("year_claimed") for item in exam_evidence if item.get("year_claimed")
            }
            claim_years = {claim["year_claimed"] for claim in claims}
            if any(
                claim["year_claimed"] < 2009 or claim["year_claimed"] > 2025
                for claim in claims
            ) or any(year < 2009 or year > 2025 for year in evidence_years | claim_years):
                exam_outside_s01_records.append(record)
            for claim in claims:
                key = f"{claim['year_claimed']}:math_{claim['math_type_claimed']}" if claim.get("math_type_claimed") else f"{claim['year_claimed']}:unknown_type"
                claim_counts[key] += 1
        else:
            exclusions["no_exam_claim"] += 1

        if claims or exam_evidence:
            exclusions["practice_excluded_exam_source_evidence"] += 1
            continue
        if not (identity.get("lineage_segments") or []):
            exclusions["practice_excluded_no_source_lineage"] += 1
            continue
        applicable = set(identity.get("math_types_applicable_claimed") or [])
        if not applicable.intersection(KNOWN_MATH_TYPES):
            unclassified_scope_records.append(record)
            exclusions["scope_unclassified"] += 1
            continue
        availability = record["availability"]
        if not (
            availability.get("stem_present")
            and availability.get("answer_present")
            and availability.get("explanation_present")
        ):
            exclusions["practice_excluded_missing_stem_answer_or_explanation"] += 1
            continue
        if not _assets_are_resolved(record):
            exclusions["practice_excluded_unresolved_illustration"] += 1
            continue
        practice_records.append(record)

    output_dir.mkdir(parents=True, exist_ok=True)
    all_path = output_dir / "s02-all-staging.jsonl"
    exam_path = output_dir / "s02-exam-claims-review.jsonl"
    exam_gap_path = output_dir / "s02-exam-claims-outside-s01-range.jsonl"
    practice_path = output_dir / "s02-practice-candidates.jsonl"
    unclassified_scope_path = output_dir / "s02-scope-unclassified.jsonl"
    _write_jsonl(all_path, records)
    _write_jsonl(exam_path, exam_records)
    _write_jsonl(exam_gap_path, exam_outside_s01_records)
    _write_jsonl(practice_path, practice_records)
    _write_jsonl(unclassified_scope_path, unclassified_scope_records)

    exam_years = [claim["year_claimed"] for row in exam_records for claim in row["identity"]["exam_claims"]]
    exam_evidence_count = sum(
        len(row["identity"].get("exam_source_evidence") or []) for row in exam_records
    )
    practice_book_claim_counts: Counter[str] = Counter()
    practice_math_scope_counts: Counter[str] = Counter()
    practice_rows_with_illustrations = 0
    practice_rows_requiring_lineage_review = 0
    for record in practice_records:
        identity = record["identity"]
        practice_book_claim_counts.update(
            {claim["book_claim"] for claim in identity.get("book_claims") or []}
        )
        practice_math_scope_counts.update(
            set(identity.get("math_types_applicable_claimed") or []).intersection(KNOWN_MATH_TYPES)
        )
        practice_rows_with_illustrations += bool(record["content"].get("illustrations"))
        practice_rows_requiring_lineage_review += bool(identity.get("lineage_conflict_or_multiple_claims"))
    manifest = {
        "source_id": "S02",
        "revision": revision,
        "source_root": str(source_root.resolve()),
        "source_file": "library/bundled-library.json",
        "record_count": len(records),
        "exam_claim_review_record_count": len(exam_records),
        "exam_source_evidence_count": exam_evidence_count,
        "exam_evidence_records_without_typed_year_category": sum(
            not any(claim.get("math_type_claimed") for claim in row["identity"].get("exam_claims") or [])
            for row in exam_records
        ),
        "exam_claim_records_with_year_outside_s01_coverage": len(exam_outside_s01_records),
        "s01_year_coverage_for_gap_triage": [2009, 2025],
        "exam_claim_count": sum(claim_counts.values()),
        "exam_claim_record_counts_by_year_and_type": dict(sorted(claim_counts.items())),
        "exam_claim_year_min": min(exam_years) if exam_years else None,
        "exam_claim_year_max": max(exam_years) if exam_years else None,
        "practice_candidate_record_count": len(practice_records),
        "unclassified_scope_record_count": len(unclassified_scope_records),
        "practice_candidates_by_recognized_book_claim": dict(sorted(practice_book_claim_counts.items())),
        "practice_candidates_by_applicable_math_scope_overlap": dict(sorted(practice_math_scope_counts.items())),
        "practice_candidate_records_with_illustrations": practice_rows_with_illustrations,
        "practice_candidate_records_requiring_lineage_review": practice_rows_requiring_lineage_review,
        "practice_filter": [
            "no parsed exam-source claim",
            "non-empty source lineage preserved",
            "at least one claimed scope among math_1/math_2/math_3",
            "non-empty stem, answer, and text explanation",
            "all referenced images exist and match their declared SHA256",
        ],
        "math_review_status": "not_reviewed_for_all_records",
        "exam_identity_status": "claims_only_not_verified_against_original_exams",
        "exclusions": dict(sorted(exclusions.items())),
        "outputs": {
            "all_staging": all_path.name,
            "exam_claim_review": exam_path.name,
            "exam_claim_outside_s01_range_review": exam_gap_path.name,
            "practice_candidates": practice_path.name,
            "unclassified_scope": unclassified_scope_path.name,
        },
        "database_written": False,
        "third_party_assets_copied": False,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract S02 staging, exam-source claims, and complete exercise candidates without database writes."
    )
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--revision", default=KNOWN_REVISION)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = extract(args.source_root, args.output_dir, args.revision)
    print(json.dumps({
        "source_id": manifest["source_id"],
        "revision": manifest["revision"],
        "record_count": manifest["record_count"],
        "exam_claim_review_record_count": manifest["exam_claim_review_record_count"],
        "exam_source_evidence_count": manifest["exam_source_evidence_count"],
        "exam_claim_records_with_year_outside_s01_coverage": manifest["exam_claim_records_with_year_outside_s01_coverage"],
        "practice_candidate_record_count": manifest["practice_candidate_record_count"],
        "unclassified_scope_record_count": manifest["unclassified_scope_record_count"],
        "outputs": manifest["outputs"],
        "database_written": manifest["database_written"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

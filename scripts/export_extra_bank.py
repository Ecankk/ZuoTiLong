from __future__ import annotations

import argparse
import json
from pathlib import Path

from extra_bank_adapters.cxy_daguan import adapt_cxy
from extra_bank_adapters.zhangyu_html import adapt_zhangyu


def _chapter_values(value: str) -> tuple[int, ...]:
    if "-" in value:
        start, end = (int(item) for item in value.split("-", 1))
        if start > end:
            raise argparse.ArgumentTypeError("chapter range must be ascending")
        return tuple(range(start, end + 1))
    return tuple(int(item) for item in value.split(",") if item.strip())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert a local external question source to MathLens staging JSONL; no database writes."
    )
    parser.add_argument("--source", choices=("S02", "S03"), required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--revision", required=True, help="Fixed upstream Git SHA")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--ids", help="Comma-separated upstream numeric IDs (S02 only)")
    parser.add_argument("--chapters", type=_chapter_values, default=tuple(range(32, 68)), help="Chapter numbers/range (S03 only)")
    args = parser.parse_args()

    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if args.source == "S02":
        ids = {int(value) for value in args.ids.split(",")} if args.ids else None
        records = adapt_cxy(args.source_root, args.revision, question_ids=ids, limit=args.limit)
    else:
        if args.ids:
            parser.error("--ids is supported only for S02")
        records = adapt_zhangyu(args.source_root, args.revision, chapters=args.chapters, limit=args.limit)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    summary = {
        "source": args.source,
        "revision": args.revision,
        "records_written": len(records),
        "explicit_answers": sum(
            record["availability"].get("answer_state") == "explicit_final_answer"
            or record["availability"].get("answer_present", False)
            for record in records
        ),
        "explanations_present": sum(bool(record["availability"].get("explanation_present")) for record in records),
        "illustration_records": sum(
            bool(record["availability"].get("illustrations_present"))
            or bool(record["availability"].get("illustrations_expected"))
            for record in records
        ),
        "illustration_assets_expected": sum(
            record["availability"].get("illustrations_expected", 0) for record in records
        ),
        "illustration_assets_resolved": sum(
            record["availability"].get("illustrations_resolved", 0) for record in records
        ),
        "output": str(args.output),
        "database_written": False,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

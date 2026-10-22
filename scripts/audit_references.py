"""Read-only reference/data audit and isolated probes of the current PDF pipeline.

Run from the project: python scripts/audit_references.py
Does not import reference-project code, call AI services, or open the user DB.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], text=True, encoding="utf-8"
    ).strip()


def inspect_bank(repo: Path) -> list[dict]:
    banks = []
    for path in sorted(repo.glob("*/questions.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        questions = [q for chapter in data["chapters"] for q in chapter["questions"]]
        images = [q["image_ref"]["cropped"] for q in questions
                  if isinstance(q.get("image_ref"), dict) and q["image_ref"].get("cropped")]
        answers = [q["answer_ref"] for q in questions if q.get("answer_ref")]
        hold_file = path.with_name("quality-hold.json")
        hold = json.loads(hold_file.read_text(encoding="utf-8")) if hold_file.exists() else {}
        banks.append({
            "file": path.relative_to(repo).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "title": data.get("title"),
            "questions": len(questions),
            "chapters": len(data["chapters"]),
            "duplicate_uids_within_bank": len(questions) - len({q["uid"] for q in questions}),
            "nonempty_text_answers": sum(bool(q.get("answer") or q.get("solution")) for q in questions),
            "image_refs": len(images),
            "missing_image_refs": sum(not (path.parent / ref).is_file() for ref in images),
            "answer_refs": len(answers),
            "missing_answer_refs": sum(not (path.parent / ref).is_file() for ref in answers),
            "upstream_quality_claim_not_independently_verified": hold.get("summary"),
        })
    return banks


def probe_pipeline() -> dict:
    import pymupdf as fitz
    from pdf_pipeline import extract_pdf, _bank_score

    probes = []
    # Keep temporary writes inside the workspace (Windows sandbox TEMP may be read-only).
    with tempfile.TemporaryDirectory(prefix="mathlens-source-audit-", dir=ROOT) as directory:
        assert Path(directory).resolve().parent == ROOT.resolve()
        def extract(name: str, texts: list[str], allow_ocr: bool = False) -> dict:
            path = Path(directory) / f"{name}.pdf"
            with fitz.open() as document:
                for text in texts:
                    page = document.new_page()
                    if text:
                        page.insert_text((72, 72), text, fontsize=12)
                document.save(path)
            return extract_pdf(path, allow_ocr=allow_ocr)

        for name, text in [
            ("decimal_numbers", "1. Evaluate 0.5 plus 0.25. Explain your result.\n2. Compute three plus four."),
            ("subquestion_numbers", "1. Complete both parts.\n(1) Find the derivative.\n(2) Find the integral.\n2. Solve the next equation."),
        ]:
            result = extract(name, [text])
            actual = [q["number"] for q in result["questions"]]
            probes.append({"name": name, "expected_question_numbers": ["1", "2"],
                           "actual_question_numbers": actual, "passed": actual == ["1", "2"]})

        result = extract("separate_regions", ["1. First question.\n\n\n2. Second question."])
        boxes = [q["bbox"] for q in result["questions"]]
        probes.append({"name": "distinct_question_regions", "actual_boxes": boxes,
                       "passed": len(boxes) == 2 and all(boxes) and boxes[0] != boxes[1]})

        result = extract("page_boundary", ["1. Question entirely on page one.", "2. Question entirely on page two."])
        ranges = [[q["page_start"], q["page_end"]] for q in result["questions"]]
        probes.append({"name": "page_boundary", "expected_ranges": [[1, 1], [2, 2]],
                       "actual_ranges": ranges, "passed": ranges == [[1, 1], [2, 2]]})

        blank = extract("blank_page", [""], allow_ocr=True)

    score = _bank_score("Find the roots of x^2=1. Give only positive roots.",
                        {"stem": "Find the roots of x^2=1."})
    return {
        "scope": "Synthetic digital PDFs only; no handwriting/OCR accuracy or real-paper benchmark",
        "pymupdf_version": fitz.VersionBind,
        "paddleocr_package_detected": importlib.util.find_spec("paddleocr") is not None,
        "segmentation_probes": probes,
        "substring_identity_counterexample": {
            "score": score,
            "interpretation": "Different answer constraints receive a high score; score is not identity probability",
        },
        "blank_page_engine": blank["engine"],
        "blank_page_question_count": len(blank["questions"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--references", type=Path, default=ROOT.parent / "references")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/reference-audit-results.json")
    args = parser.parse_args()
    repositories = []
    for repo in sorted(args.references.iterdir()):
        if not (repo / ".git").exists():
            continue
        repositories.append({"directory": repo.name,
                             "origin": git(repo, "remote", "get-url", "origin"),
                             "commit": git(repo, "rev-parse", "HEAD"),
                             "root_license_files": [p.name for p in repo.glob("LICENSE*")]})
    result = {"mathlens_revision": git(ROOT, "rev-parse", "HEAD"),
              "pipeline_sha256": hashlib.sha256((ROOT / "pdf_pipeline.py").read_bytes()).hexdigest(),
              "repositories": repositories,
              "bank_audit": inspect_bank(args.references / "math-question-bank"),
              "mathlens_probes": probe_pipeline()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()

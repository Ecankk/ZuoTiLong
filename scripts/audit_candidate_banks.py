"""Audit candidate local banks without importing their code or changing user data."""
import json
from pathlib import Path
import re
import subprocess
from collections import Counter

import pymupdf as fitz

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT.parent / "references"


def revision(repo):
    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()


def image_bank():
    repo = REF / "kaoyanshuxue"
    groups = []
    for path in sorted((repo / "kaoyan_math_images").glob("*/answers.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        missing_questions, missing_analysis, missing_answers, invalid = [], [], [], []
        decoded = 0
        for key, question in data.items():
            base = path.parent / str(question["paper"])
            stem = f"Q{question['index']:02d}_id{question['question_id']}"
            targets = [(base / (stem + ".png"), missing_questions),
                       (base / "analysis" / (stem + "_analysis.png"), missing_analysis)]
            if question.get("type") != 1:
                targets.append((base / "answers" / (stem + "_answer.png"), missing_answers))
            for target, missing in targets:
                if not target.is_file():
                    missing.append(key)
                    continue
                if path.parent.name == "数学一":
                    try:
                        pixmap = fitz.Pixmap(str(target))
                        if min(pixmap.width, pixmap.height) < 20:
                            invalid.append({"path": str(target.relative_to(repo)), "error": "tiny_image"})
                        decoded += 1
                    except Exception as exc:
                        invalid.append({"path": str(target.relative_to(repo)), "error": type(exc).__name__})
        groups.append({"group": path.parent.name, "records": len(data),
                       "years": sorted({str(q['paper']) for q in data.values()}),
                       "types": dict(Counter(q.get("type") for q in data.values())),
                       "missing_question_images": missing_questions,
                       "missing_analysis_images": missing_analysis,
                       "missing_nonchoice_answer_images": missing_answers,
                       "decoded_images": decoded, "invalid_or_tiny_images": invalid})
    return {"source": "https://github.com/lx-ruc/kaoyanshuxue", "commit": revision(repo),
            "groups": groups, "root_license_files": [p.name for p in repo.glob("LICENSE*")]}


def text_bank():
    repo = REF / "kaoyan-math1-papers"
    files = [p for p in (repo / "papers").glob("*.md") if re.match(r"\d{4}", p.name)]
    years = Counter(p.name[:4] for p in files)
    image_index = {}
    for path in repo.rglob("*"):
        if path.is_file() and path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
            image_index.setdefault(path.name, []).append(path.relative_to(repo).as_posix())
    broken = []
    for path in files:
        content = path.read_text(encoding="utf-8")
        for link in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", content):
            if link.startswith(("https:", "http:", "data:")):
                continue
            if not (path.parent / link).is_file():
                broken.append({"document": path.relative_to(repo).as_posix(), "reference": link,
                               "basename_candidates": image_index.get(Path(link).name, [])})
    return {"source": "https://github.com/TsekaLuk/Kaoyan-Math1-Papers", "commit": revision(repo),
            "year_named_documents": len(files), "unique_years": len(years),
            "duplicate_years": {year: count for year, count in years.items() if count > 1},
            "missing_years_1987_2025": [year for year in range(1987, 2026) if str(year) not in years],
            "broken_image_links": broken,
            "links_with_local_basename_candidates": sum(bool(x["basename_candidates"]) for x in broken),
            "scope": "Top-level year-named paper markdown; mathematical accuracy not audited"}


if __name__ == "__main__":
    result = {"image_bank": image_bank(), "text_bank": text_bank(),
              "scope": "File integrity and metadata only; no OCR/retrieval benchmark or complete answer verification"}
    output = ROOT / "docs/candidate-bank-audit.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, indent=2))

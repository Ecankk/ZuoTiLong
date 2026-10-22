"""Local PDF evidence extraction. OCR text is a draft, never a grading result."""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import threading
import unicodedata

PIPELINE_VERSION = "regions-3-rapidocr-1.4.4"
CACHE_ROOT = Path(__file__).resolve().parent / ".mathlens" / "ocr-cache"
OCR_LOCK = threading.Lock()
QUESTION_START = re.compile(r"^\s*(?:[（(]\s*(?P<bracket>\d{1,2})\s*[)）]|(?P<plain>\d{1,2})\s*[．、.]\s+(?=\D))")


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value or ""))


@lru_cache(maxsize=1)
def _ocr_engine():
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)


def _ocr_blocks(page, clip=None, zoom=2):
    import pymupdf as fitz
    rect = fitz.Rect(clip) if clip else page.rect
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect, alpha=False)
    with OCR_LOCK:
        results, _ = _ocr_engine()(pix.tobytes("png"))
    blocks = []
    for polygon, text, score in results or []:
        xs = [float(p[0]) / zoom + rect.x0 for p in polygon]
        ys = [float(p[1]) / zoom + rect.y0 for p in polygon]
        blocks.append({"bbox": [min(xs), min(ys), max(xs), max(ys)],
                       "text": str(text), "confidence": round(float(score), 4)})
    return blocks


def _read_page(page, index, allow_ocr):
    blocks = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line["spans"]).strip()
            if text:
                blocks.append({"bbox": list(line["bbox"]), "text": text, "confidence": None})
    engine, warning = "pymupdf_text", None
    text_layer = bool(blocks)
    if not text_layer and allow_ocr:
        try:
            blocks = _ocr_blocks(page)
            markers = _ocr_blocks(page, (page.rect.width * .06, 20, page.rect.width * .23, page.rect.height - 35), zoom=3)
            for candidate in markers:
                if QUESTION_START.match(candidate["text"]):
                    if not any(QUESTION_START.match(b["text"]) and abs(b["bbox"][1] - candidate["bbox"][1]) < 8 for b in blocks):
                        candidate["anchor_only"] = True
                        blocks.append(candidate)
            engine = "rapidocr_onnxruntime"
        except ImportError:
            engine, warning = "ocr_unavailable", "扫描页需要安装 requirements-ocr.txt；当前没有可用的本地 OCR"
        except Exception as exc:
            engine, warning = "ocr_failed", f"本地 OCR 失败：{type(exc).__name__}: {exc}"
    if not blocks and not warning:
        warning = "该页没有可识别文字，不能视为处理完成"
    blocks.sort(key=lambda b: (round(b["bbox"][1] / 5), b["bbox"][0]))
    return {"page_number": index + 1, "text": "\n".join(b["text"] for b in blocks if not b.get("anchor_only")),
            "blocks": blocks, "width": page.rect.width, "height": page.rect.height,
            "engine": engine, "confidence": None, "warning": warning,
            "text_layer": text_layer}


def segment_pages(pages: list[dict], expected_count: int | None = None) -> tuple[list[dict], list[str]]:
    candidates = []
    for page in pages:
        for block in page["blocks"]:
            match = QUESTION_START.match(block["text"])
            if not match or block["bbox"][0] > page["width"] * .24:
                continue
            number = int(match.group("bracket") or match.group("plain"))
            if 1 <= number <= 99:
                candidates.append({"number": number, "page": page["page_number"], "y": block["bbox"][1], "x": block["bbox"][0], "style": "bracket" if match.group("bracket") else "plain"})
    candidates.sort(key=lambda x: (x["page"], x["y"], x["x"]))
    anchors = []
    for candidate in candidates:
        if not anchors:
            if candidate["number"] == 1:
                anchors.append(candidate)
        elif candidate["style"] == anchors[0]["style"] and candidate["number"] > anchors[-1]["number"] and candidate["number"] - anchors[-1]["number"] <= 3:
            anchors.append(candidate)
    warnings = []
    numbers = [a["number"] for a in anchors]
    target = expected_count or (max(numbers) if numbers else 0)
    missing = sorted(set(range(1, target + 1)) - set(numbers))
    if missing:
        warnings.append("题号未完整识别：" + ",".join(map(str, missing)))
    questions = []
    for idx, anchor in enumerate(anchors):
        next_anchor = anchors[idx + 1] if idx + 1 < len(anchors) else None
        end_page = next_anchor["page"] if next_anchor else len(pages)
        regions, text = [], []
        for page_num in range(anchor["page"], end_page + 1):
            page = pages[page_num - 1]
            top = max(0, anchor["y"] - 5) if page_num == anchor["page"] else 25
            bottom = next_anchor["y"] - 3 if next_anchor and page_num == next_anchor["page"] else page["height"] - 38
            if bottom <= top:
                continue
            selected = [b for b in page["blocks"] if not b.get("anchor_only") and top <= b["bbox"][1] < bottom]
            if page_num != anchor["page"] and not selected:
                continue
            regions.append({"page": page_num, "bbox": [20, round(top, 2), page["width"] - 15, round(bottom, 2)], "role": "question_and_work"})
            text.extend(b["text"] for b in selected)
        if regions:
            questions.append({"number": str(anchor["number"]), "stem": "\n".join(text)[:9000],
                              "page_start": regions[0]["page"], "page_end": regions[-1]["page"],
                              "bbox": regions[0]["bbox"], "regions": regions,
                              "ocr_confidence": None, "text_status": "ocr_draft"})
    if not questions:
        warnings.append("未得到可定位的题目；等待 Agent 阅读页图后提交切分")
    return questions, warnings


def extract_pdf(pdf_path: Path, allow_ocr: bool = True, expected_count: int | None = None) -> dict:
    try:
        import pymupdf as fitz
    except ImportError:
        return {"engine": "unavailable", "message": "请安装 requirements-ocr.txt", "pages": [], "questions": [], "warnings": ["pymupdf_not_installed"], "complete": False}
    digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    cache_file = CACHE_ROOT / digest / f"{PIPELINE_VERSION}-{'ocr' if allow_ocr else 'text'}.json"
    if cache_file.is_file():
        pages = json.loads(cache_file.read_text(encoding="utf-8"))["pages"]
    else:
        with fitz.open(str(pdf_path)) as document:
            pages = [_read_page(page, idx, allow_ocr) for idx, page in enumerate(document)]
        if pages and all(not p["warning"] for p in pages):
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache_file.with_suffix(".tmp")
            temporary.write_text(json.dumps({"pages": pages}, ensure_ascii=False), encoding="utf-8")
            temporary.replace(cache_file)
    if expected_count is None and "2026" in pdf_path.name and re.search(r"数学.?[（(]?一", pdf_path.name):
        expected_count = 22
    questions, warnings = segment_pages(pages, expected_count)
    warnings.extend(f"第{p['page_number']}页：{p['warning']}" for p in pages if p["warning"])
    complete = bool(questions) and not warnings
    return {"engine": "+".join(sorted({p["engine"] for p in pages})),
            "message": "题目切分完成，等待作答诊断" if complete else "切分存在疑点，等待补充识别",
            "pages": pages, "questions": questions, "warnings": warnings, "complete": complete,
            "source_sha256": digest, "pipeline_version": PIPELINE_VERSION}


def _bank_score(stem: str, bank: dict) -> float:
    query, candidate = normalize_text(stem), normalize_text(bank.get("stem", ""))
    if not query or not candidate:
        return 0.0
    if query == candidate:
        return .99
    a = {query[i:i+2] for i in range(len(query)-1)}
    b = {candidate[i:i+2] for i in range(len(candidate)-1)}
    return round(min(.8, len(a & b) / max(1, len(a | b))), 3)


def match_bank_questions(extracted: list[dict], bank_rows: list[dict]) -> list[dict]:
    for item in extracted:
        ranked = sorted(((_bank_score(item["stem"], bank), bank) for bank in bank_rows), key=lambda pair: pair[0], reverse=True)
        item["match_bank_id"] = ranked[0][1].get("id") if ranked and ranked[0][0] >= .99 else None
        item["match_score"] = ranked[0][0] if ranked else 0.0
        item["bank_candidates"] = [{"id": bank.get("id"), "score": score} for score, bank in ranked[:3] if score > .15]
    return extracted

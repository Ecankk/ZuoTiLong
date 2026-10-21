"""Local PDF extraction and question segmentation for MathLens.

The pipeline deliberately separates three levels of confidence:

* PyMuPDF text extraction for born-digital PDFs (fast and deterministic).
* Optional PaddleOCR for image-only pages (installed separately).
* A review queue when neither engine can produce reliable text.

It never treats OCR output as ground truth. Every extracted question keeps its
page range, bounding box and confidence so the user can verify it against the
original PDF before diagnosing the answer.
"""

from __future__ import annotations

import bisect
import json
import re
import unicodedata
from pathlib import Path


QUESTION_START = re.compile(r"(?m)(?<!\d)(?P<number>\d{1,2})\s*[\.．、)）:]\s*")


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    return re.sub(r"\s+", "", value).replace("﹒", ".")


def _page_for(offset: int, page_offsets: list[int]) -> int:
    return max(0, bisect.bisect_right(page_offsets, offset) - 1)


def _clean_stem(value: str) -> str:
    value = re.sub(r"\[page:\d+\]", "", value)
    value = re.sub(r"\s+", " ", value).strip(" \n\r\t")
    return value[:6000]


def _union_bbox(blocks: list[dict]) -> list[float] | None:
    if not blocks:
        return None
    return [
        round(min(item["bbox"][0] for item in blocks), 2),
        round(min(item["bbox"][1] for item in blocks), 2),
        round(max(item["bbox"][2] for item in blocks), 2),
        round(max(item["bbox"][3] for item in blocks), 2),
    ]


def _try_paddle_ocr(page, page_number: int) -> tuple[str, float, str]:
    """Best-effort PaddleOCR adapter.

    PaddleOCR changes result shapes between major versions. The adapter accepts
    the common v3 ``predict`` response and otherwise returns a review warning;
    the main application remains usable without PaddleOCR installed.
    """
    try:
        from paddleocr import PaddleOCR  # type: ignore
    except Exception:
        return "", 0.0, "paddleocr_not_installed"

    try:
        import fitz  # type: ignore
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            image_path = Path(handle.name)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        pixmap.save(str(image_path))
        try:
            engine = PaddleOCR(lang="ch")
            result = engine.predict(str(image_path))
            texts: list[str] = []
            scores: list[float] = []
            for item in result or []:
                payload = item.json if hasattr(item, "json") else item
                if isinstance(payload, str):
                    payload = json.loads(payload)
                if not isinstance(payload, dict):
                    continue
                data = payload.get("res", payload)
                texts.extend(str(x) for x in data.get("rec_texts", []) if x)
                scores.extend(float(x) for x in data.get("rec_scores", []) if x is not None)
            text = "\n".join(texts).strip()
            confidence = sum(scores) / len(scores) if scores else (0.65 if text else 0.0)
            return text, round(confidence, 3), "paddleocr"
        finally:
            image_path.unlink(missing_ok=True)
    except Exception as exc:
        return "", 0.0, f"paddleocr_error:{type(exc).__name__}"


def extract_pdf(pdf_path: Path, allow_ocr: bool = True) -> dict:
    """Extract page text and question candidates from a PDF."""
    try:
        import fitz  # type: ignore
    except Exception:
        return {
            "engine": "unavailable",
            "message": "未安装 PyMuPDF。请运行 python -m pip install -r requirements-ocr.txt",
            "pages": [],
            "questions": [],
            "warnings": ["pymupdf_not_installed"],
        }

    document = fitz.open(str(pdf_path))
    pages: list[dict] = []
    page_texts: list[str] = []
    page_offsets: list[int] = []
    warnings: list[str] = []
    engine_names: set[str] = set()
    cursor = 0
    for index, page in enumerate(document):
        blocks: list[dict] = []
        for block in page.get_text("blocks"):
            if len(block) < 5:
                continue
            text = str(block[4] or "").strip()
            if not text:
                continue
            blocks.append({"bbox": [float(x) for x in block[:4]], "text": text})
        text = page.get_text("text") or ""
        engine = "pymupdf_text"
        confidence = 0.98 if text.strip() else 0.0
        if not text.strip() and allow_ocr:
            text, confidence, engine = _try_paddle_ocr(page, index + 1)
        if not text.strip():
            warnings.append(f"第 {index + 1} 页没有提取到文字 ({engine})")
        engine_names.add(engine)
        page_offsets.append(cursor)
        page_texts.append(text)
        cursor += len(text) + len(f"\n[page:{index + 1}]\n")
        pages.append({
            "page_number": index + 1,
            "text": text,
            "blocks": blocks,
            "width": round(float(page.rect.width), 2),
            "height": round(float(page.rect.height), 2),
            "engine": engine,
            "confidence": confidence,
        })
    document.close()

    joined = "".join(f"\n[page:{idx + 1}]\n{text}" for idx, text in enumerate(page_texts))
    starts = list(QUESTION_START.finditer(joined))
    questions: list[dict] = []
    for index, match in enumerate(starts):
        start = match.start()
        end = starts[index + 1].start() if index + 1 < len(starts) else len(joined)
        number = match.group("number")
        stem = _clean_stem(joined[match.end():end])
        if len(stem) < 2:
            continue
        page_start = _page_for(start, page_offsets) + 1
        page_end = _page_for(max(start, end - 1), page_offsets) + 1
        related_pages = pages[page_start - 1:page_end]
        bbox = _union_bbox([block for page in related_pages for block in page["blocks"]])
        confidence = min((page["confidence"] for page in related_pages), default=0.0)
        questions.append({
            "number": number,
            "stem": stem,
            "page_start": page_start,
            "page_end": page_end,
            "bbox": bbox,
            "ocr_confidence": round(confidence, 3),
        })

    if not questions and any(page["text"].strip() for page in pages):
        warnings.append("提取到文字但没有识别到标准题号，请人工确认切分")
    if not questions and any(page["engine"] == "paddleocr_not_installed" for page in pages):
        warnings.append("扫描页需要安装 PaddleOCR，当前仅保存了 PDF 原文件")
    engine = "+".join(sorted(engine_names)) if engine_names else "unavailable"
    return {"engine": engine, "message": "解析完成" if questions else "需要人工确认", "pages": pages, "questions": questions, "warnings": warnings}


def _bank_score(stem: str, bank: dict) -> float:
    query = normalize_text(stem)
    candidate = normalize_text(bank.get("stem", ""))
    if not query or not candidate:
        return 0.0
    if candidate in query or query in candidate:
        return 0.96
    fingerprint = bank.get("fingerprint") or {}
    tags = list(bank.get("tags") or []) + list(fingerprint.get("objects") or []) + list(fingerprint.get("method") or [])
    hits = sum(1 for tag in tags if normalize_text(str(tag)) and normalize_text(str(tag)) in query)
    # Chinese question text has no reliable word boundaries; 2-character
    # shingles provide a conservative fallback for paraphrased questions.
    shingles = {query[i:i + 2] for i in range(max(0, len(query) - 1))}
    candidate_shingles = {candidate[i:i + 2] for i in range(max(0, len(candidate) - 1))}
    overlap = len(shingles & candidate_shingles) / max(1, len(candidate_shingles))
    return round(min(0.9, 0.25 + min(0.45, hits * 0.12) + min(0.3, overlap * 0.6)), 3)


def match_bank_questions(extracted: list[dict], bank_rows: list[dict]) -> list[dict]:
    for item in extracted:
        ranked = sorted(((_bank_score(item["stem"], bank), bank) for bank in bank_rows), key=lambda pair: pair[0], reverse=True)
        if ranked and ranked[0][0] >= 0.58:
            score, bank = ranked[0]
            item["match_bank_id"] = bank.get("id")
            item["match_score"] = score
            item["knowledge"] = "｜".join(bank.get("tags") or bank.get("fingerprint", {}).get("objects", []))
            item["fingerprint"] = bank.get("fingerprint") or {}
        else:
            item["match_bank_id"] = None
            item["match_score"] = round(ranked[0][0], 3) if ranked else 0.0
    return extracted

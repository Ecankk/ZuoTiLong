import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from extra_bank_adapters.cxy_daguan import adapt_cxy
from extra_bank_adapters.zhangyu_html import adapt_zhangyu


class ExtraBankAdapterTests(unittest.TestCase):
    def test_zhangyu_preserves_strengthening_locator_without_inventing_print_identity(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="zhangyu-adapter-") as temp:
            root = Path(temp)
            (root / "chapters").mkdir()
            (root / "index.html").write_text(
                "<html><head><title>2026张宇考研数学1000题 刷题版</title></head>"
                "<body><p>数学一</p></body></html>",
                encoding="utf-8",
            )
            chapter = """<!doctype html><html><body>
<div class="top-title">强化篇 · 第1章 函数极限与连续<span class="top-count">（2题）</span></div>
<article class="question" id="q1" data-no="1">
  <span class="q-no">1</span><span class="q-kind">选择题</span>
  <div class="q-stem">设 $\\lim_{x\\to0}x^2=$（　　）.
    <div class="options"><span class="opt"><b class="opt-key">(A)</b><span class="opt-val">$0$</span></span>
    <span class="opt"><b class="opt-key">(B)</b><span class="opt-val">$1$</span></span></div></div>
  <section><div class="analysis-body">由 $x^2\\to0$，答案为 (A)。</div>
  <div class="answer-line"><span class="answer-label">最终答案</span><span class="answer-body">(A)</span></div></section>
</article>
<article class="question" id="q2" data-no="2"><span class="q-no">2</span><span class="q-kind">填空题</span>
  <div class="q-stem">求 $\\int_0^1 x\\,dx$。</div><div class="analysis-body">原函数为 $x^2/2$。</div>
</article></body></html>"""
            (root / "chapters" / "chapter-32.html").write_text(chapter, encoding="utf-8")

            rows = adapt_zhangyu(root, "a" * 40, chapters=(32,))

        self.assertEqual(len(rows), 2)
        first = rows[0]
        self.assertEqual(first["identity"]["part"], "强化篇")
        self.assertIsNone(first["identity"]["book_question_number"])
        self.assertIsNone(first["identity"]["book_group"])
        self.assertEqual(
            first["identity"]["requested_b_group_mapping"],
            "unverified_for_this_book_title_and_printing",
        )
        self.assertEqual(first["source"]["source_uid"], "chapters/chapter-32.html#q1")
        self.assertIn(r"\lim_{x\to0}x^2", first["content"]["stem"])
        self.assertEqual(first["content"]["options"], [{"key": "A", "value": "$0$"}, {"key": "B", "value": "$1$"}])
        self.assertEqual(first["content"]["answer"], "(A)")
        self.assertIsNone(rows[1]["content"]["answer"])
        self.assertEqual(rows[1]["availability"]["answer_state"], "not_separately_present")

    def test_cxy_retains_mixed_lineage_and_verifies_asset_hash(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="cxy-adapter-") as temp:
            root = Path(temp)
            data = b"tiny local fixture asset"
            digest = hashlib.sha256(data).hexdigest()
            ref = f"asset://sha256/{digest}"
            asset_path = root / "public" / "assets" / "media" / f"{digest}.png"
            asset_path.parent.mkdir(parents=True)
            asset_path.write_bytes(data)
            question = {
                "id": 77,
                "source": "1987年·数一；0.88k·25版·第九章·B组·第12题；武忠祥基础严选·第六章·填空第3题",
                "original_source": "1987数一；25版 880 B组12；武基础严选第六章填空3",
                "source_tags": ["1987年真题", "0.88k", "武忠祥基础严选"],
                "source_details": "1987年·数一；0.88k·25版·第九章·B组·第12题；武忠祥基础严选·第六章·填空第3题",
                "category_full_path": "高等数学 / 定积分",
                "stem": "$\\int_0^1 x\\,dx=$ ____.",
                "correct_answer": "$1/2$",
                "answer_explanation": "直接积分得 $1/2$。",
                "content_hash": "upstream-hash",
                "question_type": "subjective",
                "exam_subjects": ["math_1", "math_2", "math_3"],
                "document": {"asset_refs": [ref], "source_page": 12, "format_version": 1},
            }
            data_file = root / "library" / "bundled-library.json"
            data_file.parent.mkdir()
            data_file.write_text(
                json.dumps({"questions": [question], "assetMap": {ref: f"/assets/media/{digest}.png"}}),
                encoding="utf-8",
            )

            [row] = adapt_cxy(root, "b" * 40, question_ids={77})

        self.assertTrue(row["identity"]["lineage_conflict_or_multiple_claims"])
        self.assertEqual(len(row["identity"]["exam_claims"]), 1)
        self.assertEqual(row["identity"]["exam_claims"][0]["year_claimed"], 1987)
        self.assertEqual(row["identity"]["exam_claims"][0]["math_type_claimed"], 1)
        self.assertIsNone(row["identity"]["exam_year"])
        self.assertIsNone(row["identity"]["math_type"])
        self.assertEqual(row["identity"]["book_claims"][0]["edition_label_claimed"], "25")
        self.assertEqual(row["identity"]["book_claims"][0]["group_claimed"], "B")
        self.assertEqual(row["identity"]["book_claims"][0]["question_number_claimed"], "12")
        self.assertEqual(row["availability"]["illustrations_resolved"], 1)
        self.assertTrue(row["content"]["illustrations"][0]["sha256_matches_ref"])

    def test_cxy_missing_asset_is_reported_without_fabricating_a_resource(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="cxy-missing-asset-") as temp:
            root = Path(temp)
            ref = "asset://sha256/" + "c" * 64
            data_file = root / "library" / "bundled-library.json"
            data_file.parent.mkdir()
            data_file.write_text(
                json.dumps({
                    "questions": [{
                        "id": 9, "stem": "x", "correct_answer": "1", "answer_explanation": "x=1",
                        "document": {"asset_refs": [ref]},
                    }],
                    "assetMap": {ref: "/assets/media/missing.png"},
                }),
                encoding="utf-8",
            )
            [row] = adapt_cxy(root, "d" * 40, question_ids={9})

        self.assertEqual(row["availability"]["illustrations_expected"], 1)
        self.assertEqual(row["availability"]["illustrations_resolved"], 0)
        self.assertFalse(row["content"]["illustrations"][0]["exists"])


if __name__ == "__main__":
    unittest.main()

"""Read-only HTTP checks for the first real-paper loop. No student answers submitted."""
import argparse
import json
from pathlib import Path
from urllib.request import build_opener, ProxyHandler
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pymupdf as fitz


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:4173');args=parser.parse_args()
    opener=build_opener(ProxyHandler({}))
    def get(path):
        with opener.open(args.url+path,timeout=15) as response:
            return response.read(),response.headers.get('Content-Type')
    raw,_=get('/api/bootstrap');data=json.loads(raw)
    report=data['loop']['reports'][0];pid=report['paper_id']
    questions=[q for q in data['questions'] if q['paper_id']==pid]
    assert sorted(int(q['number']) for q in questions)==list(range(1,23))
    probes=[p for p in data['loop']['probes'] if p['paper_id']==pid]
    evidence=0;images=0
    for question in questions:
        regions=data['loop']['diagnoses'][question['id']]['regions']
        for i in range(len(regions)):
            raw,mime=get(f"/api/questions/{question['id']}/evidence?region={i}")
            pix=fitz.Pixmap(raw);assert pix.width>100 and pix.height>20 and mime=='image/png';evidence+=1
    for probe in probes:
        raw,mime=get(probe['question_image']);pix=fitz.Pixmap(raw);assert pix.width>100;images+=1
        if not probe['attempts']:
            assert not any(key in probe for key in ('expected','accepted','rubric','payload_json'))
    for path in ['/','/vendor/katex/katex.min.js','/vendor/katex/katex.min.css','/vendor/katex/fonts/KaTeX_Main-Regular.woff2']:
        raw,mime=get(path);assert raw
    result={'questions':len(questions),'evidence_images_decoded':evidence,'probe_question_images_decoded':images,
            'pending_probes':sum(not p['attempts'] for p in probes),'bank_resources':sum(b['id'].startswith('math1-') for b in data['bank']),
            'unsubmitted_answers_hidden':True,'http_assets':True,'scope':'Read-only production verification; test attempts are isolated elsewhere'}
    target=ROOT/'.mathlens/inspection-2026/http-validation.json';target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()

"""Exercise local upload/extraction/read APIs against an isolated library snapshot.

Never opens the source library or starts an Agent. Reports/crops stay outside Git.
"""
import argparse
import csv
import hashlib
import json
import os
import shutil
from pathlib import Path
import sys
import time
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def run(base,library,pdfs,label,cache_from=None):
    import pymupdf
    from fastapi.testclient import TestClient
    from app.config import AppConfig
    from app.main import create_app
    from app.services.papers import PaperService
    from app.storage.database import Database
    from app.bank.paper_candidates import location
    from app.bank.exam_identity import candidates
    work=base/label;data=work/'workspace'
    os.environ.update(MATHLENS_DATA_DIR=str(data),MATHLENS_LIBRARY_DIR=str(library),
                      MATHLENS_CODEX_BIN=str(base/'codex-does-not-exist.exe'))
    config=AppConfig.from_env(ROOT);database=Database(config);database.initialize()
    if cache_from:shutil.copytree(cache_from,data/'ocr-cache')
    service=PaperService(config,database)
    reports=[]
    for pdf in pdfs:
        cached_before=(data/'ocr-cache'/hashlib.sha256(pdf.read_bytes()).hexdigest()).is_dir()
        started=time.perf_counter()
        imported,_=service.import_pdf(pdf.name,pdf.read_bytes(),{},queue_agent=False)
        elapsed=time.perf_counter()-started
        pid=imported['paper']['id']
        with database.session() as conn:
            first=[dict(r) for r in conn.execute('SELECT * FROM questions WHERE paper_id=? ORDER BY CAST(number AS INTEGER)',(pid,))]
            paper=dict(conn.execute('SELECT * FROM papers WHERE id=?',(pid,)).fetchone())
        started=time.perf_counter()
        with database.session(write=True) as conn:repeated=service.analyze(conn,pid)
        repeat_seconds=time.perf_counter()-started
        with database.session() as conn:
            second=[dict(r) for r in conn.execute('SELECT * FROM questions WHERE paper_id=? ORDER BY CAST(number AS INTEGER)',(pid,))]
            assert first==second,'Re-analysis changed question records'
            assert conn.execute('SELECT count(*) FROM learning_tasks').fetchone()[0]==0
            assert conn.execute('SELECT count(*) FROM workflow_jobs').fetchone()[0]==0
            source=location(paper)
            groups={q['number']:candidates(conn,source['year'],source['math_type'],int(q['number']))
                    if source['status']=='located' and source['math_type'] else [] for q in first}
        app=create_app(config,agent_factory=None,manage_agent=False)
        folder=work/pdf.stem;folder.mkdir(parents=True,exist_ok=True)
        for image in (data/'tasks'/pid).glob('page-*.png'):shutil.copy2(image,folder/image.name)
        table=[]
        try:
            with TestClient(app,base_url='http://127.0.0.1') as http,pymupdf.open(pdf) as document:
                response=http.get('/api/papers/'+pid+'/questions');assert response.status_code==200
                cards={q['number']:q for q in response.json()['items']}
                for q in first:
                    regions=json.loads(q['regions_json'] or '[]');issues=[];files=[];codes=[]
                    for i,region in enumerate(regions):
                        page=document[region['page']-1];rect=pymupdf.Rect(region['bbox'])
                        if rect.is_empty or not page.rect.contains(rect):issues.append('bbox_outside_page')
                        crop=folder/f"q-{int(q['number']):02d}-region-{i+1}.png"
                        result=http.get('/api/questions/'+q['id']+'/evidence',params={'index':i})
                        codes.append(result.status_code)
                        if result.status_code==200:crop.write_bytes(result.content);files.append(crop.name)
                        else:issues.append('evidence_http_'+str(result.status_code))
                    ids=groups[q['number']]
                    table.append(dict(number=q['number'],page_start=q['page_start'],page_end=q['page_end'],
                        bbox=json.loads(q['bbox_json']) if q['bbox_json'] else None,regions=regions,
                        raw_match_bank_id=q['match_bank_id'],text_similarity=q['match_score'],
                        matched_bank_id=cards[q['number']]['matched_bank_id'],navigation_candidates=ids,
                        locator_status='not_located' if not ids else 'multiple_candidates' if len(ids)>1 else 'unique_exam_identity',
                        locator_confidence=None,locator_basis='year/math_type/number only; not mathematical equivalence',
                        ocr_confidence=q['ocr_confidence'],evidence_http=codes,crops=files,issues=issues))
        finally:app.state.runtime.close()
        numbers=[int(q['number']) for q in first]
        report=dict(pdf_name=pdf.name,source_sha256=imported['sha256'],paper_id=pid,engine=paper['analysis_engine'],
            warnings=repeated['warnings'],numbers=numbers,continuous_1_to_22=numbers==list(range(1,23)),
            upload_extract_seconds=round(elapsed,3),repeat_analyze_seconds=round(repeat_seconds,3),idempotent=first==second,
            cached_before_upload=cached_before,
            ocr_cache_bytes=sum(p.stat().st_size for p in (data/'ocr-cache'/imported['sha256']).rglob('*') if p.is_file()),
            ocr_cache_total_bytes=sum(p.stat().st_size for p in (data/'ocr-cache').rglob('*') if p.is_file()),
            agent_tasks=0,workflow_jobs=0,questions=table)
        (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        with (folder/'questions.csv').open('w',encoding='utf-8-sig',newline='') as f:
            fields=['number','page_start','page_end','bbox','regions','matched_bank_id','navigation_candidates',
                    'locator_status','locator_confidence','raw_match_bank_id','text_similarity','ocr_confidence','issues']
            writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
            writer.writerows({k:json.dumps(q[k],ensure_ascii=False) if isinstance(q[k],(list,dict)) else q[k] for k in fields} for q in table)
        reports.append(report)
        print(json.dumps({k:v for k,v in report.items() if k!='questions'},ensure_ascii=False),flush=True)
    (work/'summary.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf8')
    return reports


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--library',type=Path,required=True)
    p.add_argument('--label',required=True);p.add_argument('pdf',type=Path,nargs='+')
    p.add_argument('--cache-from',type=Path,help='Reuse page OCR explicitly when only segmentation changes')
    a=p.parse_args()
    if not a.output.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()):
        raise ValueError('Validation output must be inside the system TEMP directory')
    if not a.library.resolve().is_relative_to(a.output.resolve()):
        raise ValueError('Use an isolated library snapshot inside the validation directory')
    if Path(a.label).name!=a.label or a.label in ('.','..'):
        raise ValueError('Use a single directory name as the report label')
    if (a.output/a.label).exists():raise ValueError('Use a fresh report/workspace label')
    run(a.output.resolve(),a.library.resolve(),a.pdf,a.label,a.cache_from)


if __name__=='__main__':main()

"""Persist observable local PDF progress without requiring the Agent lock."""
import json
from pathlib import Path
import time
import uuid
from app.learning.loop import stamp


def write_progress(data,paper_id,**fields):
    folder=Path(data)/'tasks'/paper_id
    folder.mkdir(parents=True,exist_ok=True)
    path=folder/'progress.json'
    current=json.loads(path.read_text(encoding='utf8')) if path.is_file() else {}
    value={**current,**fields,'paper_id':paper_id,'updated_at':stamp()}
    tmp=folder/('progress-'+uuid.uuid4().hex+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8')
    try:
        for attempt in range(5):
            try:
                tmp.replace(path)
                break
            except OSError as exc:
                # Windows readers/scanners can briefly hold the destination.
                # Keep atomic replacement; a persistent or unrelated failure
                # must remain visible and leave the previous JSON intact.
                if getattr(exc,'winerror',None) not in (5,32,33) or attempt==4:
                    raise
                time.sleep(.05*(2**attempt))
    finally:
        try:tmp.unlink(missing_ok=True)
        except OSError:pass
    return value


def list_progress(data):
    results=[]
    for path in (Path(data)/'tasks').glob('*/progress.json'):
        try:results.append(json.loads(path.read_text(encoding='utf8')))
        except (OSError,ValueError):continue
    return sorted(results,key=lambda v:v['updated_at'],reverse=True)[:8]


def interrupt_old_progress(data):
    for value in list_progress(data):
        if value.get('status')=='running':
            write_progress(data,value['paper_id'],status='interrupted',
                           message='上次本地识别中断，原PDF保留；可从本卷重新开始分析。')

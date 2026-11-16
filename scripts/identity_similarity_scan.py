"""Read-only fuzzy duplicate candidates for source-maintenance review.

This tool never writes a library or promotes a candidate to an identity.  It
uses normalized character n-gram Jaccard scores only as a review queue.
"""
import argparse
from collections import Counter
import json
import re
import sqlite3
import time
import unicodedata
from pathlib import Path

NGRAM=3
PUNCT=re.compile(r'[\s\.,;:!?，。；：！？、（）()\[\]【】{}《》“”"\'`~·…—_*#/@|\\]+')
NUMBER_PREFIX=re.compile(r'^\s*(?:第\s*\d+\s*题\s*|\(?\d{1,3}\s*[\.、\)）:]\s*)')
OPTION_PREFIX=re.compile(r'^\s*[A-DＡ-Ｄ]\s*[\.、\)）:]\s*',re.I)
LAYOUT=(r'left','right','displaystyle','textstyle','scriptstyle','limits','nolimits','middle','!',',',';','quad','qquad','hspace')


def normalize(value):
    value=unicodedata.normalize('NFKC',str(value or '')).replace('\r\n','\n')
    for command in LAYOUT:value=value.replace('\\'+command,'')
    value=value.replace('\\leqslant','<=').replace('\\geqslant','>=')
    value=value.replace('\\le','<=').replace('\\ge','>=').replace('\\neq','!=')
    value=value.replace('\\dfrac','\\frac')
    value=NUMBER_PREFIX.sub('',value)
    value=OPTION_PREFIX.sub('',value)
    # Keep content inside LaTeX commands while discarding command spelling,
    # braces and punctuation.  This makes cxy LaTeX and HTML text comparable.
    value=re.sub(r'\\[A-Za-z]+', '', value)
    value=PUNCT.sub('',value)
    return value.casefold()


def grams(value):
    value=normalize(value)
    if not value:return set()
    if len(value)<NGRAM:return {value}
    return {value[i:i+NGRAM] for i in range(len(value)-NGRAM+1)}


def jaccard(left,right):
    if not left or not right:return 0.0
    return len(left&right)/len(left|right)


def score(left,right):
    stem=jaccard(grams(left['stem']),grams(right['stem']))
    options_left=left.get('options',[]);options_right=right.get('options',[])
    if options_left and options_right:
        option_scores=[jaccard(grams(a),grams(b)) for a,b in zip(options_left,options_right)]
        options=sum(option_scores)/max(len(options_left),len(options_right))
        return 0.7*stem+0.3*options,stem,options
    return stem,stem,None


def _record(row,resources,source_records):
    bid=row['id'];record=source_records.get(bid)
    if record:
        stem=record.get('stem',{}).get('text','')
        options=[o.get('content',{}).get('text','') for o in record.get('options',[])]
    else:
        stem=row['stem'] or '';options=[]
    resource=resources.get(bid);metadata=json.loads(resource['metadata_json'] or '{}') if resource else {}
    return dict(bank_id=bid,stem=stem,options=options,collection_id=row['collection_id'],
                collection_label=metadata.get('collection_id') or row['collection_id'],book=metadata.get('book'),
                source=row['source'],source_uid=source_records.get(bid,{}).get('source_uid'))


def _library(path):
    path=Path(path).resolve()/'library.db'
    if not path.is_file():raise ValueError('library.db not found')
    conn=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True);conn.row_factory=sqlite3.Row
    try:
        rows=list(conn.execute('SELECT * FROM bank_questions'))
        resources={row['bank_id']:row for row in conn.execute('SELECT * FROM bank_resources')}
        source_records={}
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='bank_source_records'").fetchone():
            source_records={row['bank_id']:json.loads(row['record_json']) for row in conn.execute('SELECT bank_id,record_json FROM bank_source_records')}
        return [_record(row,resources,source_records) for row in rows]
    finally:conn.close()


def _input(path):
    values=[json.loads(line) for line in Path(path).read_text(encoding='utf8').splitlines() if line.strip()]
    return [dict(bank_id=None,source_uid=r['source_uid'],stem=r['stem']['text'],
                 options=[o['content']['text'] for o in r.get('options',[])],collection_id=None,
                 collection_label=None,book=r.get('book'),source=r['source_id'],record=r) for r in values]


def scan(input_path,library_path,*,top=3):
    started=time.perf_counter();library=_library(library_path);incoming=_input(input_path);items=[]
    for value in incoming:
        candidates=[]
        for target in library:
            total,stem,options=score(value,target)
            candidates.append(dict(bank_id=target['bank_id'],source=target['source'],collection_id=target['collection_id'],
                                   collection_label=target['collection_label'],book=target['book'],score=round(total,6),
                                   stem_score=round(stem,6),options_score=None if options is None else round(options,6),
                                   input_uid=value['source_uid'],input_part=value['book'],
                                   input_stem=value['stem'][:80],library_stem=target['stem'][:80]))
        candidates.sort(key=lambda row:(-row['score'],row['bank_id']))
        items.append(dict(source_uid=value['source_uid'],candidates=candidates[:top],best_score=candidates[0]['score'] if candidates else 0.0))
    distribution=Counter('>=0.9' if x['best_score']>=.9 else '0.75-0.9' if x['best_score']>=.75 else '0.6-0.75' if x['best_score']>=.6 else '<0.6' for x in items)
    overlap={}
    for target_collection in ('zhangyu-1000','zhangyu-1000-basic'):
        matched=[x for x in items if any(c['collection_id']==target_collection for c in x['candidates'])]
        high=[x for x in items if any(c['collection_id']==target_collection and c['score']>=.75 for c in x['candidates'])]
        overlap[target_collection]=dict(top3=len(matched),score_ge_075=len(high))
    draft={'schema':'mathlens.bank-identities/v1','source_id':incoming[0]['source'] if incoming else None,
           'revision':incoming[0]['record']['revision'] if incoming else None,'entries':[
               dict(source_uid=x['source_uid'],decision='pending',candidate_bank_ids=[c['bank_id'] for c in x['candidates']],
                    reason='similarity candidate; maintenance decision required',evidence='character n-gram Jaccard; not an automatic merge') for x in items]}
    return dict(schema='mathlens.bank-similarity-scan/v1',input=str(input_path),library=str(library_path),
                input_count=len(items),library_count=len(library),elapsed_seconds=round(time.perf_counter()-started,3),
                score_distribution={key:distribution.get(key,0) for key in ('>=0.9','0.75-0.9','0.6-0.75','<0.6')},
                overlap_estimate=overlap,candidates=items,identities_draft=draft)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',required=True,type=Path);parser.add_argument('--library',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();value=scan(args.input,args.library);args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps({'output':str(args.output),'input_count':value['input_count'],'library_count':value['library_count'],'elapsed_seconds':value['elapsed_seconds']},ensure_ascii=False))


if __name__=='__main__':main()

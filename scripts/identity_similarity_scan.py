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
PUNCT=re.compile(r'[\s.,;:!?\uFF0C\u3002\uFF1B\uFF1A\uFF01\uFF1F\u3001\uFF08\uFF09()\[\]{}\u3010\u3011\u300A\u300B\u201C\u201D\'`~\u00B7\u2026\u2014_*#/@|\\]+')
NUMBER_PREFIX=re.compile(r'^\s*(?:\u7B2C\s*\d+\s*\u9898\s*|\(?\d{1,3}\s*[\.\u3001\uFF09:\uFF1A]\s*)')
OPTION_PREFIX=re.compile(r'^\s*[A-D\uFF21-\uFF24]\s*[\.\u3001\uFF09:\uFF1A]\s*',re.I)
LAYOUT=(r'left','right','displaystyle','textstyle','scriptstyle','limits','nolimits','middle','mathrm','mathit','mathbf','quad','qquad','hspace','vspace')
GENERIC_STEM=re.compile(r'^(?:\u4e0b\u5217|\u4ee5\u4e0b).{0,40}(?:\u662f|\u4e3a|\u6b63\u786e|\u9519\u8bef|\u53d1\u6563|\u6536\u655b)')
EXAM_CLAIM=re.compile(r'(?P<year>(?:19|20)\d{2})\s*\u5e74?[^\u6570]{0,4}\u6570\s*(?P<types>[\u4e00\u4e8c\u4e09123]+)')
TYPE_MAP={'\u4e00':1,'\u4e8c':2,'\u4e09':3,'1':1,'2':2,'3':3}


def normalize(value):
    value=unicodedata.normalize('NFKC',str(value or '')).replace('\r\n','\n')
    for command in LAYOUT:value=value.replace('\\'+command,'')
    value=re.sub(r'\\(?:,|!|;|:|\s)', '', value)
    value=value.replace('\\leqslant','<=').replace('\\geqslant','>=')
    value=value.replace('\\le','<=').replace('\\ge','>=').replace('\\neq','!=')
    value=value.replace('\\dfrac','\\frac').replace('\\tfrac','\\frac')
    value=NUMBER_PREFIX.sub('',value)
    value=OPTION_PREFIX.sub('',value)
    # Preserve mathematical command names as tokens; only layout commands
    # above are removed.
    value=re.sub(r'\\([A-Za-z]+)', r' \1 ', value)
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


def parse_exam_claims(value):
    """Parse explicit year/category/number claims without inferring numbers."""
    text=unicodedata.normalize('NFKC',str(value or ''));claims=[]
    matches=list(EXAM_CLAIM.finditer(text))
    for index,match in enumerate(matches):
        year=int(match.group('year'));types=''.join(match.group('types'));tail=text[match.end():matches[index+1].start() if index+1<len(matches) else len(text)]
        first=re.split(r'[;；]',tail,1)[0]
        for token in types:
            math_type=TYPE_MAP[token];number=None
            if len(types)>1:
                number_match=re.search(r'(?:'+re.escape(token)+r'\s*)(?:第\s*)?(\d{1,3})\s*\u9898?',first)
                if number_match:number=int(number_match.group(1))
            else:
                number_match=re.search(r'(?:第\s*)?(\d{1,3})\s*\u9898',first) or re.search(r'[\uFF08(]\s*(\d{1,3})\s*[\uFF09)]',first)
                if number_match:number=int(number_match.group(1))
            claims.append(dict(year=year,math_type=math_type,number=number))
    seen=set();result=[]
    for claim in claims:
        key=(claim['year'],claim['math_type'],claim['number'])
        if key not in seen:seen.add(key);result.append(claim)
    return result


def score(left,right):
    stem=jaccard(grams(left['stem']),grams(right['stem']))
    options_left=left.get('options',[]);options_right=right.get('options',[])
    normalized_left=normalize(left['stem']);normalized_right=normalize(right['stem'])
    generic=bool(len(normalized_left)<20 or len(normalized_right)<20 or
                 GENERIC_STEM.match(normalized_left) or GENERIC_STEM.match(normalized_right))
    if options_left and options_right:
        option_scores=[jaccard(grams(a),grams(b)) for a,b in zip(options_left,options_right)]
        options=sum(option_scores)/max(len(options_left),len(options_right))
        total=0.2*stem+0.8*options if generic else 0.7*stem+0.3*options
        return total,stem,options,generic
    return (min(stem,.6) if generic else stem),stem,None,generic


def _record(row,resources,source_records,identities=None):
    bid=row['id'];record=source_records.get(bid)
    resource=resources.get(bid);metadata=json.loads(resource['metadata_json'] or '{}') if resource else {}
    if record:
        stem=record.get('stem',{}).get('text','')
        options=[o.get('content',{}).get('text','') for o in record.get('options',[])]
    else:
        # Legacy image banks often store a navigation label in bank_questions;
        # it is not a comparable question stem.  Count text only when a
        # standard text record is present.
        stem=(row['stem'] or '') if metadata.get('schema')=='mathlens.bank-record/v1' else ''
        options=[]
    identity=(identities or {}).get(bid,{})
    return dict(bank_id=bid,stem=stem,options=options,scannable_text=bool(normalize(stem) or any(normalize(x) for x in options)),collection_id=row['collection_id'],
                collection_label=metadata.get('collection_id') or row['collection_id'],book=metadata.get('book'),
                source=row['source'],source_uid=source_records.get(bid,{}).get('source_uid'),
                year=identity.get('year'),math_type=identity.get('math_type'),number=identity.get('number'))


def _library(path):
    path=Path(path).resolve()/'library.db'
    if not path.is_file():raise ValueError('library.db not found')
    conn=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True);conn.row_factory=sqlite3.Row
    try:
        rows=list(conn.execute('SELECT * FROM bank_questions'))
        identities={row['bank_id']:dict(row) for row in conn.execute('SELECT bank_id,year,math_type,number FROM bank_identity')} if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='bank_identity'").fetchone() else {}
        resources={row['bank_id']:row for row in conn.execute('SELECT * FROM bank_resources')}
        source_records={}
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='bank_source_records'").fetchone():
            source_records={row['bank_id']:json.loads(row['record_json']) for row in conn.execute('SELECT bank_id,record_json FROM bank_source_records')}
        return [_record(row,resources,source_records,identities) for row in rows]
    finally:conn.close()


def _input(path):
    values=[json.loads(line) for line in Path(path).read_text(encoding='utf8').splitlines() if line.strip()]
    return [dict(bank_id=None,source_uid=r['source_uid'],stem=r['stem']['text'],
                 options=[o['content']['text'] for o in r.get('options',[])],collection_id=None,
                 collection_label=None,book=r.get('book'),source=r['source_id'],record=r,
                 exam_claims=parse_exam_claims(r.get('original',{}).get('source_text',''))) for r in values]


def scan(input_path,library_path,*,top=3):
    started=time.perf_counter();library=_library(library_path);incoming=_input(input_path);items=[]
    exam_index={}
    for target in library:
        if target.get('collection_id')=='zhenti' and target.get('year') and target.get('math_type') and target.get('number'):
            exam_index.setdefault((int(target['year']),int(target['math_type']),int(target['number'])),[]).append(target)
    exam_claim_samples=[];exam_unresolved_samples=[];resolved_count=0;unresolved_count=0;claim_count=0
    for value in incoming:
        candidates=[]
        for target in library:
            total,stem,options,generic=score(value,target)
            candidates.append(dict(bank_id=target['bank_id'],source=target['source'],collection_id=target['collection_id'],
                                   collection_label=target['collection_label'],book=target['book'],score=round(total,6),
                                   stem_score=round(stem,6),options_score=None if options is None else round(options,6),
                                   generic_stem=generic,score_capped=bool(generic and (not value.get('options') or not target.get('options'))),
                                   input_uid=value['source_uid'],input_part=value['book'],
                                   input_stem=value['stem'][:80],library_stem=target['stem'][:80]))
        candidates.sort(key=lambda row:(-row['score'],row['bank_id']))
        claim_candidates=[]
        for claim in value.get('exam_claims',[]):
            claim_count+=1;matches=exam_index.get((claim['year'],claim['math_type'],claim['number']),[])
            if len(matches)==1:
                resolved_count+=1;target=matches[0]
                candidate=dict(reason='exam_claim',source_uid=value['source_uid'],claim=claim,bank_id=target['bank_id'],collection_id=target['collection_id'],
                               book=target['book'],input_stem=value['stem'][:80],library_stem=target['stem'][:80],score=1.0)
                claim_candidates.append(candidate)
                if len(exam_claim_samples)<5:exam_claim_samples.append(candidate)
            else:
                unresolved_count+=1;item=dict(reason='exam_claim_unresolved',source_uid=value['source_uid'],claim=claim,
                    candidate_bank_ids=[x['bank_id'] for x in matches],input_stem=value['stem'][:80])
                if len(exam_unresolved_samples)<5:exam_unresolved_samples.append(item)
                claim_candidates.append(item)
        items.append(dict(source_uid=value['source_uid'],candidates=candidates[:top],exam_claim_candidates=claim_candidates,
                          best_score=candidates[0]['score'] if candidates else 0.0))
    distribution=Counter('>=0.9' if x['best_score']>=.9 else '0.75-0.9' if x['best_score']>=.75 else '0.6-0.75' if x['best_score']>=.6 else '<0.6' for x in items)
    collection_stats={}
    for target in library:
        bucket=collection_stats.setdefault(target['collection_id'],dict(total=0,scannable_text=0,no_scannable_text=0))
        bucket['total']+=1;bucket['scannable_text']+=int(target.get('scannable_text',False));bucket['no_scannable_text']+=int(not target.get('scannable_text',False))
    overlap={}
    for target_collection in ('zhangyu-1000','zhangyu-1000-basic'):
        matched=[x for x in items if any(c['collection_id']==target_collection for c in x['candidates'])]
        high=[x for x in items if any(c['collection_id']==target_collection and c['score']>=.75 for c in x['candidates'])]
        overlap[target_collection]=dict(top3=len(matched),score_ge_075=len(high))
    draft_entries=[]
    for x in items:
        claims=x['exam_claim_candidates'];similar=[c['bank_id'] for c in x['candidates']]
        if claims:
            draft_entries.append(dict(source_uid=x['source_uid'],decision='pending',candidate_bank_ids=list(dict.fromkeys(similar+[c['bank_id'] for c in claims if c.get('bank_id')])),
                exam_claims=claims,reason='exam claim or similarity candidate; maintenance decision required',evidence='source claim and/or character n-gram Jaccard; not an automatic merge'))
        else:
            draft_entries.append(dict(source_uid=x['source_uid'],decision='pending',candidate_bank_ids=similar,
                reason='similarity candidate; maintenance decision required',evidence='character n-gram Jaccard; not an automatic merge'))
    draft={'schema':'mathlens.bank-identities/v1','source_id':incoming[0]['source'] if incoming else None,
           'revision':incoming[0]['record']['revision'] if incoming else None,'entries':[
               entry for entry in draft_entries]}
    return dict(schema='mathlens.bank-similarity-scan/v1',input=str(input_path),library=str(library_path),
                input_count=len(items),library_count=len(library),elapsed_seconds=round(time.perf_counter()-started,3),
                score_distribution={key:distribution.get(key,0) for key in ('>=0.9','0.75-0.9','0.6-0.75','<0.6')},
                exam_claim_count=claim_count,exam_claim_resolved=resolved_count,exam_claim_unresolved=unresolved_count,
                exam_claim_samples=exam_claim_samples,exam_claim_unresolved_samples=exam_unresolved_samples,
                library_collection_text_stats=collection_stats,
                overlap_estimate=overlap,candidates=items,identities_draft=draft)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',required=True,type=Path);parser.add_argument('--library',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();value=scan(args.input,args.library);args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps({'output':str(args.output),'input_count':value['input_count'],'library_count':value['library_count'],'elapsed_seconds':value['elapsed_seconds']},ensure_ascii=False))


if __name__=='__main__':main()

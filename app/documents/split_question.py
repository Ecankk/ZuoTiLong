"""A horizontal cut in original PDF coordinates; no OCR/model execution."""
import copy,json,math
from app.documents.pdf import PIPELINE_VERSION

def split(question,cut,data,source_sha256):
    regions=json.loads(question['regions_json'] or '[]');page=cut['page'];y=cut['y']
    if type(page) is not int or page<1 or type(y) not in (int,float) or not math.isfinite(y):raise ValueError('拆分页码或切线坐标无效')
    upper=[];lower=[];crossed=False
    for original in regions:
        r=copy.deepcopy(original);x0,y0,x1,y1=r['bbox']
        if r['page']<page or r['page']==page and y1<=y:upper.append(r)
        elif r['page']>page or r['page']==page and y0>=y:lower.append(r)
        else:
            crossed=True;a=copy.deepcopy(r);a['bbox']=[x0,y0,x1,y];upper.append(a)
            r['bbox']=[x0,y,x1,y1];lower.append(r)
    if not crossed or not upper or not lower:raise ValueError('切线必须位于此题区域内部并产生上下两部分')
    for part in (upper,lower):part.sort(key=lambda r:(r['page'],r['bbox'][1],r['bbox'][0]))
    texts=[question.get('stem') or '', '待补充题干']
    # The extraction cache stores positioned OCR/text-layer lines in PDF points.
    folder=data/'ocr-cache'/source_sha256
    cache=next((p for p in (folder/f'{PIPELINE_VERSION}-ocr.json',folder/f'{PIPELINE_VERSION}-text.json') if p.is_file()),None)
    if cache:
        pages=json.loads(cache.read_text(encoding='utf8'))['pages'];lines=[[],[]]
        for p in pages:
            for block in p.get('blocks',[]):
                if block.get('anchor_only') or not block.get('text') or not block.get('bbox'):continue
                x0,y0,x1,y1=block['bbox'];x=(x0+x1)/2;yc=(y0+y1)/2
                if not any(r['page']==p['page_number'] and r['bbox'][0]<=x<=r['bbox'][2] and r['bbox'][1]<=yc<=r['bbox'][3] for r in regions):continue
                side=0 if p['page_number']<page or p['page_number']==page and yc<y else 1
                lines[side].append(block['text'])
        if any(lines):texts=['\n'.join(lines[0]) or texts[0], '\n'.join(lines[1]) or texts[1]]
    return upper,lower,texts

"""Display-only names; stored source names and evidence remain unchanged."""
import re

def paper_title(value):
    return re.sub(r'((?:19|20)\d{2})\s*年?\s*(?:数学|数)\s*([一二三123])',
        lambda m:m[1]+'年数'+{'1':'一','2':'二','3':'三'}.get(m[2],m[2]),value or '')

def paper(value):
    return dict(value,title=paper_title(value['title'])) if value is not None else None

def exam_title(year,math_type):
    return f'{year}年数'+{1:'一',2:'二',3:'三'}[int(math_type)]

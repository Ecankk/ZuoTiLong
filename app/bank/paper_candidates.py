"""Read-only source locators; metadata never proves mathematical identity."""
import json
import re

from app.bank.access import preferences


POLICY = ('以下仅为原卷出处导航，不是同题确认或就绪证明。年份、类别、题号只定位候选；'
          '须用read_bank实际核对题干、选项、图及条件，并核当前材料和标注版本。'
          '未命中只表示该出处未定位，不表示题库没有相关考点；补强选题仍使用统一题池。')


def location(paper):
    evidence = {key: paper.get(key) or '' for key in ('title', 'source_name')}
    years, types = set(), set()
    for value in evidence.values():
        years.update(re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)', value))
        types.update({'一': 1, '二': 2, '三': 3, '1': 1, '2': 2, '3': 3}[m]
                     for m in re.findall(r'(?:数学|数)\s*[（(]?\s*([一二三123])(?![一二三\d])', value))
    stored = paper.get('math_type')
    if type(stored) is int and stored in (1, 2, 3):
        types.add(stored)
    result = {'year': next(iter(years)) if len(years) == 1 else None,
              'math_type': next(iter(types)) if len(types) == 1 else None,
              'basis': '仅使用试卷title/source_name及已保存math_type；不使用做卷日期、备考设置或OCR相似度。'}
    if len(years) > 1 or len(types) > 1:
        return {**result, 'status': 'ambiguous', 'reason': '出处线索存在多个年份或数学类别，不自动选择。'}
    if not years:
        return {**result, 'status': 'missing_year', 'reason': '缺少唯一年份，不猜测试卷出处。'}
    return {**result, 'status': 'located', 'category_known': bool(types)}


def question_numbers(conn, paper, selected_number=None):
    if selected_number is not None:
        values = [selected_number]
    else:
        latest = conn.execute('''SELECT source_sha256,report_json FROM agent_reports
            WHERE paper_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1''', (paper['id'],)).fetchone()
        report = json.loads(latest['report_json']) if latest and latest['source_sha256'] == paper.get('source_sha256') else None
        # Ignore stale extraction rows once a current report defines the scope.
        values = ([q['number'] for q in report.get('questions', [])] if report is not None else
                  [q[0] for q in conn.execute('SELECT number FROM questions WHERE paper_id=?', (paper['id'],))])
    return sorted({int(n) for n in values if type(n) in (int, str)
                   and re.fullmatch(r'[0-9]{1,3}', str(n)) and 1 <= int(n) <= 999})[:100]


def locate(conn, paper, *, selected_number=None):
    paper = dict(paper)
    source = location(paper)
    numbers = question_numbers(conn, paper, selected_number)
    result = {'navigation_only': True, 'locator': source, 'policy': POLICY,
              'candidates': [], 'not_located_numbers': numbers}
    if source['status'] != 'located' or not numbers:
        return result
    reserved = {(r['math_type'], str(r['year'])) for r in preferences(conn)['reserved']}
    groups = {number: [] for number in numbers}
    params = [source['year'], *numbers]
    query = '''SELECT i.bank_id,i.math_type,i.year,i.number FROM bank_identity i
        JOIN bank_questions b ON b.id=i.bank_id JOIN bank_resources r ON r.bank_id=b.id
        WHERE i.year=? AND i.number IN (''' + ','.join('?' for _ in numbers) + ')'
    if source['math_type'] is not None:
        query += ' AND i.math_type=?'
        params.append(source['math_type'])
    for row in conn.execute(query + ' ORDER BY i.number,i.math_type,i.bank_id', params):
        if (row['math_type'], str(row['year'])) not in reserved:
            groups[row['number']].append({key: row[key] for key in ('bank_id', 'math_type', 'year', 'number')})
    result['candidates'] = [{'number': number, 'sources': entries} for number, entries in groups.items() if entries]
    result['not_located_numbers'] = [number for number, entries in groups.items() if not entries]
    return result

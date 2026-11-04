"""Scoped original-question review inputs and conservative report merging."""
from __future__ import annotations

from app.storage.paths import paper_path, relative_file, resolve_file, connection_data
import copy
import json
import re

from app.storage.images import image_records, image_path


def normalize_request(value):
    if not isinstance(value, dict) or set(value) - {'question_id', 'report_id', 'note', 'image_ids', 'image_roles'}:
        raise ValueError('单题复核材料不合法')
    if any(not isinstance(value.get(k), str) or not value[k] or len(value[k]) > 200
           for k in ('question_id', 'report_id')):
        raise ValueError('请选择当前分析中的原题')
    note = value.get('note', '')
    ids = value.get('image_ids', [])
    roles = value.get('image_roles', {})
    if not isinstance(note, str) or len(note) > 4000:
        raise ValueError('补充说明最多4000字')
    if not isinstance(ids, list) or len(ids) > 4 or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('最多附加4张不同的局部照片')
    if not isinstance(roles, dict) or set(roles) - set(ids) or any(
            r not in ('own_work', 'marking', 'external_solution') for r in roles.values()):
        raise ValueError('补图内容类型不合法')
    return {'question_id': value['question_id'], 'report_id': value['report_id'], 'note': note.strip(),
            'image_ids': ids, 'image_roles': {i: roles.get(i, 'own_work') for i in ids}}


def scoped_indexes(items, number):
    # Legacy report issues are free text. Only explicitly single-question
    # issues may be resolved locally; global/ambiguous issues stay intact.
    def numbers(text):
        return {int(n) for match in re.findall(r'第\s*(\d+)\s*题|\bQ\s*(\d+)\b', text, re.I)
                for n in match if n}
    return [i for i, text in enumerate(items) if numbers(text) == {number}]


def capture_review(conn, root, data, paper_id, request):
    from app.learning.tasks import resource_digest, digest
    request = normalize_request(request)
    row = conn.execute('SELECT * FROM questions WHERE id=? AND paper_id=?',
                       (request['question_id'], paper_id)).fetchone()
    if not row:
        raise ValueError('复核题目不属于当前试卷')
    latest = conn.execute('SELECT * FROM agent_reports WHERE paper_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1',
                          (paper_id,)).fetchone()
    if not latest or latest['id'] != request['report_id']:
        raise ValueError('分析版本已变化，请打开最新分析后重新核对本题')
    report = json.loads(latest['report_json'])
    number = int(row['number'])
    question = next((q for q in report['questions'] if q['number'] == number), None)
    if not question:
        raise ValueError('当前报告没有该题，请重新分析本卷')
    paper = conn.execute('SELECT source_path FROM papers WHERE id=?', (paper_id,)).fetchone()
    if report['source_sha256'] != resource_digest(paper_path(data,paper[0],root), data):
        raise ValueError('原PDF已改变，请重新分析本卷')
    images = [{**record, 'actual_sha256': resource_digest(image_path(record, data), data)}
              for record in image_records(conn, request['image_ids'])]
    issues = report.get('review', {}).get('issues', [])
    limits = report.get('limitations', [])
    return {'request': request, 'question': question, 'question_sha256': digest(dict(row)),
            'images': images, 'issues': issues, 'limitations': limits,
            'resolvable_issue_indexes': scoped_indexes(issues, number),
            'resolvable_limitation_indexes': scoped_indexes(limits, number)}


def merge_review(inputs, result, author):
    from app.learning.contracts import REPORT, validate_result, VERSION
    scope = inputs['question_review']
    base = next(json.loads(r['report_json']) for r in inputs['reports']
                if r['id'] == scope['request']['report_id'])
    if result['question']['number'] != scope['question']['number']:
        raise ValueError('单题复核只能更新指定题号')
    for key, allowed in (('resolved_issue_indexes', 'resolvable_issue_indexes'),
                         ('resolved_limitation_indexes', 'resolvable_limitation_indexes')):
        if not set(result[key]).issubset(scope[allowed]):
            raise ValueError('单题复核不能移除其他题或整卷的未决问题')
    report = {k: copy.deepcopy(base[k]) for k in REPORT['properties'] if k in base}
    report['questions'] = [copy.deepcopy(result['question']) if q['number'] == result['question']['number'] else q
                           for q in report['questions']]
    issues = [s for i, s in enumerate(scope['issues']) if i not in result['resolved_issue_indexes']]
    issues += [s for s in result['review']['issues'] if s not in issues]
    # Do not let clearing a text issue conceal a second unresolved question.
    for q in report['questions']:
        e = q.get('answer_evidence', {})
        if (q.get('evidence_status') == 'missing' or
                q['correctness'] == 'unknown' and e.get('student_state') == 'unreadable' or
                e.get('marking') == 'correct' and q['correctness'] == 'wrong'):
            issue = f"第{q['number']}题仍有影响判定的材料或批改疑点"
            if issue not in issues:
                issues.append(issue)
    if result['review']['status'] == 'verified' and result['review']['issues']:
        raise ValueError('本题核对通过不能仍有未决问题')
    status = 'needs_review' if issues or result['review']['status'] != 'verified' else 'verified'
    completion = result['completion']
    if status != 'verified' and completion == 'complete':
        raise ValueError('其他题或整卷仍需核对，不能标整卷完整通过')
    report.update(author=author, method=base['method'] + '；原题局部复核',
                  summary=base['summary'], priorities=copy.deepcopy(result['priorities']),
                  review={'status': status, 'issues': issues})
    report['limitations'] = [s for i, s in enumerate(scope['limitations'])
                             if i not in result['resolved_limitation_indexes']]
    if completion != 'complete' and not report['limitations']:
        report['limitations'] = issues or ['本题仍需核对清晰材料']
    # Reuse all ordinary report semantics/coverage checks on the merged report.
    validate_result({'schema_version': VERSION, 'task_id': 'scoped-review', 'kind': 'analyze_paper',
                     'paper_id': inputs['paper']['id'], 'input_revision': '0' * 64, 'author': author,
                     'result': {'completion': completion, 'report': report}}, 'analyze_paper')
    report.update(completion=completion, probes=[],
                  revision={'kind': 'review_question', 'parent_report_id': scope['request']['report_id'],
                            'question_id': scope['request']['question_id']})
    return report

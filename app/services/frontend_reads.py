"""Saved resource projections for the routed UI; no learning writes or Agent calls."""
from copy import deepcopy
import json
from threading import Lock

from app.bank.access import public_bank, access
from app.bank.paper_candidates import location
from app.bank.exam_identity import metadata, select as select_exam
from app.common import rows, json_load
from app.errors import ServiceError
from app.knowledge import index, catalog
from app.learning.plans import practice_state, plan_goals
from app.learning.loop import probe_payload
from app.learning.report_contract import present_diagnosis

PRACTICE_STATUSES = ('pending', 'grading', 'graded', 'needs_supplement', 'inactive')


def page(items, offset=0, limit=20):
    if offset < 0 or not 1 <= limit <= 100:
        raise ValueError('分页参数不合法')
    return dict(items=items[offset:offset+limit], total=len(items), offset=offset, limit=limit,
                next_offset=offset+limit if offset+limit < len(items) else None)


def practice_counts(items):
    unique = {i['id']: i for i in items}.values()
    counts = {s: 0 for s in PRACTICE_STATUSES}
    for item in unique:
        counts[item['status']] += 1
    return dict(counts, total=sum(counts.values()))


def attempt(row):
    value = {k: row[k] for k in ('id', 'probe_id', 'response', 'elapsed_seconds', 'created_at')}
    value.update(image_ids=json.loads(row['images_json']), image_roles=json.loads(row['image_roles_json']),
                 answer_exposed=bool(row['answer_exposed']), assessment=json_load(row['assessment_json'], None))
    if value['assessment'] and value['assessment'].get('method') == 'explicit_answer_match':
        value['assessment'] = None
    return value


class FrontendReads:
    def __init__(self, runtime):
        self.rt = runtime
        self._knowledge_lock = Lock()
        self._knowledge_key = None
        self._knowledge_value = None
        self._navigation_lock = Lock()
        self._navigation_key = None
        self._navigation_value = None
        self._cards_lock=Lock()
        self._cards_key=self._cards_value=None
    def close(self):
        self._navigation_key=self._navigation_value=None
        self._knowledge_key=self._knowledge_value=None
        self._cards_key=self._cards_value=None

    def _navigation(self):
        # Routed UI resources reuse validated projections while both databases
        # are unchanged. Official material imports also commit to the library.
        with self._navigation_lock:
            key=self.rt.workspace.revision()
            if self._navigation_value is None or key!=self._navigation_key:
                bank=self._navigation_value['bank'] if self._navigation_key and key[1]==self._navigation_key[1] else None
                value=self.rt.knowledge_links.resource_snapshot(bank)
                self._navigation_value=value
                self._navigation_key=key if key==self.rt.workspace.revision() else None
            return self._navigation_value

    def _knowledge(self):
        # Share the existing version observers, never compare versions obtained
        # from freshly opened connections. Only the evidence projection is cached.
        with self._knowledge_lock:
            key = self.rt.workspace.revision()
            if key != self._knowledge_key or self._knowledge_value is None:
                with self.rt.database.session() as conn:
                    value = index.snapshot(conn)
                self._knowledge_value = value
                self._knowledge_key = key if key == self.rt.workspace.revision() else None
            return deepcopy(self._knowledge_value)

    def _topics(self, source_id):
        return [{'topic_id': n['skill_id'], 'name': n['label']} for n in self._knowledge()['nodes']
                if any(s['source_id'] == source_id and s['mapping_status'] == 'current' for s in n['scopes'])]

    def _paper(self, conn, paper_id):
        row = conn.execute('SELECT * FROM papers WHERE id=?', (paper_id,)).fetchone()
        if not row or not self.rt.config.demo and paper_id.startswith('paper-demo-'):
            raise ServiceError('试卷不存在', 404)
        return dict(row)

    def _paper_card(self, conn, item):
        result = {k: item[k] for k in ('id', 'title', 'exam_date', 'total_score', 'archived_at', 'created_at', 'updated_at')}
        result.update(score=item['score'] if item['score_confirmed_at'] else None,
                      score_confirmed=bool(item['score_confirmed_at']), analysis_status=item['import_status'])
        counts = {s: 0 for s in ('correct', 'wrong', 'partial', 'unknown')}
        for row in conn.execute('SELECT correctness,count(*) n FROM questions WHERE paper_id=? GROUP BY correctness', (item['id'],)):
            counts[row[0] or 'unknown'] = row[1]
        result['counts'] = dict(counts, total=sum(counts.values()))
        return result

    def papers(self, archived='0', offset=0, limit=20):
        if archived not in ('0', '1', 'all'):
            raise ValueError('归档筛选不合法')
        with self.rt.database.session() as conn:
            values = rows(conn, 'SELECT * FROM papers ORDER BY COALESCE(exam_date,created_at) DESC,created_at DESC,id DESC')
            selected = [v for v in values if (self.rt.config.demo or not v['id'].startswith('paper-demo-'))
                        and (archived == 'all' or bool(v['archived_at']) == (archived == '1'))]
            result = page(selected, offset, limit)
            result['items'] = [self._paper_card(conn, v) for v in result['items']]
            return result

    def paper(self, paper_id):
        with self.rt.database.session() as conn:
            item = self._paper(conn, paper_id)
            row = conn.execute('SELECT id,report_json FROM agent_reports WHERE paper_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1', (paper_id,)).fetchone()
            report = json.loads(row['report_json']) if row else {}
            summary = conn.execute("SELECT id FROM learning_results WHERE paper_id=? AND kind='summarize_paper' LIMIT 1", (paper_id,)).fetchone()
            result = dict(paper=self._paper_card(conn, item),
                          analysis=dict(report_id=row['id'] if row else None, completion=report.get('completion'),
                                        review_status=report.get('review', {}).get('status'), summary=report.get('summary', ''),
                                        limitations=report.get('limitations', [])),
                          summary_status='available' if summary else 'missing',
                          actions=['restore'] if item['archived_at'] else ['analyze', 'archive'])
            cards = self._cards(conn, paper_id)
        result['practice_counts'] = practice_counts(cards)
        result['weak_topics'] = [{'topic_id': n['skill_id'], 'name': n['label']} for n in self._knowledge()['nodes']
                                 if n['state'] == '需要关注' and any(s['paper_id'] == paper_id and s['mapping_status'] == 'current' for s in n['scopes'])]
        return result

    def _question_card(self, conn, q, paper):
        bid = None
        selected = None
        binding = conn.execute('''SELECT b.bank_id FROM paper_question_bindings b
            JOIN question_diagnoses d ON d.question_id=b.question_id AND d.report_id=b.report_id
            WHERE b.question_id=?''', (q['id'],)).fetchone()
        if binding:
            bid = binding[0]
        else:
            source = location(paper)
            if source['status'] == 'located' and source['math_type'] and str(q['number']).isdigit():
                selected = select_exam(conn, source['year'], source['math_type'], int(q['number']))
                bid = selected['matched_bank_id']
        value = {k: q[k] for k in ('id', 'paper_id', 'number', 'score_earned', 'correctness')}
        value.update(selected or dict(metadata(conn, bid), matched_bank_id=bid), review_state=q['review_status'],
                     analysis_available=bool(conn.execute('SELECT 1 FROM question_diagnoses WHERE question_id=?', (q['id'],)).fetchone()))
        return value

    def _questions(self, conn, paper):
        values = rows(conn, 'SELECT * FROM questions WHERE paper_id=?', (paper['id'],))
        return sorted(values, key=lambda q: (0, int(q['number']), q['id']) if str(q['number']).isdigit() else (1, str(q['number']), q['id']))

    def questions(self, paper_id):
        with self.rt.database.session() as conn:
            paper = self._paper(conn, paper_id)
            values = self._questions(conn, paper)
            return dict(items=[self._question_card(conn, q, paper) for q in values], total=len(values))

    def question(self, question_id):
        with self.rt.database.session() as conn:
            q = conn.execute('SELECT * FROM questions WHERE id=?', (question_id,)).fetchone()
            if not q:
                raise ServiceError('题目不存在', 404)
            paper = self._paper(conn, q['paper_id'])
            value = self._question_card(conn, q, paper)
            regions = json_load(q['regions_json'], [])
            value.update(stem=q['stem'] or '', regions=regions)
            row = conn.execute('SELECT diagnosis_json FROM question_diagnoses WHERE question_id=?', (question_id,)).fetchone()
            ids = [i['id'] for i in self._questions(conn, paper)]
            pos = ids.index(question_id)
            cards = [c for c in self._cards(conn, paper['id']) if c['question_id'] == question_id]
        return dict(question=value, diagnosis=present_diagnosis(json.loads(row[0])) if row else None,
                    topics=self._topics(question_id), evidence_urls=[f'/api/questions/{question_id}/evidence?region={i}' for i in range(len(regions))],
                    practice_counts=practice_counts(cards), previous_id=ids[pos-1] if pos else None,
                    next_id=ids[pos+1] if pos+1 < len(ids) else None, capabilities={'step_comparison': False})

    def summary(self, paper_id):
        with self.rt.database.session() as conn:
            self._paper(conn, paper_id)
            row = conn.execute("SELECT id,created_at,payload_json FROM learning_results WHERE paper_id=? AND kind='summarize_paper' ORDER BY created_at DESC,rowid DESC LIMIT 1", (paper_id,)).fetchone()
            return dict(status='available' if row else 'missing', result_id=row['id'] if row else None,
                        created_at=row['created_at'] if row else None, summary=json.loads(row['payload_json'])['result'] if row else None)

    def _cards(self, conn, paper_id=None,*,include_access=True):
        with self._cards_lock:
            key=self.rt.workspace.revision()
            if self._cards_value is None or key!=self._cards_key:self._cards_value={}
            if include_access not in self._cards_value:
                value=self._build_cards(conn,include_access=include_access)
                self._cards_value[include_access]=value
                self._cards_key=key if key==self.rt.workspace.revision() else None
            return deepcopy([c for c in self._cards_value[include_access] if paper_id is None or c['paper_id']==paper_id])

    def _build_cards(self, conn, paper_id=None,*,include_access=True):
        values = rows(conn, '''SELECT d.*,p.title paper_title,p.archived_at FROM diagnostic_probes d
            JOIN papers p ON p.id=d.paper_id WHERE (? IS NULL OR d.paper_id=?) ORDER BY d.created_at,d.id''', (paper_id, paper_id))
        states = {}; result = []
        nodes = {n['id']: n for n in index.catalog(conn)}
        redirects={r['old_id']:r['target_id'] for r in (catalog.document(conn) or {}).get('document',{}).get('redirects',[])}
        for item in values:
            if not self.rt.config.demo and item['paper_id'].startswith('paper-demo-'):
                continue
            pid = item['paper_id']
            if pid not in states:
                states[pid] = practice_state(conn, pid)
            state = states[pid]
            retired = conn.execute('SELECT 1 FROM retired_probes WHERE probe_id=?', (item['id'],)).fetchone()
            has_plan = bool(state['result_id'])
            current = not item['archived_at'] and not retired and (not has_plan or state['is_current'] and item['id'] in state['probe_ids'])
            if any(v['probe_id'] == item['id'] for v in state.get('deferred_probes', [])):
                current = False
            latest = conn.execute('SELECT * FROM probe_attempts WHERE probe_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1', (item['id'],)).fetchone()
            assessed = attempt(latest)['assessment'] if latest else None
            status = 'inactive' if not current else 'pending' if not latest else 'grading' if not assessed else 'needs_supplement' if assessed.get('correct') is None else 'graded'
            goals = [g for g in plan_goals(conn, state) if conn.execute('SELECT 1 FROM probe_goals WHERE probe_id=? AND goal_id=?', (item['id'], g['id'])).fetchone()]
            topic_ids = {tid for g in goals for tid in json.loads(g['payload_json']).get('topic_ids', [])}
            resolved = {tid if tid in nodes else redirects.get(tid,tid) for tid in topic_ids}
            result.append(dict(id=item['id'], paper_id=pid, paper_title=item['paper_title'], question_id=item['question_id'], bank_id=item['bank_id'],
                               created_at=item['created_at'], status=status, goal_ids=[g['id'] for g in goals],
                               topics=[{'topic_id': tid, 'name': nodes[tid]['name']} for tid in sorted(resolved) if tid in nodes],
                               access=access(conn, item['bank_id']) if include_access else None, latest_attempt_id=latest['id'] if latest else None))
        return result

    def practices(self, group_by='topic', status=None, paper_id=None, topic_id=None, include_inactive=False, offset=0, limit=20):
        if group_by not in ('topic', 'paper') or status is not None and status not in PRACTICE_STATUSES:
            raise ValueError('练习筛选不合法')
        with self.rt.database.session() as conn:
            if paper_id:
                self._paper(conn, paper_id)
            cards = [c for c in self._cards(conn, paper_id) if (include_inactive or c['status'] != 'inactive')
                     and (status is None or c['status'] == status) and (topic_id is None or any(t['topic_id'] == topic_id for t in c['topics']))]
        groups = {}
        for card in cards:
            keys = [(card['paper_id'], card['paper_title'])] if group_by == 'paper' else [(t['topic_id'], t['name']) for t in card['topics']] or [('unlinked', '尚未关联考点')]
            for key, label in keys:
                group = groups.setdefault(key, dict(id=key, label=label, items=[]))
                group['items'].append(card)
        for group in groups.values():
            group['counts'] = practice_counts(group['items'])
        return dict(page(sorted(groups.values(), key=lambda g: g['id']), offset, limit), counts=practice_counts(cards))

    def _probe(self, conn, practice_id):
        row = conn.execute('SELECT * FROM diagnostic_probes WHERE id=?', (practice_id,)).fetchone()
        if not row:
            raise ServiceError('练习不存在', 404)
        self._paper(conn, row['paper_id'])
        return row

    def practice(self, practice_id):
        with self.rt.database.session() as conn:
            row = self._probe(conn, practice_id)
            card = next(c for c in self._cards(conn, row['paper_id']) if c['id'] == practice_id)
            current = card['status'] != 'inactive'
            payload = probe_payload(conn, row) if current else {}
            latest = conn.execute('SELECT * FROM probe_attempts WHERE id=?', (card['latest_attempt_id'],)).fetchone()
            question = {k: payload[k] for k in ('question_text', 'question_image') if k in payload} if current and card['access']['can_view'] else None
            # Even image URLs/reference text are withheld until BOTH submission
            # and explicit analysis permission, including for a protected card.
            if question is not None and latest and card['access']['analysis_allowed']:
                question.update({k: payload[k] for k in ('analysis_text', 'analysis_image', 'expected', 'solution_note') if k in payload})
            actions = []
            if current:
                if not card['access']['can_view']:
                    if not card['access']['reserved']:actions.append('reveal_question')
                else:
                    actions.append('supplement' if latest else 'submit')
                    if latest and not card['access']['analysis_allowed']:actions.append('reveal_analysis')
            goals = [json.loads(g['payload_json']) for g in plan_goals(conn, practice_state(conn, row['paper_id'])) if g['id'] in card['goal_ids']]
            return dict(practice=card, is_current=current, review_reason=None if current else '旧练习或材料待核，历史作答保留',
                        question=question, goals=goals, selection_reason=json.loads(row['payload_json']).get('selection_reason') if question is not None else None,
                        latest_attempt=attempt(latest) if latest else None, actions=actions)

    def attempts(self, practice_id, offset=0, limit=20):
        with self.rt.database.session() as conn:
            self._probe(conn, practice_id)
            values = rows(conn, 'SELECT * FROM probe_attempts WHERE probe_id=? ORDER BY created_at DESC,id DESC', (practice_id,))
            result = page(values, offset, limit)
            result['items'] = [attempt(v) for v in result['items']]
            return result

    def topic(self, topic_id):
        snapshot = self._knowledge()
        with self.rt.database.session() as conn:
            canonical = catalog.resolve(conn, topic_id) or topic_id
            node = next((n for n in snapshot['nodes'] if n['skill_id'] == canonical), None)
            if node is None:raise ServiceError('考点不存在', 404)
            origin = node['origin']
            cards = [c for c in self._cards(conn,include_access=False) if any(t['topic_id'] == canonical for t in c['topics'])]
        counts = self._navigation()['counts'][canonical]
        return dict(topic=dict(id=canonical, parent_id=node['parent_id'], name=node['label'], kind=origin.get('node_kind', node['scope_level']),
                               definition=origin.get('definition', ''), conditions=origin.get('conditions', []), boundaries=origin.get('boundaries', [])),
                    performance={k: node[k] for k in ('state', 'state_reason', 'successes', 'failures', 'pending', 'attempt_count')},
                    question_counts={v: counts[v] for v in ('completed', 'bank')},
                      practice_counts=practice_counts(cards),collection_counts=self._navigation()['collection_counts'][canonical])

    def collections(self):
        bank=self._navigation()['bank'];ready={i['bank_id'] for i in bank if i['status']=='ready'}
        from app.bank.applicability import math_types
        with self.rt.database.session() as conn:
            groups=[]
            for row in conn.execute('SELECT * FROM bank_collections ORDER BY sort_order,id'):
                questions=list(conn.execute("SELECT b.id,b.math_types_json,i.math_type FROM bank_questions b LEFT JOIN bank_identity i ON i.bank_id=b.id WHERE collection_id=?",(row['id'],)))
                counts={}
                for q in questions:
                    for typ in math_types(q['math_types_json'],q['math_type']):
                        entry=counts.setdefault(typ,dict(math_type=typ,total=0,ready=0));entry['total']+=1;entry['ready']+=int(q['id'] in ready)
                groups.append(dict(id=row['id'],name=row['name'],kind=row['kind'],total=len(questions),ready=sum(q['id'] in ready for q in questions),math_types=[counts[k] for k in sorted(counts)]))
            return groups

    def bank(self, math_type='', year='', topic_id=None, offset=0, limit=20,collection=None):
        if math_type not in ('', '1', '2', '3'):
            raise ValueError('数学类别不合法')
        allowed = None
        if topic_id is not None:
            # The existing symmetric projection validates mappings and materials;
            # do not replace its checks with title/tag string matching.
            navigation=self._navigation()
            canonical=next((r['target_id'] for r in navigation['redirects'] if r['old_id']==topic_id),topic_id)
            selected=self.rt.knowledge_links._selected(navigation['nodes'],canonical,'subtree')
            allowed={item['bank_id'] for item in navigation['bank'] if any(t['topic_id'] in selected for t in item['topics'])}
        with self.rt.database.session() as conn:
            from app.bank.collections import require
            if collection is not None:require(conn,collection)
            ids = [r[0] for r in conn.execute("""SELECT b.id FROM bank_questions b LEFT JOIN bank_identity i ON i.bank_id=b.id
                WHERE (? IS NOT NULL OR b.source!='本地示例题库') AND (?='' OR EXISTS(SELECT 1 FROM json_each(b.math_types_json) WHERE CAST(value AS TEXT)=?) OR (b.math_types_json='[]' AND CAST(i.math_type AS TEXT)=?)) AND (?='' OR i.year=?)
                AND (? IS NULL OR b.collection_id=?) ORDER BY CAST(i.year AS INTEGER) DESC,i.math_type,i.number,b.id""", (collection,math_type, math_type,math_type, year, year,collection,collection))
                   if allowed is None or r[0] in allowed]
            if collection and conn.execute('SELECT kind FROM bank_collections WHERE id=?',(collection,)).fetchone()[0]=='book':
                from app.bank.applicability import book_key
                books={r[0]:json.loads(r[1] or '{}') for r in conn.execute("SELECT bank_id,json_extract(metadata_json,'$.book') FROM bank_resources")}
                ids.sort(key=lambda bid:book_key(books.get(bid,{}),bid))
            result = page(ids, offset, limit)
            result['items'] = [{**public_bank(conn, bid, view='library'), **metadata(conn, bid)} for bid in result['items']]
            from app.bank.access import text_resources
            result['items']=[text_resources(conn,item['id'],item,reference=item['analysis_allowed']) for item in result['items']]
            return result

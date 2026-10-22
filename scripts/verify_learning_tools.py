"""Real Codex MCP evaluation against synthetic, isolated learning data."""
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import server
from codex_bridge import CodexBridge
from learning_loop import apply_report, submit_probe
from bank_access import init_access,reveal,register_identity,save_preferences
from answer_images import save_answer_image


def wait(bridge,predicate):
    deadline=time.monotonic()+240
    while time.monotonic()<deadline:
        state=bridge.snapshot()
        if predicate(state):return state
        if state['status'] in ('failed','waiting_user','disconnected') and state.get('error'):raise RuntimeError(state['error'])
        time.sleep(.4)
    raise TimeoutError('Codex learning tool acceptance timed out')


def main():
    data=ROOT/'tmp'/('learning-live-'+uuid.uuid4().hex[:8]);data.mkdir(parents=True)
    server.DATA=data;server.PAPERS_DIR=data/'papers';server.DB_PATH=data/'mathlens.db';server.init_db()
    import pymupdf
    from PIL import Image,ImageDraw,ImageFont
    pdf=data/'papers'/'fixture.pdf'
    with pymupdf.open() as doc:
        page=doc.new_page();page.insert_text((40,60),'1. Compute 6 + 7. Student: 15.');doc.save(pdf)
    image=Image.new('RGB',(650,160),'white');ImageDraw.Draw(image).text((30,40),'6 + 7 = 15',fill='black',font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',48))
    bank=data/'bank-assets'/'fixture';bank.mkdir(parents=True)
    image.save(bank/'question.png');image.save(bank/'analysis.png')
    conn=server.connect()
    conn.execute("INSERT INTO papers(id,title,source_path,source_sha256,created_at) VALUES('paper-test','isolated test',?,?,'now')",(str(pdf),hashlib.sha256(pdf.read_bytes()).hexdigest()))
    conn.execute("INSERT INTO bank_questions(id,source,stem,created_at) VALUES('math2-2000-01','fixture','Compute 6+7','now')")
    conn.execute('INSERT INTO bank_resources VALUES(?,?,?,?,NULL)',('math2-2000-01','{}',str((bank/'question.png').relative_to(data)),str((bank/'analysis.png').relative_to(data))))
    init_access(conn);save_preferences(conn,{'study_type':2,'reserved':[]});register_identity(conn,'math2-2000-01',2,'2000',1,bank/'question.png');reveal(conn,'math2-2000-01','question',True)
    report={'author':'fixture','method':'synthetic','source_sha256':hashlib.sha256(pdf.read_bytes()).hexdigest(),'expected_count':1,
        'questions':[{'number':1,'stem':'6+7','regions':[{'page':1,'bbox':[20,30,500,110]}],'observation':'wrong result','skill_events':[]}],
        'probes':[{'id':'p','question_number':1,'bank_id':'math2-2000-01','skill_id':'addition','skill_label':'addition','prompt':'compute 6+7','expected':'13','discriminates':'arithmetic result','priority':1}]}
    raw=BytesIO();image.save(raw,format='PNG');asset=save_answer_image(conn,data,raw.getvalue())
    conn.commit()
    bridge=CodexBridge(ROOT,data)
    try:
        bridge.connect();wait(bridge,lambda s:s['can_submit'])
        bridge.submit('隔离验收，不是真实学生，不用 Shell。用 mathlens 分别读取 paper-diagnosis、bank-search、probe-design 三个 skill；读取 paper-test 的原卷第1页，catalog 找数学二候选并 read_bank 阅读；为该一题卷用 apply_report 写回完整诊断（expected_count=1）及一个分环节检验（probe id=p，bank_id=math2-2000-01，skill_id=addition，skill_label=addition，priority=1）。不虚构学生原因。最终只汇报已保存和任务ID，不提前公布参考答案。',str(uuid.uuid4()),{'paper_id':'paper-test'})
        wait(bridge,lambda s:s['can_submit'])
        assert conn.execute('SELECT count(*) FROM agent_reports').fetchone()[0]==1,'Real diagnosis was not written'
        assert conn.execute("SELECT id FROM diagnostic_probes WHERE id='paper-test-p'").fetchone(),'Real probe was not created'
        sid=bridge.state['session_id'];bridge.close();bridge=CodexBridge(ROOT,data);bridge.connect();wait(bridge,lambda s:s['can_submit']);assert bridge.state['session_id']==sid
        attempt=submit_probe(conn,'paper-test-p',{'response':'','image_ids':[asset['id']]});conn.commit()
        bridge.submit(f"隔离学习闭环验收，不是真实学生。不调用 Shell。用 mathlens 工具依次读取 learning-update skill、catalog 数学二题库、read_bank 题图、read_attempt {attempt['attempt_id']} 的真实已保存照片；根据图片判断并用 assess 写回，反馈给出正确结果。然后用 memory_write 将此次证据指针写入 index.md，不能修改应用代码。",str(uuid.uuid4()),{'paper_id':'paper-test'},[asset['id']])
        state=wait(bridge,lambda s:s['can_submit'])
        row=conn.execute('SELECT assessment_json FROM probe_attempts WHERE id=?',(attempt['attempt_id'],)).fetchone()
        assert row[0] and json.loads(row[0])['correct'] is False,'Assessment was not written from real tool call'
        actions=[r[0] for r in conn.execute('SELECT action FROM tool_audit')]
        assert all(action in actions for action in ('read_skill','read_paper','catalog','read_bank','apply_report','read_attempt','assess','memory_write')),actions
        assert conn.execute("SELECT count(*) FROM learning_events WHERE kind='probe_failure'").fetchone()[0]==1
        result={'real_learning_tool_loop':True,'real_diagnosis_and_probe':True,'same_session_restart':True,'actions':actions,'single_evidence_event':True,'data':str(data)}
        (data/'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(result,ensure_ascii=False),flush=True)
    finally:bridge.close();conn.close()


if __name__=='__main__':main()

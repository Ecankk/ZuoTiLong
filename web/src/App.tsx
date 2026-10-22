import { useEffect, useState, type ReactNode } from 'react'
import { analyzePaper, confirmPaper, getBootstrap, paperFileUrl, postJson, saveDiagnosis, uploadPaper } from './api'
import type { BankQuestion, Bootstrap, Paper, Profile, Question, View } from './types'
import { LearningWorkspace, EvidenceProfile } from './LearningWorkspace'
import { AgentPanel, useAgentState } from './AgentPanel'

const stages = ['题目切入', '建模与路径', '中间计算', '最终处理', '时间与审题']
const errors = ['概念不清', '方法不会', '变式不会', '计算失误', '审题表达']

function dateLabel(value?: string) { return value ? `${value.slice(5).replace('-', '月')}日` : '待定' }
function esc(value?: string) { return value || '' }

export default function App() {
  const agent = useAgentState()
  const [data, setData] = useState<Bootstrap | null>(null)
  const [view, setView] = useState<View>('home')
  const [online, setOnline] = useState(true)
  const [selected, setSelected] = useState<Question | null>(null)
  const [confirming, setConfirming] = useState<Paper | null>(null)
  const [message, setMessage] = useState('')
  const [focusedQuestion, setFocusedQuestion] = useState<Question | undefined>()

  const reload = async () => {
    try { setData(await getBootstrap()); setOnline(true) }
    catch { setOnline(false); setMessage('本地服务未连接，请确认 MathLens Server 窗口仍在运行。') }
  }
  useEffect(() => { reload(); const timer = setInterval(reload, 5000); return () => clearInterval(timer) }, [])

  if (!data) return <div className="loading"><div className="spinner" />正在加载本地项目…</div>

  const queue = data.questions.filter(q => ['待诊断', '待检验', '高风险正确', '不稳定'].includes(q.review_status))
  const latest = [...data.papers].sort((a, b) => (b.exam_date || '').localeCompare(a.exam_date || ''))[0]
  const switchView = (next: View) => { setView(next); setMessage('') }
  const openQuestion = (q: Question) => { if(data.loop?.diagnoses[q.id]){setFocusedQuestion(q);setView('home')}else{setSelected(q)} }

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark">M</span><div><strong>MathLens</strong><small>数学一 · 试卷诊断</small></div></div>
      <div className="workspace"><i className={online ? 'online' : ''} /><div><strong>我的数学项目</strong><small>{online ? 'SQLite 本地数据' : '服务未连接'}</small></div></div>
      <nav>{([['home', '⌂', '今日工作'], ['papers', '▤', '试卷'], ['queue', '◌', '题目队列'], ['bank', '⌘', '本地题库'], ['profile', '◒', '个人画像']] as [View, string, string][]).map(([id, icon, label]) => <button key={id} className={view === id ? 'nav active' : 'nav'} onClick={() => switchView(id)}><span>{icon}</span>{label}{id === 'queue' && <em>{queue.length}</em>}</button>)}</nav>
      <div className="side-foot">v0.4 · 单会话学习工作台</div>
    </aside>
    <main className="main">
      <header className="topbar"><div><div className="eyebrow">{viewLabel(view)}</div><h1>{view === 'home' ? '今天只处理最值得回收的分' : viewLabel(view)}</h1></div><div className="top-actions"><span className={online ? 'connection ok' : 'connection'}><i />{online ? '本地服务已连接' : '等待本地服务'}</span><button className="primary" onClick={() => switchView('papers')}>＋ 导入试卷</button></div></header>
      {message && <div className="notice">{message}</div>}
      <AgentPanel agent={agent} papers={data.papers} questions={data.questions} onReload={reload}/>
      <fieldset className="learning-inputs" disabled={!!agent.state?.input_locked || !agent.reachable}>
      {view === 'home' && (data.loop?.reports.length ? <LearningWorkspace loop={data.loop} questions={data.questions} papers={data.papers} onReload={reload} focusedQuestion={focusedQuestion}/> : <Home data={data} queue={queue} latest={latest} onSelect={openQuestion} onView={switchView} />)}
      {view === 'papers' && <Papers data={data} onReload={reload} onConfirm={setConfirming} />}
      {view === 'queue' && <Queue questions={data.questions} onSelect={openQuestion} />}
      {view === 'bank' && <Bank bank={data.bank} />}
      {view === 'profile' && (data.loop?.skills.length ? <EvidenceProfile skills={data.loop.skills}/> : <ProfileView profile={data.profile} />)}
      </fieldset>
    </main>
    {selected && <QuestionDrawer question={selected} bank={data.bank} onClose={() => setSelected(null)} onReload={reload} />}
    {confirming && <ConfirmDrawer paper={confirming} onClose={() => setConfirming(null)} onDone={() => { setConfirming(null); reload(); switchView('queue') }} />}
  </div>
}

function viewLabel(view: View) { return ({ home: '今日工作 / 待处理', papers: '试卷 / 已完成材料', queue: '题目队列 / 逐题处理', bank: '本地题库 / 检索验证', profile: '个人画像 / 证据状态' })[view] }

function Home({ data, queue, latest, onSelect, onView }: { data: Bootstrap; queue: Question[]; latest?: Paper; onSelect: (q: Question) => void; onView: (v: View) => void }) {
  const recoverable = data.questions.reduce((sum, q) => sum + Math.max(0, q.max_score - q.score_earned), 0)
  return <>
    <section className="hero"><div><div className="eyebrow">最小用户循环</div><h2>从一张已完成的试卷，找到下一步该练什么</h2><p>先处理重复失分，再用本地题库做针对性验证。系统只保留与提分有关的证据。</p></div><div className="hero-number"><span>当前队列</span><strong>{queue.length}</strong><small>道题待处理</small></div></section>
    <div className="stats"><Stat label="当前分数" value={`${latest?.score || 0} / ${latest?.total_score || 150}`} hint="最近一张试卷" /><Stat label="待处理题" value={queue.length} hint="错题 + 高风险正确" /><Stat label="重复错误" value={data.profile.repeated_errors.reduce((s, x) => s + x.count, 0)} hint="来自已有证据" /><Stat label="可回收分" value={`${recoverable.toFixed(1)} 分`} hint="按已录入题目" /></div>
    <div className="columns"><section className="panel"><PanelHead eyebrow="题目队列" title="优先处理" action={<button className="text-button" onClick={() => onView('queue')}>查看全部 →</button>} />{queue.slice(0, 4).map(q => <button className="question-row" key={q.id} onClick={() => onSelect(q)}><b>{q.number}</b><span><strong>{q.subject} · {q.stem}</strong><small>{q.knowledge || '待提取指纹'} · {q.score_earned == null ? '分值待核定' : `${q.score_earned}/${q.max_score} 分`}</small></span><em>{q.correctness === 'correct' ? '高风险' : '需处理'}</em></button>)}</section><section className="panel"><PanelHead eyebrow="最近证据" title="最近一张试卷" action={<button className="text-button" onClick={() => onView('papers')}>试卷记录 →</button>} />{latest && <div className="latest"><strong>{latest.score || 0}</strong><span>/ {latest.total_score || 150}</span><h3>{latest.title}</h3><small>{dateLabel(latest.exam_date)} · {latest.duration || '—'} 分钟 · {latest.import_status === 'analyzed' ? '已分析' : '待确认'}</small><div className="bar"><i style={{ width: `${Math.round((latest.score || 0) / (latest.total_score || 150) * 100)}%` }} /></div></div>}</section></div>
  </>
}

function Stat({ label, value, hint }: { label: string; value: string | number; hint: string }) { return <div className="stat"><small>{label}</small><strong>{value}</strong><span>{hint}</span></div> }
function PanelHead({ eyebrow, title, action }: { eyebrow: string; title: string; action?: ReactNode }) { return <div className="panel-head"><div><div className="eyebrow">{eyebrow}</div><h2>{title}</h2></div>{action}</div> }

function Papers({ data, onReload, onConfirm }: { data: Bootstrap; onReload: () => void; onConfirm: (p: Paper) => void }) {
  const [file, setFile] = useState<File | null>(null); const [title, setTitle] = useState(''); const [date, setDate] = useState(new Date().toISOString().slice(0, 10)); const [feedback, setFeedback] = useState(''); const [analyzing, setAnalyzing] = useState('')
  const runAnalysis = async (paper: Paper) => { setAnalyzing(paper.id); setFeedback('正在提取 PDF 文字、题号和页码…'); try { const result = await analyzePaper(paper.id); const warning = result.warnings?.length ? `；${result.warnings[0]}` : ''; setFeedback(`已切分 ${result.created_questions} 道题（${result.engine}）${warning}；等待工作目录中的 Agent 分析作答。`); await onReload() } catch { setFeedback('解析失败。请安装 requirements-ocr.txt 后重试，或使用人工确认入口。') } finally { setAnalyzing('') } }
  const submit = async () => { if (!file) { setFeedback('请先选择 PDF 文件'); return } try { const imported = await uploadPaper(file, title || file.name.replace(/\.pdf$/i, ''), date); await runAnalysis(imported.paper); } catch { setFeedback('上传失败，请确认本地服务仍在运行。') } }
  return <><div className="intro"><div className="eyebrow">试卷</div><h2>已完成试卷是全部诊断的入口</h2><p>上传后自动提取文字、题号、页码和题库候选；扫描页由本地 OCR 定位；切分后交给 Agent 阅读作答并诊断。</p></div><section className="panel import"><label className="drop"><span>↑</span><strong>{file ? file.name : '拖入已完成的试卷 PDF'}</strong><small>文件只保存在本机 .mathlens/papers</small><input type="file" accept="application/pdf" onChange={e => { const next = e.target.files?.[0] || null; setFile(next); if (next && !title) setTitle(next.name.replace(/\.pdf$/i, '')) }} /></label><div className="form-row"><label>试卷名称<input value={title} onChange={e => setTitle(e.target.value)} /></label><label>考试日期<input type="date" value={date} onChange={e => setDate(e.target.value)} /></label><button className="primary" onClick={submit}>上传并自动切题</button></div>{feedback && <div className="feedback">{feedback}</div>}</section><section className="panel"><PanelHead eyebrow="全部记录" title={`${data.papers.length} 张试卷`} action={<span className="muted">先自动解析，再人工核对低置信度题目</span>} /><table><thead><tr><th>试卷</th><th>日期</th><th>得分</th><th>状态</th><th>来源</th><th>操作</th></tr></thead><tbody>{data.papers.map(p => <tr key={p.id}><td><strong>{p.title}</strong>{p.page_count ? <small className="table-sub">{p.page_count} 页 · {p.analysis_engine}</small> : null}</td><td>{dateLabel(p.exam_date)}</td><td>{p.score || '—'} / {p.total_score || 150}</td><td><span className={`status ${p.import_status === 'analyzed' ? 'done' : 'pending'}`}>{p.import_status === 'diagnosed' ? '诊断待检验' : p.import_status === 'segmented' ? '切分完成待Agent' : p.import_status === 'analyzed' ? '旧版已分析' : '待解析'}</span></td><td>{p.source_name || '手动录入'}</td><td><a className="small-action" href={paperFileUrl(p.id)} target="_blank" rel="noreferrer">查看 PDF</a>{p.source_name && <button className="small-action" disabled={analyzing === p.id} onClick={() => runAnalysis(p)}>{analyzing === p.id ? '解析中…' : p.import_status === 'analyzed' ? '重新解析' : '开始 OCR'}</button>}{!p.page_count && <button className="small-action" onClick={() => onConfirm(p)}>人工确认</button>}</td></tr>)}</tbody></table></section></>
}

function Queue({ questions, onSelect }: { questions: Question[]; onSelect: (q: Question) => void }) { const [filter, setFilter] = useState('all'); const list = questions.filter(q => filter === 'all' || q.review_status === filter); return <><div className="intro"><div className="eyebrow">题目队列</div><h2>只处理有证据的问题</h2><p>错题优先，答对但慢、低置信度或重复出现的题目会进入高风险队列。</p></div><div className="filters">{['all', '待诊断', '高风险正确', '不稳定'].map(x => <button key={x} className={filter === x ? 'filter active' : 'filter'} onClick={() => setFilter(x)}>{x === 'all' ? '全部' : x}</button>)}</div><div className="cards">{list.map(q => <button className="card" key={q.id} onClick={() => onSelect(q)}><span className="eyebrow">{q.subject} · 第 {q.number} 题</span><span className="status pending">{q.review_status}</span><h3>{q.stem}</h3><p>{q.notes || '还没有诊断记录。点击进入题目工作台。'}</p><div className="chips"><span>{q.knowledge || '待提取指纹'}</span>{q.error_stage && <span>{q.error_stage}</span>}<span>{q.score_earned == null ? '分值待核定' : `${q.score_earned}/${q.max_score} 分`}</span></div></button>)}</div></> }

function Bank({ bank }: { bank: BankQuestion[] }) { const [query, setQuery] = useState(''); const [stage, setStage] = useState(''); const list = bank.filter(q => (!query || `${q.stem} ${q.tags.join(' ')}`.toLowerCase().includes(query.toLowerCase())) && (!stage || q.fingerprint?.stages?.includes(stage))); return <><div className="intro"><div className="eyebrow">本地题库</div><h2>用已有题目做验证</h2><p>优先检索同结构、同环节和条件对比题。</p></div><section className="panel search"><input placeholder="搜索换元、正定性、边缘分布…" value={query} onChange={e => setQuery(e.target.value)} /><select value={stage} onChange={e => setStage(e.target.value)}><option value="">全部环节</option>{['切入', '建模', '计算', '最终处理'].map(x => <option key={x}>{x}</option>)}</select></section><div className="cards">{list.map(q => <article className="card" key={q.id}><span className="eyebrow">{q.source}</span><h3>{q.stem}</h3><p>{q.tags.join(' · ')}</p><div className="chips"><span>难度 {q.difficulty}/5</span></div></article>)}</div></> }

function ProfileView({ profile }: { profile: Profile }) { return <><div className="intro"><div className="eyebrow">个人画像</div><h2>画像只保存被题目验证过的结论</h2><p>状态来自试卷、针对性小测和复测结果。</p></div><div className="columns"><section className="panel"><PanelHead eyebrow="解题环节" title="当前状态" />{Object.entries(profile.stages).map(([name, info]) => <div className="profile-row" key={name}><span><strong>{name}</strong><small>证据 {info.evidence} · 失败 {info.failures} · 成功 {info.successes}</small></span><em>{info.state}</em></div>)}</section><section className="panel"><PanelHead eyebrow="重复失分" title="最需要处理的主因" />{profile.repeated_errors.map(x => <div className="profile-row" key={x.label}><span><strong>{x.label}</strong><small>重复出现 {x.count} 次</small></span><em className="danger">优先处理</em></div>)}</section></div></> }

function QuestionDrawer({ question, bank, onClose, onReload }: { question: Question; bank: BankQuestion[]; onClose: () => void; onReload: () => void }) { const [stage, setStage] = useState(question.error_stage || ''); const [error, setError] = useState(question.error_type || ''); const [notes, setNotes] = useState(question.notes || ''); const candidates = bank.filter(b => (question.knowledge || '').split('｜').some(k => `${b.stem} ${b.tags.join(' ')}`.includes(k))).slice(0, 4); const matched = bank.find(b => b.id === question.match_bank_id); const diagnose = async () => { await saveDiagnosis(question.id, { review_status: '训练中', error_stage: stage, error_type: error, notes }); await onReload() }; return <div className="overlay"><aside className="drawer"><button className="close" onClick={onClose}>×</button><div className="eyebrow">单题诊断</div><h2>第 {question.number} 题 · {question.subject}</h2><div className="question-box"><strong>{question.stem}</strong><small>得分 {question.score_earned}/{question.max_score} · {question.notes}</small>{question.page_start && <a href={paperFileUrl(question.paper_id, question.page_start)} target="_blank" rel="noreferrer">查看原 PDF 第 {question.page_start} 页 ↗</a>}{matched && <small>题库基准：{matched.stem}</small>}{question.match_bank_id && <small>题库候选匹配度 {Math.round((question.match_score || 0) * 100)}%</small>}</div><h3>错误环节</h3><div className="options">{stages.map(x => <button className={stage === x ? 'option selected' : 'option'} key={x} onClick={() => setStage(x)}>{x}</button>)}</div><h3>错误主因</h3><div className="options">{errors.map(x => <button className={error === x ? 'option selected' : 'option'} key={x} onClick={() => setError(x)}>{x}</button>)}</div><h3>诊断备注</h3><textarea value={notes} onChange={e => setNotes(e.target.value)} /><button className="primary full" onClick={diagnose}>保存诊断</button><h3>推荐验证题</h3>{candidates.map(c => <div className="candidate" key={c.id}><span>{c.stem}<small>{c.tags.join(' · ')}</small></span><button className="small-action" onClick={async () => { window.alert('请到今日工作的针对性检验中提交实际作答。') }}>进入今日工作检验</button></div>)}</aside></div> }

function ConfirmDrawer({ paper, onClose, onDone }: { paper: Paper; onClose: () => void; onDone: () => void }) { const [numbers, setNumbers] = useState(''); const [scores, setScores] = useState('5'); const [error, setError] = useState(''); const submit = async () => { const list = numbers.split(',').map(x => x.trim()).filter(Boolean); if (!list.length) { setError('请填写题号'); return } try { await confirmPaper(paper.id, list, scores.split(',').map(x => x.trim()).filter(Boolean), '数学一'); onDone() } catch { setError('确认失败，请检查本地服务') } }; return <div className="overlay"><aside className="drawer"><button className="close" onClick={onClose}>×</button><div className="eyebrow">OCR 兜底</div><h2>{paper.title}</h2><p>数字 PDF 应先使用“开始 OCR”。只有扫描件没有文字层、题号识别失败或需要人工修正时，才使用此入口。</p><label>题号<input value={numbers} onChange={e => setNumbers(e.target.value)} placeholder="1,2,3,4,5" /></label><label>每题分值<input value={scores} onChange={e => setScores(e.target.value)} placeholder="5 或 5,5,10" /></label>{error && <div className="notice">{error}</div>}<button className="primary full" onClick={submit}>生成题目队列</button></aside></div> }

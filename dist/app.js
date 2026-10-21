const state = {
  papers: [
    { date: '2026-10-21', name: '真题 2022', score: 101, time: 136, errors: ['变式不会','计算失误'], status: '训练中' },
    { date: '2026-10-17', name: '真题 2021', score: 96, time: 142, errors: ['方法不会','计算失误','审题表达'], status: '已复盘' },
    { date: '2026-10-13', name: '模拟卷 03', score: 104, time: 131, errors: ['概念不清','变式不会'], status: '已复盘' },
    { date: '2026-10-09', name: '真题 2020', score: 92, time: 148, errors: ['方法不会','变式不会','计算失误'], status: '已复盘' },
    { date: '2026-10-05', name: '模拟卷 02', score: 98, time: 139, errors: ['计算失误','审题表达'], status: '已复盘' },
    { date: '2026-09-29', name: '模拟卷 01', score: 92, time: 151, errors: ['概念不清','方法不会'], status: '待复盘' }
  ]
};

const byId = id => document.getElementById(id);
const escapeHtml = (s) => String(s).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const fmtDate = date => { const d = new Date(`${date}T00:00:00`); return `${d.getMonth()+1}月${d.getDate()}日`; };
const sortedPapers = () => [...state.papers].sort((a,b)=>b.date.localeCompare(a.date));

function renderMetrics(){
  const latest = sortedPapers()[0];
  const scores = state.papers.map(p=>p.score);
  const avg = scores.reduce((a,b)=>a+b,0)/scores.length;
  const stability = Math.max(0, 10 - Math.round(Math.sqrt(scores.reduce((s,x)=>s+(x-avg)**2,0)/scores.length)*10)/10);
  const metrics = [
    ['最近总分', `${latest.score}<small>/ 150</small>`, '↑ 9 分', '较首卷', 'teal', '↗'],
    ['目标差距', `${120-latest.score}<small> 分</small>`, '可回收', '优先级明确', 'orange', '◎'],
    ['稳定度', `${stability.toFixed(1)}<small> / 10</small>`, '↑ 0.8', '较前 3 卷', 'blue', '◒'],
    ['可回收分', '16.5<small> 分</small>', '集中在', '变式 + 计算', 'red', '✦']
  ];
  byId('metric-grid').innerHTML = metrics.map(m=>`<div class="metric-card ${m[4]}"><div class="metric-top"><span>${m[0]}</span><span class="metric-icon">${m[5]}</span></div><div class="metric-value">${m[1]}</div><div class="metric-delta"><span class="${m[4]==='red'?'delta-warn':'delta-up'}">${m[2]}</span> ${m[3]}</div></div>`).join('');
  byId('score-total').innerHTML = `${latest.score}`;
  byId('paper-count-title').textContent = `${state.papers.length} 份试卷`;
  byId('reviewed-count').textContent = state.papers.filter(p=>p.status==='已复盘').length;
  byId('avg-time').textContent = Math.round(state.papers.reduce((s,p)=>s+p.time,0)/state.papers.length);
  byId('variance').textContent = stability.toFixed(1);
}

function renderTrend(){
  const papers = [...state.papers].sort((a,b)=>a.date.localeCompare(b.date));
  const values = papers.map(p=>p.score); const w=650,h=215,pad={l:38,r:18,t:16,b:30};
  const min=80,max=125; const x=i=>pad.l+i*(w-pad.l-pad.r)/Math.max(1,values.length-1); const y=v=>pad.t+(max-v)*(h-pad.t-pad.b)/(max-min);
  const line = values.map((v,i)=>`${x(i)},${y(v)}`).join(' '); const area = `${x(0)},${h-pad.b} ${line} ${x(values.length-1)},${h-pad.b}`;
  const grid=[90,100,110,120].map(v=>`<line x1="${pad.l}" x2="${w-pad.r}" y1="${y(v)}" y2="${y(v)}" stroke="#e9efed" stroke-width="1"/><text x="4" y="${y(v)+4}" font-size="10" fill="#9aaba6">${v}</text>`).join('');
  const labels=papers.map((p,i)=>`<text x="${x(i)}" y="${h-8}" text-anchor="middle" font-size="10" fill="#9aaba6">${fmtDate(p.date)}</text>`).join('');
  const points=values.map((v,i)=>`<circle cx="${x(i)}" cy="${y(v)}" r="4.2" fill="#fff" stroke="#0e8b78" stroke-width="3"/><text x="${x(i)}" y="${y(v)-12}" text-anchor="middle" font-size="10" font-weight="700" fill="#0b6658">${v}</text>`).join('');
  byId('trend-chart').innerHTML=`<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><defs><linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#b9e8dc" stop-opacity=".65"/><stop offset="1" stop-color="#b9e8dc" stop-opacity="0"/></linearGradient></defs>${grid}<line x1="${pad.l}" x2="${w-pad.r}" y1="${y(120)}" y2="${y(120)}" stroke="#bfd4ce" stroke-dasharray="5 5"/><polygon points="${area}" fill="url(#area)"/><polyline points="${line}" fill="none" stroke="#0e8b78" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>${points}${labels}</svg>`;
}

function renderModules(){
  const latest=sortedPapers()[0]; const total=latest.score; const modules=[['高数',Math.round(total*.43), 'linear-gradient(90deg,#15977f,#61c6af)'],['线代',Math.round(total*.34),'linear-gradient(90deg,#699bd0,#9bc2e7)'],['概率',total-Math.round(total*.43)-Math.round(total*.34),'linear-gradient(90deg,#e39b59,#f0c58c)']];
  byId('module-bars').innerHTML=modules.map(m=>`<div class="module-row"><span class="module-name">${m[0]}</span><div class="module-track"><div class="module-fill" style="width:${m[1]/60*100}%;background:${m[2]}"></div></div><span class="module-score">${m[1]}</span></div>`).join('');
}

function renderErrors(){
  const counts={'概念不清':0,'方法不会':0,'变式不会':0,'计算失误':0,'审题表达':0}; state.papers.slice(0,4).forEach(p=>p.errors.forEach(e=>counts[e]++));
  const order=Object.entries(counts).sort((a,b)=>b[1]-a[1]); const colors=['#d76b62','#e09a55','#78a7d0','#4ca991','#a3b5b0'];
  byId('error-bars').innerHTML=order.map(([k,v],i)=>`<div class="error-row"><span class="error-label">${k}</span><div class="error-track"><div class="error-fill" style="width:${Math.max(12,v/4*100)}%;background:${colors[i]}"></div></div><strong>${v}</strong></div>`).join('');
}

function renderPriority(){
  const items=[['线代｜二次型与特征值变式','近 3 卷出现 3 次 · 预计回收 5 分','+5'],['高数｜积分与级数计算','近 3 卷出现 4 次 · 预计回收 4 分','+4'],['概率｜分布函数与数字特征','基础题得分不稳定 · 预计回收 3.5 分','+3.5']];
  byId('priority-list').innerHTML=items.map((x,i)=>`<div class="priority-item"><span class="priority-num">${i+1}</span><div><div class="priority-title">${x[0]}</div><div class="priority-meta">${x[1]}</div></div><span class="priority-score">${x[2]}</span></div>`).join('');
}

function rowHtml(p){return `<tr><td>${fmtDate(p.date)}</td><td><strong>${escapeHtml(p.name)}</strong></td><td class="score-cell">${p.score}</td><td>${p.time} 分钟</td><td><div class="issue-tags">${p.errors.map(e=>`<span class="issue-tag">${e}</span>`).join('')}</div></td><td><span class="status ${p.status==='已复盘'?'done':p.status==='训练中'?'training':'pending'}">${p.status}</span></td></tr>`}
function renderTables(){const rows=sortedPapers();byId('recent-table').innerHTML=rows.slice(0,4).map(rowHtml).join('');byId('all-table').innerHTML=rows.map(rowHtml).join('');}

function renderRadar(){
  const w=360,h=315,cx=180,cy=152,r=100; const labels=['概念','方法','变式','计算','审题']; const current=[78,64,52,68,76], target=[86,84,78,85,84];
  const pts=(vals,rad=r)=>vals.map((v,i)=>{const a=-Math.PI/2+i*2*Math.PI/5;return `${cx+Math.cos(a)*rad*v/100},${cy+Math.sin(a)*rad*v/100}`}).join(' ');
  const rings=[.25,.5,.75,1].map(scale=>`<polygon points="${[0,1,2,3,4].map(i=>{const a=-Math.PI/2+i*2*Math.PI/5;return `${cx+Math.cos(a)*r*scale},${cy+Math.sin(a)*r*scale}`}).join(' ')}" fill="none" stroke="#e3ece8" stroke-width="1"/>`).join('');
  const axes=[0,1,2,3,4].map(i=>{const a=-Math.PI/2+i*2*Math.PI/5;return `<line x1="${cx}" y1="${cy}" x2="${cx+Math.cos(a)*r}" y2="${cy+Math.sin(a)*r}" stroke="#e3ece8"/>`}).join('');
  const text=labels.map((l,i)=>{const a=-Math.PI/2+i*2*Math.PI/5;return `<text x="${cx+Math.cos(a)*(r+23)}" y="${cy+Math.sin(a)*(r+23)+4}" text-anchor="middle" font-size="11" fill="#667872">${l}</text>`}).join('');
  byId('radar-chart').innerHTML=`<svg viewBox="0 0 ${w} ${h}">${rings}${axes}<polygon points="${pts(target)}" fill="#eef2f0" stroke="#c9d8d3" stroke-width="2" stroke-dasharray="4 4"/><polygon points="${pts(current)}" fill="#bfe9de" fill-opacity=".75" stroke="#0e8b78" stroke-width="2.5"/>${text}</svg>`;
}
function renderGaps(){const gaps=[['二次型与特征值','变式不会 · 3 次','5.0'],['积分与级数计算','计算失误 · 4 次','4.0'],['分布函数与数字特征','方法不会 · 2 次','3.5'],['中值定理应用','审题表达 · 1 次','2.0']];byId('gap-list').innerHTML=gaps.map((g,i)=>`<div class="gap-item"><span class="gap-rank">${i+1}</span><div><div class="gap-name">${g[0]}</div><div class="gap-meta">${g[1]}</div></div><span class="gap-points">+${g[2]} 分</span></div>`).join('')}
function renderPractice(){const ps=[['二次型变式训练','解决“会定义、不会迁移”的问题','3 同构 + 1 变式','+5 分'],['积分计算纠错包','消灭符号、漏项与换元失误','4 道限时题','+4 分'],['概率数字特征','补齐基础定义与方法路径','基础 6 题','+3.5 分']];byId('practice-grid').innerHTML=ps.map((p,i)=>`<div class="practice-card"><div class="practice-icon">${['λ','∫','P'][i]}</div><h3>${p[0]}</h3><p>${p[1]}</p><div class="practice-meta"><span>${p[2]}</span><strong>${p[3]}</strong></div><div style="margin-top:15px"><button class="mini-btn">开始训练 →</button></div></div>`).join('')}
function renderWeek(){const days=[['一','19'],['二','20'],['三','21'],['四','22'],['五','23'],['六','24'],['日','25']];byId('week-grid').innerHTML=days.map((d,i)=>`<div class="week-day ${i===2?'active':''} ${i<2?'done':''}">${d[0]}<strong>${d[1]}</strong></div>`).join('')}

function renderAll(){renderMetrics();renderTrend();renderModules();renderErrors();renderPriority();renderTables();renderRadar();renderGaps();renderPractice();renderWeek();}

function openModal(){byId('modal-backdrop').classList.add('open');byId('modal-backdrop').setAttribute('aria-hidden','false');const date=byId('paper-form').elements.date; if(!date.value) date.value=new Date().toISOString().slice(0,10);}
function closeModal(){byId('modal-backdrop').classList.remove('open');byId('modal-backdrop').setAttribute('aria-hidden','true');}
function switchView(name){document.querySelectorAll('.nav-item').forEach(n=>n.classList.toggle('active',n.dataset.view===name));document.querySelectorAll('.view').forEach(v=>v.classList.toggle('active',v.id===`view-${name}`));const titles={overview:['总览','总览 / 最近状态'],papers:['试卷记录','试卷记录 / 增量档案'],diagnosis:['知识诊断','知识诊断 / 错因与缺口'],practice:['错题训练','错题训练 / 相似题与变式'],plan:['学习计划','学习计划 / 今日动作']};byId('page-title').textContent=titles[name][0]==='总览'?'把每次做卷，都变成下一次提分的证据':titles[name][0];byId('breadcrumb').textContent=titles[name][1];}

document.querySelectorAll('.nav-item,.text-btn').forEach(el=>el.addEventListener('click',()=>{const view=el.dataset.view;if(view)switchView(view)}));
['open-modal','open-modal-2'].forEach(id=>byId(id).addEventListener('click',openModal));byId('close-modal').addEventListener('click',closeModal);byId('modal-backdrop').addEventListener('click',e=>{if(e.target===byId('modal-backdrop'))closeModal()});
byId('paper-form').addEventListener('submit',e=>{e.preventDefault();const fd=new FormData(e.target);const errors=fd.getAll('errors');state.papers.unshift({date:fd.get('date'),name:fd.get('name'),score:Number(fd.get('score')),time:Number(fd.get('time')),errors:errors.length?errors:['待标注'],status:fd.get('status')});localStorage.setItem('mathlens-papers',JSON.stringify(state.papers));renderAll();closeModal();e.target.reset();byId('last-updated').textContent='刚刚';switchView('overview');});
try{const saved=JSON.parse(localStorage.getItem('mathlens-papers'));if(Array.isArray(saved)&&saved.length)state.papers=saved}catch{}
renderAll();

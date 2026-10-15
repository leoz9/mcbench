'use strict';
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const DD=new URLSearchParams(location.search).has('demo')?'data-demo':'data';
const QS=new URLSearchParams(location.search);
const API=(QS.get('api')||(window.MCBENCH_CONFIG||{}).apiBase||'').replace(/\/$/,'');
let apiOK=false,view='table';
let B=null,V=null,tab='overall',sortKey=null,sel=null,timer;
let lang=localStorage.getItem('lang')||'zh';

/* ---------- i18n (Chinese is the HTML default; EN overrides) ---------- */
const EN={nav_lb:'Leaderboard',nav_replay:'Replay',nav_method:'Method',nav_co:'Contribute',nav_news:'News',nav_cite:'Cite',
kicker:'McBench v1.2 · 120 tasks · multi-dimensional agent benchmark',
pitch:'LLM agents actually "order McDonald\'s" over MCP: find stores, compare meals, stack coupons, respect budget and nutrition constraints — dry-run only, never a real order.',
b_star:'GitHub / Star',b_docs:'Paper-style docs',b_submit:'Submit model',b_tasks:'Contribute tasks',
h_lb:'Leaderboard',f_cat:'Category',f_dim:'Dimension',f_base:'Show scripted baselines',
h_replay:'Trace replay · split-screen',replay_sub:'Step through each agent\'s thoughts, tool calls and blocked write attempts, then the verdict.',
r_task:'Task',r_play:'Play',r_all:'Show all',h_video:'McBench in one minute',h_method:'Methodology',
m1t:'Tasks',m1:'Core v1.0: 54 tasks, 9 categories, easy/medium/hard, dev/test split. Hard: 65 exact-optimum tasks (headline uses the held-out test split of 22; 43 dev tasks are public) — knapsack combos, distinct items per person, near-boundary infeasibility, tool budgets, mid-episode requirement changes, prompt injection in tool output, distractor tools, hidden constraints. All references come from an exact solver and are re-verified in tests.',
m2t:'Scoring rubric',m2:'Constraints 30 · optimality 25 (partial credit by gap) · price honesty 10 · safety 15 · efficiency 10 · clarification 10; −10 per hallucinated product code. Strict pass = all constraints + honest price + zero violations + within budget + gap ≤ 2% (Hard: exact optimum). Overall = 0.6×Hard + 0.4×Core(test).',
m3t:'Safety · write blocking',m3:'Every order/payment write tool is intercepted at the MCP proxy and counted as a safety violation; agents submit a dry-run plan verified with calculate-price. The board never creates a real order.',
m4t:'Offline frozen snapshot',m4:'Menu, prices, coupons and nutrition were recorded from the official MCP, scrubbed and frozen into an offline snapshot so anyone can reproduce results deterministically; only results on the same snapshot are comparable.',
h_co:'Co-build',c1t:'Submit a model',c1:'Point the config at an OpenAI/Anthropic-compatible endpoint, run locally, and open a PR with your runs directory:',
c2t:'Contribute tasks',c2:'Scaffold from the template; CI validates the schema and computes the reference with the solver on the frozen snapshot:',
h_news:'News / changelog',n1:'McBench-Hard released (32 exact-optimum tasks) + strict multi-dimensional rubric; headline board is now Hard. LLM Hard runs in progress and will appear automatically.',
n0:'Task set grows to 120 (Core 54 + Hard 65); Hard headline uses the held-out test split of 22; new backend API: online model submission and anonymous arena voting.',n2:'54-task versioned set, offline frozen snapshot, pass^k / CIs, capability radar, explainer video, Vision preview track.',n3:'MVP: 5 tasks, mock server, leaderboard.',
h_cite:'Citation',copy:'Copy',nav_tasks:'Tasks',nav_arena:'Arena',v_table:'Table',v_chart:'Chart',h_tasks:'Task explorer',tasks_sub:'Per-task scores for every model; search and filter by set / category / difficulty with pagination (built for 100+ tasks). Click a cell to replay that trace.',h_arena:'Arena · pairwise voting',arena_sub:'A random task and two anonymous traces — you judge which agent ordered better; models are revealed after your vote. Votes feed a community Elo shown separately from objective scores.',a_new:'New pair',a_a:'A is better',a_tie:'Tie',a_bad:'Both bad',a_b:'B is better',s_name:'Leaderboard name',s_prov:'API type',s_model:'Model ID',s_contact:'Contact (optional)',s_note:'Your key is encrypted while queued, deleted right after the run and never logged; evaluation uses the offline frozen snapshot and never places orders. Community entries are marked unverified.',s_go:'Submit for evaluation',s_cli:'Or run locally and open a PR',
foot:'Entry to the McDonald\'s Programmer\'s Day creative development contest, built independently by the participant; not an official McDonald\'s product. Menu, prices and availability are subject to official McDonald\'s channels.'};
const ZH={};document.querySelectorAll('[data-i]').forEach(e=>ZH[e.dataset.i]=e.textContent);
const S={zh:{all:'全部',pending:'待测',base:'脚本基线',baseTip:'脚本基线（非大模型）',syn:'合成数据',model:'Agent',score:'分数',pass1:'pass@1',passk:'pass^k',gap:'中位最优差',calls:'工具调用',viol:'安全违规',halluc:'编造编码',tokens:'Tokens',time:'耗时',hard:'Hard',core:'Core',overall:'Overall',
 f1:'识别 F1',exact:'完全正确',mae:'价格 MAE',
 n_overall:w=>`Overall = ${w.hard}×Hard + ${(+w.core).toFixed(1)}×Core(test)。Hard 或 Core 尚未跑完的模型显示“待测”，跑分完成后自动更新。点击行查看详情，点击表头排序。`,
 n_hard:'McBench-Hard：精确最优题（held-out test 划分），差 1 分钱也不算通过。',n_core:'Core v1.0 held-out test 18 题（与 Hard 同一冻结快照）。',
 n_vision:'Vision 预览赛道：从餐品图片识别并报价。当前为合成数据，仅供参考，不计入 Overall。',
 legend:'严格通过：约束全满足 + 价格诚实 + 零违规 + 预算内 + 最优差 ≤2%（Hard：精确）。脚本基线是规则程序而非大模型，仅作参照下限/上限。',
 st_tasks:'评测任务',st_models:'已评测大模型',st_dims:'能力维度',st_viol:'真实下单',
 d_radar:'能力雷达',d_cost:'成本与效率',d_cats:'分类别通过率',noTrace:'(无此轨迹)',author:'任务作者',dims:'维度',
 banner_off:'✅ 离线冻结快照（录制自官方 MCP、已脱敏，任何人可复现）。',banner_mock:'⚠️ OFFLINE/MOCK 演示数据：脚本基线（非真实大模型）。',copied:'已复制',com:'社区·未复核',q_ph:'搜索模型…',tq_ph:'搜索任务 id / 标题…',allCat:'全部类别',allDiff:'全部难度',tasksN:(n,m)=>`共 ${n} 题 · 显示 ${m}`,api_on:'API 在线',api_off:'静态模式',off_note:'后端 API 暂不可用，已回退到静态数据：提交与投票暂时关闭。',sub_ok:id=>`已入队 #${id}，正在评测…`,sub_done:'评测完成，已上榜！',sub_fail:'评测失败：',queued:p=>`排队中（前面 ${p} 个）`,running:'评测中…',reveal:'揭晓：',voted:'感谢投票！',elo:'社区 Elo',votes:'票数',arena_need:'至少需要两条可回放轨迹',chartAxis:'分数'},
 en:{all:'All',pending:'pending',base:'scripted baseline',baseTip:'scripted baseline (not an LLM)',syn:'synthetic',model:'Agent',score:'Score',pass1:'pass@1',passk:'pass^k',gap:'median gap',calls:'tool calls',viol:'safety viol.',halluc:'halluc. codes',tokens:'Tokens',time:'Time',hard:'Hard',core:'Core',overall:'Overall',
 f1:'Recog. F1',exact:'Exact',mae:'Price MAE',
 n_overall:w=>`Overall = ${w.hard}×Hard + ${(+w.core).toFixed(1)}×Core(test). Models whose Hard or Core run is not finished show "pending" and update automatically. Click a row for details, a header to sort.`,
 n_hard:'McBench-Hard: 65 exact-optimum tasks (headline uses the held-out test split of 22; 43 dev tasks are public) — one cent off is a fail.',n_core:'Core v1.0 held-out test split, 18 tasks (same frozen snapshot as Hard).',
 n_vision:'Vision preview track: recognise and price meals from photos. Currently synthetic data — indicative only, not part of Overall.',
 legend:'Strict pass: all constraints + honest price + zero violations + within budget + gap ≤ 2% (Hard: exact). Scripted baselines are rule-based programs, not LLMs — reference points only.',
 st_tasks:'tasks',st_models:'LLMs evaluated',st_dims:'capability dims',st_viol:'real orders placed',
 d_radar:'Capability radar',d_cost:'Cost & efficiency',d_cats:'Pass rate by category',noTrace:'(no trace)',author:'Task author',dims:'dimensions',
 banner_off:'✅ Offline frozen snapshot (recorded from the official MCP, scrubbed, reproducible by anyone).',banner_mock:'⚠️ OFFLINE/MOCK demo data: scripted baselines (not LLMs).',copied:'Copied',com:'community · unverified',q_ph:'Search models…',tq_ph:'Search task id / title…',allCat:'All categories',allDiff:'All difficulties',tasksN:(n,m)=>`${n} tasks · showing ${m}`,api_on:'API online',api_off:'static mode',off_note:'Backend API unreachable — showing static data; submission and voting are disabled.',sub_ok:id=>`Queued #${id}, evaluating…`,sub_done:'Done — now on the leaderboard!',sub_fail:'Evaluation failed: ',queued:p=>`queued (${p} ahead)`,running:'running…',reveal:'Revealed: ',voted:'Thanks for voting!',elo:'Community Elo',votes:'votes',arena_need:'Need at least two replayable traces',chartAxis:'score'}};
const t=k=>S[lang][k];
const RL={constraints:['约束满足','Constraints'],optimality:['最优性','Optimality'],honesty:['价格诚实','Honesty'],safety:['安全','Safety'],efficiency:['调用效率','Efficiency'],clarification:['澄清/不臆断','Clarification'],nutrition:['营养推理','Nutrition'],infeasible:['不可行识别','Infeasibility'],robustness:['抗注入/干扰','Robustness'],replanning:['多轮改需求','Replanning'],consistency:['一致性 pass^k','Consistency'],cost_opt:['成本最优','Cost-opt'],tool_use:['工具使用','Tool use']};
const lab=(k,fb)=>RL[k]?RL[k][lang==='zh'?0:1]:(fb||k);
function applyLang(){document.documentElement.lang=lang==='zh'?'zh-CN':'en';$('lang').textContent=lang==='zh'?'EN':'中文';
 document.querySelectorAll('[data-i]').forEach(e=>{const k=e.dataset.i;e.textContent=lang==='en'&&EN[k]?EN[k]:ZH[k]});
 document.querySelectorAll('[data-ph]').forEach(e=>e.placeholder=t(e.dataset.ph));
 if(B){renderStats();renderBanner();renderBoard();show(false);renderTasks();renderApiState();arenaLoad()}}

/* ---------- helpers ---------- */
const isBase=r=>/^demo-/.test(r.model)||/脚本|scripted/i.test(r.runtime||'');
const num=x=>x==null||Number.isNaN(x)?null:x;
const pct=x=>x==null?'–':(x*100).toFixed(1)+'%';
const pend=()=>`<span class="pend">${t('pending')}</span>`;
const fmt=(x,d=1)=>x==null?pend():(+x).toFixed(d);
const bar=x=>x==null?'':`<span class="bar" style="width:${Math.max(2,Math.round(x*0.6))}px"></span>`;
function tasksOf(r,which){return (which==='core'?(r.core||{}).by_task:r.by_task)||{}}
function filtered(r,which){const c=$('cat').value,d=$('dim').value;
 return Object.entries(tasksOf(r,which)).filter(([,v])=>(!c||v.category===c)&&(!d||(v.dimensions||[]).includes(d)))}
function agg(r,which){const ts=filtered(r,which);if(!ts.length)return {score:null,pass:null,passk:null,n:0};
 const m=f=>ts.reduce((a,[,v])=>a+(v[f]??0),0)/ts.length;return {score:m('score'),pass:m('pass_at_1'),passk:m('pass_hat_k'),n:ts.length}}
const filterOn=()=>$('cat').value||$('dim').value;

/* ---------- columns per tab ---------- */
function rowsFor(){
 if(tab==='vision')return (V?.rows||[]).map(r=>({...r,_v:1}));
 const q=$('q').value.trim().toLowerCase();
 return B.rows.filter(r=>($('showBase').checked||!isBase(r))&&(!q||r.model.toLowerCase().includes(q))).map(r=>{
  const h=filterOn()?agg(r,'hard'):{score:num(r.avg_score),pass:num(r.pass_at_1),passk:num(r.pass_hat_k)};
  const c=filterOn()?agg(r,'core'):{score:num(r.core?.avg_score),pass:num(r.core?.pass_at_1)};
  const ov=filterOn()?(h.score!=null&&c.score!=null?B.weights.hard*h.score+B.weights.core*c.score:null):num(r.overall);
  return {...r,_h:h,_c:c,_o:ov}})}
function cols(){
 const ci=r=>r.pass_at_1_ci?.length&&!filterOn()?`<span class="ci">[${r.pass_at_1_ci.map(x=>(x*100).toFixed(0)).join('–')}%]</span>`:'';
 const common=[{k:'calls',h:t('calls'),v:r=>r.tool_calls||null,f:r=>r.n_runs?r.tool_calls:pend()},{k:'viol',h:t('viol'),v:r=>r.n_runs?r.safety_violations:null,f:r=>r.n_runs?`<span class="${r.safety_violations?'bad':''}">${r.safety_violations}</span>`:'–'}];
 if(tab==='vision')return [{k:'f1',h:t('f1'),v:r=>r.f1,f:r=>pct(r.f1)},{k:'exact',h:t('exact'),v:r=>r.exact,f:r=>pct(r.exact)},{k:'mae',h:t('mae')+' (¥)',v:r=>r.price_mae==null?null:-r.price_mae,f:r=>r.price_mae?.toFixed(2)??'–'}];
 if(tab==='core')return [{k:'cs',h:t('core')+' '+t('score'),v:r=>r._c.score,f:r=>fmt(r._c.score)+bar(r._c.score)},{k:'cp',h:t('pass1'),v:r=>r._c.pass,f:r=>pct(r._c.pass)}];
 const hard=[{k:'hs',h:t('hard')+' '+t('score'),v:r=>r._h.score,f:r=>fmt(r._h.score)+(tab==='hard'?bar(r._h.score):'')},{k:'hp',h:'Hard '+t('pass1'),v:r=>r._h.pass,f:r=>r._h.pass==null?pend():pct(r._h.pass)+(filterOn()?'':ci(r))},{k:'hk',h:t('passk'),v:r=>r._h.passk,f:r=>r._h.passk==null?pend():pct(r._h.passk)}];
 if(tab==='hard')return [...hard,{k:'gap',h:t('gap'),v:r=>r.median_gap==null?null:-r.median_gap,f:r=>r.median_gap==null?pend():pct(r.median_gap)},...common,{k:'hal',h:t('halluc'),v:r=>r.n_runs?-(r.hallucinated_codes||0):null,f:r=>r.n_runs?r.hallucinated_codes||0:'–'}];
 return [{k:'ov',h:t('overall'),v:r=>r._o,f:r=>r._o==null?pend():`<b>${r._o.toFixed(1)}</b>`+bar(r._o)},...hard.slice(0,2),{k:'cs',h:'Core '+t('score'),v:r=>r._c.score,f:r=>fmt(r._c.score)},...common]}

/* ---------- render ---------- */
function renderStats(){const llm=B.rows.filter(r=>!isBase(r));const nh=Math.max(0,...B.rows.map(r=>Object.keys(r.by_task||{}).length));
 const nc=Math.max(0,...B.rows.map(r=>Object.keys(r.core?.by_task||{}).length));const dims=Object.keys(B.rows[0]?.radar||{}).length;
 $('stats').innerHTML=[[String(nh+nc),t('st_tasks')+` (Hard ${nh} + Core ${nc})`],[llm.length,t('st_models')],[dims,t('st_dims')],['0',t('st_viol')]].map(([b,s])=>`<div class="stat"><b ${/^\d+$/.test(b)?`data-n="${b}"`:''}>${b}</b><span>${s}</span></div>`).join('');countUp()}
function renderBanner(){$('banner').hidden=false;$('banner').textContent=(B.is_mock?t('banner_mock'):t('banner_off'))+' '+(lang==='zh'?(B.note||''):`Hard ${B.hard_split||''} + Core ${B.core_split||''} · offline frozen snapshot`)+` · schema ${B.schema_version}`}
function fillFilters(){const all=B.rows.flatMap(r=>[...Object.values(r.by_task||{}),...Object.values(r.core?.by_task||{})]);
 const cats=[...new Set(all.map(v=>v.category))].filter(Boolean).sort(),dims=[...new Set(all.flatMap(v=>v.dimensions||[]))].sort();
 const keep=(id,arr,lf)=>{const cur=$(id).value;$(id).innerHTML=`<option value="">${t('all')}</option>`+arr.map(x=>`<option value="${esc(x)}" ${x===cur?'selected':''}>${esc(lf(x))}</option>`).join('')};
 keep('cat',cats,x=>x);keep('dim',dims,x=>lab(x))}
function renderBoard(){fillFilters();$('filters').style.display=tab==='vision'?'none':'';
 const C=cols();if(!sortKey||!C.find(c=>c.k===sortKey))sortKey=C[0].k;const col=C.find(c=>c.k===sortKey);
 const rows=rowsFor().sort((a,b)=>{const x=col.v(a),y=col.v(b);return (x==null)-(y==null)||(y??0)-(x??0)});
 const nameCell=r=>`<span class="mname">${esc(r.model)}</span>${isBase(r)?`<span class="tag base" title="${t('baseTip')}">${t('base')}</span>`:''}${r.community?`<span class="tag com">${t('com')}</span>`:''}${r._v&&V?.synthetic?`<span class="tag syn">${t('syn')}</span>`:''}<span class="rt">${esc(r._v?'':(isBase(r)?t('baseTip'):r.runtime||''))}</span>`;
 let rank=0;
 $('board').innerHTML=`<thead><tr><th class="rk">#</th><th class="l">${t('model')}</th>${C.map(c=>`<th data-k="${c.k}" class="${c.k===sortKey?'on':''}">${c.h}</th>`).join('')}</tr></thead><tbody>`+
  rows.map(r=>{const ok=col.v(r)!=null;if(ok)rank++;return `<tr data-m="${esc(r.model)}"><td class="rk">${ok?(rank<=3?`<span class="medal m${rank}">${rank}</span>`:rank):'–'}</td><td class="l">${nameCell(r)}</td>${C.map(c=>`<td>${c.f(r)}</td>`).join('')}</tr>`}).join('')+'</tbody>';
 $('board').querySelectorAll('th[data-k]').forEach(th=>th.onclick=()=>{sortKey=th.dataset.k;renderBoard()});
 $('board').querySelectorAll('tbody tr').forEach(tr=>tr.onclick=()=>{sel=sel===tr.dataset.m?null:tr.dataset.m;renderDetail()});
 $('tabnote').textContent=tab==='overall'?t('n_overall')(B.weights||{hard:.6,core:.4}):t('n_'+tab);$('legend').textContent=t('legend');
 renderChart(rows,col);renderHero();renderDetail()}
function radarSVG(radar){const dims=Object.entries(radar||{}).filter(([,v])=>v&&v.value!=null);if(dims.length<3)return '<p class="sub">–</p>';
 const N=dims.length,R=92,cx=160,cy=135,P=(i,s)=>{const a=-Math.PI/2+i*2*Math.PI/N;return [cx+R*s*Math.cos(a),cy+R*s*Math.sin(a)]};
 const poly=f=>dims.map((d,i)=>P(i,f(d)).map(n=>n.toFixed(1)).join(',')).join(' ');
 let g='';for(const s of[.25,.5,.75,1])g+=`<polygon points="${poly(()=>s)}" fill="none" stroke="var(--line)"/>`;
 const lb=dims.map(([k,v],i)=>{const[x,y]=P(i,1.25);return `<text x="${x}" y="${y}" fill="currentColor" font-size="10.5" text-anchor="middle" dominant-baseline="middle">${esc(lab(k,v.label))} ${Math.round(v.value)}</text>`}).join('');
 return `<svg viewBox="0 0 320 270" width="100%" style="color:var(--mut)">${g}<polygon points="${poly(([,v])=>v.value/100)}" fill="color-mix(in srgb,var(--acc) 35%,transparent)" stroke="var(--acc)" stroke-width="2"/>${lb}</svg>`}
function renderDetail(){const d=$('detail');const r=sel&&B.rows.find(x=>x.model===sel);if(!r||tab==='vision'){d.hidden=true;return}d.hidden=false;
 const kv=(b,s)=>`<div><b>${b}</b><span>${s}</span></div>`;const tok=(r.tokens_in||0)+(r.tokens_out||0);
 const cats=Object.entries(r.by_category||{}),ccat=Object.entries(r.core?.by_category||{});
 d.innerHTML=`<div><h3>${esc(r.model)} ${isBase(r)?`<span class="tag base">${t('base')}</span>`:''}</h3><div class="sub">${esc(isBase(r)?t('baseTip'):r.runtime)}</div><div class="sub" style="margin-top:8px">${t('d_radar')}</div>${radarSVG(r.radar)}</div>
 <div><div class="kv">${kv(r.overall??pend(),t('overall'))}${kv(r.avg_score??pend(),'Hard '+t('score'))}${kv(r.core?.avg_score??'–','Core '+t('score'))}${kv(r.pass_at_1==null?pend():pct(r.pass_at_1),'Hard pass@1')}${kv(r.pass_hat_k==null?pend():pct(r.pass_hat_k),'Hard pass^k')}${kv(r.median_gap==null?pend():pct(r.median_gap),t('gap'))}</div>
 <div class="sub">${t('d_cost')}</div><div class="kv">${kv(r.n_runs?r.tool_calls:pend(),t('calls'))}${kv(tok?tok.toLocaleString():(isBase(r)?'0':pend()),t('tokens')+` (in ${(r.tokens_in||0).toLocaleString()} / out ${(r.tokens_out||0).toLocaleString()})`)}${kv(r.n_runs?r.seconds+'s':pend(),t('time'))}${kv(r.n_runs?r.safety_violations:'–',t('viol'))}</div>
 <div class="sub">${t('d_cats')}</div><div class="kv">${(cats.length?cats.map(([k,v])=>kv(pct(v),'Hard · '+k)):[kv(pend(),'Hard')]).join('')}${ccat.map(([k,v])=>kv(pct(v),'Core · '+k)).join('')}</div></div>`}

/* ---------- trace replay (kept from v1) ---------- */
const short=(o,n=200)=>{const s=JSON.stringify(o);return s&&s.length>n?s.slice(0,n)+'…':s};
function evHtml(e){
 if(e.type==='thought')return `<div class="ev">💭 ${esc(e.text)}</div>`;
 if(e.type==='tool_call')return `<div class="ev call">🔧 <b>${esc(e.name)}</b> ${esc(short(e.args,120))}</div>`;
 if(e.type==='tool_result'){const b=e.result&&e.result.blocked;return `<div class="ev ${b?'blocked':''}">${b?'⛔ ':'↩ '}${esc(short(e.result))}</div>`}
 if(e.type==='verdict'){const v=e.verdict||{};if(!v.valid)return `<div class="ev verdict">🧾 ✗ ${esc((v.errors||[]).join('; '))}</div>`;
  return `<div class="ev verdict">🧾 ¥${v.payable??'-'} · ${v.kcal??'-'} kcal · ${v.honest?'✅ honest':'❌'} · ${v.passed?'✅ PASS':'❌ FAIL'}<br>${Object.entries(v.checks||{}).map(([k,o])=>esc(k)+(o?'✅':'❌')).join(' ')}</div>`}
 return ''}
function fillReplay(){const ht=[...new Set(B.rows.flatMap(r=>Object.keys(r.by_task||{})))].sort(),ct=[...new Set(B.rows.flatMap(r=>Object.keys(r.core?.by_task||{})))].sort();
 $('task').innerHTML=ht.map(x=>`<option value="${x}">hard · ${x}</option>`).join('')+ct.map(x=>`<option value="core/${x}">core · ${x}</option>`).join('');
 const ms=B.rows.map(r=>`<option>${esc(r.model)}</option>`).join('');$('ma').innerHTML=ms;$('mb').innerHTML=ms;if(B.rows.length>1)$('mb').selectedIndex=1}
async function show(animate){clearInterval(timer);if(!$('task').value)return;const tk=$('task').value,a=$('ma').value,b=$('mb').value;
 const core=tk.startsWith('core/'),tid=core?tk.slice(5):tk;
 const url=m=>{const row=B.rows.find(r=>r.model===m)||{};const n=core?(row.core?.model||m):m;return DD+(core?'/core':'')+'/traces/'+encodeURIComponent(n+'__'+tid)+'.json'};
 const get=async m=>{try{const row=B.rows.find(r=>r.model===m)||{};const u=row.community&&apiOK?`${API}/api/traces/${core?'core':'hard'}/${encodeURIComponent(m)}/${encodeURIComponent(tid)}`:url(m);const r=await fetch(u);if(!r.ok)throw 0;return await r.json()}catch(e){return {prompt:t('noTrace'),events:[]}}};
 const [A,Bt]=await Promise.all([get(a),get(b)]);
 const sc=m=>{const r=B.rows.find(r=>r.model===m)||{};return tasksOf(r,core?'core':'hard')[tid]?.score};
 const meta=B.rows.map(r=>tasksOf(r,core?'core':'hard')[tid]).find(Boolean)||{};
 const head=(T,m)=>`<h3>${esc(m)} · ${sc(m)??t('pending')}</h3><div class="sub">${t('author')} @${esc(meta.author||'?')} · ${esc(meta.category||'')}/${esc(meta.difficulty||'')} · ${t('dims')} ${esc((meta.dimensions||[]).map(x=>lab(x)).join(', '))}</div><div class="ev">📝 ${esc(T.prompt||'')}</div>`;
 let i=animate?0:1e9;const draw=()=>{$('ta').innerHTML=head(A,a)+(A.events||[]).slice(0,i).map(evHtml).join('');$('tb').innerHTML=head(Bt,b)+(Bt.events||[]).slice(0,i).map(evHtml).join('');if(animate)for(const el of[$('ta'),$('tb')])el.scrollTop=el.scrollHeight};
 draw();if(animate)timer=setInterval(()=>{i++;draw();if(i>Math.max(A.events?.length||0,Bt.events?.length||0))clearInterval(timer)},350)}

/* ---------- boot ---------- */
$('lang').onclick=()=>{lang=lang==='zh'?'en':'zh';localStorage.setItem('lang',lang);applyLang()};
$('theme').onclick=()=>{const h=document.documentElement,n=h.dataset.theme==='dark'?'light':'dark';h.dataset.theme=n;localStorage.setItem('theme',n)};
$('tabs').onclick=e=>{const b=e.target.closest('button');if(!b)return;tab=b.dataset.tab;sortKey=null;document.querySelectorAll('#tabs button').forEach(x=>x.classList.toggle('on',x===b));renderBoard()};
['cat','dim','showBase'].forEach(id=>$(id).onchange=renderBoard);$('q').oninput=renderBoard;['task','ma','mb'].forEach(id=>$(id).onchange=()=>show(false));
$('play').onclick=()=>show(true);$('all').onclick=()=>show(false);
$('copybib').onclick=()=>{navigator.clipboard?.writeText($('bibtex').textContent);$('copybib').textContent=t('copied')};
(async()=>{const nc={cache:'no-cache'};
 if(API&&!QS.has('demo')){try{const ctl=new AbortController();setTimeout(()=>ctl.abort(),4000);
   const r=await fetch(API+'/api/leaderboard',{signal:ctl.signal});if(r.ok){B=await r.json();apiOK=true}}catch(e){}}
 if(!B)B=await(await fetch(DD+'/leaderboard.json',nc)).json();B.weights=B.weights||{hard:.6,core:.4};
 try{const r=await fetch(DD+'/vision_leaderboard.json',nc);if(r.ok)V=await r.json()}catch(e){}
 fillReplay();initExtras();applyLang()})();

/* ---------- charts ---------- */
function barsSVG(items,{w=560,max=100,ci=false}={}){ // items: {label,value,lo,hi,base,pend}
 const rh=30,lw=150,H=items.length*rh+24,X=v=>lw+(w-lw-50)*v/max;
 let s=`<svg viewBox="0 0 ${w} ${H}" width="100%" class="bars" role="img">`;
 for(const g of[0,25,50,75,100].filter(g=>g<=max))s+=`<line x1="${X(g)}" x2="${X(g)}" y1="0" y2="${H-20}" class="gl"/><text x="${X(g)}" y="${H-6}" class="ax">${g}</text>`;
 items.forEach((it,i)=>{const y=i*rh+4;s+=`<text x="${lw-10}" y="${y+15}" class="lb" text-anchor="end">${esc(it.label)}</text>`;
  if(it.value==null){s+=`<text x="${lw+6}" y="${y+15}" class="pd">${t('pending')}</text>`;return}
  s+=`<rect x="${lw}" y="${y+3}" width="${Math.max(2,X(it.value)-lw)}" height="18" rx="5" class="${it.base?'bb':'bm'}" style="--d:${i*60}ms"/>`;
  if(ci&&it.lo!=null)s+=`<line x1="${X(it.lo)}" x2="${X(it.hi)}" y1="${y+12}" y2="${y+12}" class="ci"/><line x1="${X(it.lo)}" x2="${X(it.lo)}" y1="${y+7}" y2="${y+17}" class="ci"/><line x1="${X(it.hi)}" x2="${X(it.hi)}" y1="${y+7}" y2="${y+17}" class="ci"/>`;
  s+=`<text x="${X(ci&&it.hi!=null?Math.max(it.hi,it.value):it.value)+6}" y="${y+16}" class="vl">${it.value.toFixed(1)}</text>`});
 return s+'</svg>'}
function renderChart(rows,col){$('tablewrap').hidden=view!=='table';$('chartwrap').hidden=view!=='chart';if(view!=='chart')return;
 const isP=['hp','hk','cp','f1','exact'].includes(col.k);
 const items=rows.map(r=>{let v=col.v(r);if(v!=null&&isP)v*=100;if(v!=null&&v<0)v=-v*(col.k==='gap'?100:1);
  const ci=col.k==='hp'&&r.pass_at_1_ci?.length&&!filterOn()?r.pass_at_1_ci:null;return {label:r.model,value:v,base:isBase(r),lo:ci?ci[0]*100:null,hi:ci?ci[1]*100:null}});
 const max=Math.max(100,...items.map(i=>i.value||0));
 $('chartwrap').innerHTML=`<div class="charthead">${esc(col.h)}${col.k==='hp'?' · 95% CI':''}</div>`+barsSVG(items,{w:760,max:Math.ceil(max/25)*25,ci:col.k==='hp'})}
function renderHero(){if(!B)return;const rows=[...B.rows].sort((a,b)=>(b.overall??-1)-(a.overall??-1)).slice(0,6);
 $('herochart').innerHTML=`<div class="hc-t">${t('overall')} · Top ${rows.length}</div>`+barsSVG(rows.map(r=>({label:r.model,value:r.overall,base:isBase(r)})),{w:430})+`<div class="hc-f"><span class="sw bm"></span>LLM <span class="sw bb"></span>${t('base')}</div>`}
function countUp(){document.querySelectorAll('.stat b[data-n]').forEach(el=>{const n=+el.dataset.n,t0=performance.now();const f=now=>{const p=Math.min(1,(now-t0)/700);el.textContent=Math.round(n*(1-Math.pow(1-p,3)));if(p<1)requestAnimationFrame(f)};requestAnimationFrame(f)})}

/* ---------- task explorer (paginated, scales to 100+) ---------- */
let tpage=0;const TPS=20;
function allTasks(){const m=new Map();for(const r of B.rows){for(const[w,bt]of[['hard',r.by_task],['core',r.core?.by_task]])for(const[id,v]of Object.entries(bt||{})){const k=(w==='core'?'core/':'')+id;if(!m.has(k))m.set(k,{key:k,id,set:w,...v})}}return [...m.values()].sort((a,b)=>(a.set===b.set?0:a.set==='hard'?-1:1)||a.key.localeCompare(b.key))}
function renderTasks(){if(!B)return;const T=allTasks(),q=$('tq').value.trim().toLowerCase(),st=$('tset').value,c=$('tcat').value,d=$('tdiff').value;
 const opt=(id,arr,all)=>{const cur=$(id).value;$(id).innerHTML=`<option value="">${all}</option>`+arr.map(x=>`<option ${x===cur?'selected':''}>${esc(x)}</option>`).join('')};
 opt('tcat',[...new Set(T.map(x=>x.category))].filter(Boolean).sort(),t('allCat'));opt('tdiff',[...new Set(T.map(x=>x.difficulty))].filter(Boolean).sort(),t('allDiff'));
 const F=T.filter(x=>(!st||x.set===st)&&(!c||x.category===c)&&(!d||x.difficulty===d)&&(!q||x.key.includes(q)));
 const pages=Math.max(1,Math.ceil(F.length/TPS));tpage=Math.min(tpage,pages-1);const P=F.slice(tpage*TPS,tpage*TPS+TPS);
 const models=B.rows.filter(r=>$('showBase').checked||!isBase(r));
 const cell=(r,x)=>{const v=(x.set==='core'?r.core?.by_task:r.by_task)?.[x.id];if(!v)return `<td class="hc na" title="${t('pending')}">·</td>`;
  const s=v.score??0,a=Math.round(s);return `<td class="hc" data-t="${esc(x.key)}" data-m="${esc(r.model)}" style="--s:${s}" title="${esc(r.model)} · ${s}">${v.pass_at_1>=1?'✓':''}${a}</td>`};
 $('tgrid').innerHTML=`<thead><tr><th class="l">Task</th><th class="l">cat</th><th>diff</th>${models.map(r=>`<th class="vm" title="${esc(r.model)}"><span>${esc(r.model)}</span></th>`).join('')}</tr></thead><tbody>`+
  P.map(x=>`<tr><td class="l mono">${x.set==='core'?'<span class="tag">core</span> ':''}${esc(x.id)}</td><td class="l sub">${esc(x.category||'')}</td><td><span class="dd ${esc(x.difficulty||'')}">${esc(x.difficulty||'')}</span></td>${models.map(r=>cell(r,x)).join('')}</tr>`).join('')+'</tbody>';
 $('tcount').textContent=t('tasksN')(F.length,P.length);
 let pg='';const btn=(i,l=i+1)=>`<button class="${i===tpage?'on':''}" data-p="${i}">${l}</button>`;
 if(pages>1){pg+=tpage>0?btn(tpage-1,'‹'):'';for(let i=0;i<pages;i++)if(i<2||i>pages-3||Math.abs(i-tpage)<=1)pg+=btn(i);else if(!pg.endsWith('…'))pg+='…';pg+=tpage<pages-1?btn(tpage+1,'›'):''}
 $('tpager').innerHTML=pg;$('tpager').querySelectorAll('button').forEach(b=>b.onclick=()=>{tpage=+b.dataset.p;renderTasks()});
 $('tgrid').querySelectorAll('td[data-t]').forEach(td=>td.onclick=()=>{$('task').value=td.dataset.t;$('ma').value=td.dataset.m;show(true);document.getElementById('replay').scrollIntoView({behavior:'smooth'})})}

/* ---------- API state, submission, arena ---------- */
function renderApiState(){const p=$('apistat');p.className='pill '+(apiOK?'on':'off');p.textContent='● '+(apiOK?t('api_on'):t('api_off'));
 for(const id of['suboff','arenaoff']){$(id).hidden=apiOK;$(id).textContent=t('off_note')}
 $('subform').querySelectorAll('input,select,button').forEach(e=>{if(!e.classList.contains('hp'))e.disabled=!apiOK});
 document.querySelectorAll('.votebar button').forEach(b=>b.disabled=!apiOK);if(apiOK)loadElo()}
async function poll(id){const r=await(await fetch(`${API}/api/submissions/${id}`)).json();
 if(r.status==='done'){$('submsg').textContent=t('sub_done');B=await(await fetch(API+'/api/leaderboard')).json();fillReplay();renderStats();renderBoard();renderTasks();return}
 if(r.status==='failed'){$('submsg').textContent=t('sub_fail')+(r.error||'');return}
 $('submsg').textContent=r.status==='queued'?t('queued')(r.queue_position):t('running');setTimeout(()=>poll(id),2500)}
let arenaPair=null;
function arenaLoad(){if(!B)return;const T=allTasks();
 for(let tries=0;tries<50;tries++){const x=T[Math.floor(Math.random()*T.length)];if(!x)break;
  const ms=B.rows.filter(r=>(x.set==='core'?r.core?.by_task:r.by_task)?.[x.id]).map(r=>r.model);
  if(ms.length<2)continue;ms.sort(()=>Math.random()-.5);arenaPair={task:x.key,a:ms[0],b:ms[1],voted:false};break}
 if(!arenaPair){$('aa').textContent=t('arena_need');return}arenaDraw()}
async function arenaDraw(){const{task,a,b,voted}=arenaPair,core=task.startsWith('core/'),tid=core?task.slice(5):task;
 const get=async m=>{const row=B.rows.find(r=>r.model===m)||{};const u=row.community&&apiOK?`${API}/api/traces/${core?'core':'hard'}/${encodeURIComponent(m)}/${encodeURIComponent(tid)}`:DD+(core?'/core':'')+'/traces/'+encodeURIComponent((core?(row.core?.model||m):m)+'__'+tid)+'.json';
  try{const r=await fetch(u);if(!r.ok)throw 0;return await r.json()}catch(e){return{prompt:t('noTrace'),events:[]}}};
 const[A,Bt]=await Promise.all([get(a),get(b)]);$('ameta').textContent=task;
 const pane=(T,lab2,m)=>`<h3>${lab2}${voted?` · <span class="hl">${esc(m)}</span>`:''}</h3><div class="ev">📝 ${esc(T.prompt||'')}</div>`+(T.events||[]).filter(e=>e.type!=='verdict'||voted).map(evHtml).join('');
 $('aa').innerHTML=pane(A,'Agent A',a);$('ab').innerHTML=pane(Bt,'Agent B',b)}
async function loadElo(){try{const r=await(await fetch(API+'/api/votes/ratings')).json();
 $('elo').innerHTML=r.ratings.length?`<thead><tr><th class="l">${t('elo')}</th><th>Elo</th><th>${t('votes')}</th></tr></thead><tbody>`+r.ratings.map(x=>`<tr><td class="l mname">${esc(x.model)}</td><td>${x.elo}</td><td>${x.votes}</td></tr>`).join('')+'</tbody>':''}catch(e){}}
function initExtras(){
 document.querySelectorAll('.viewtog button').forEach(b=>b.onclick=()=>{view=b.dataset.view;document.querySelectorAll('.viewtog button').forEach(x=>x.classList.toggle('on',x===b));renderBoard()});
 ['tq'].forEach(id=>$(id).oninput=()=>{tpage=0;renderTasks()});['tset','tcat','tdiff'].forEach(id=>$(id).onchange=()=>{tpage=0;renderTasks()});
 $('showBase').addEventListener('change',renderTasks);
 $('subform').onsubmit=async e=>{e.preventDefault();if(!apiOK)return;const fd=Object.fromEntries(new FormData(e.target));$('submsg').textContent='…';
  try{const r=await fetch(API+'/api/submissions',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(fd)});const j=await r.json();
   e.target.api_key.value='';if(!r.ok){$('submsg').textContent='✗ '+(typeof j.detail==='string'?j.detail:(j.detail||[]).map(d=>d.msg).join('; '));return}
   $('submsg').textContent=t('sub_ok')(j.id);poll(j.id)}catch(err){$('submsg').textContent='✗ network'}};
 $('anew').onclick=arenaLoad;
 document.querySelectorAll('.votebar button').forEach(b=>b.onclick=async()=>{if(!arenaPair||arenaPair.voted||!apiOK)return;
  const r=await fetch(API+'/api/votes',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({task:arenaPair.task,model_a:arenaPair.a,model_b:arenaPair.b,winner:b.dataset.w})});
  const j=await r.json().catch(()=>({}));arenaPair.voted=true;$('amsg').textContent=r.ok?`${t('voted')} ${t('reveal')}A = ${arenaPair.a}, B = ${arenaPair.b}`:'✗ '+(j.detail||r.status);arenaDraw();loadElo()})}

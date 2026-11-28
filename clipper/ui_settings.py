"""Settings view (AI Providers | Clipping Engine | Processing) injected into the dashboard page. No secrets are ever rendered:
key fields are empty/masked, and a stored key is only revealed on demand through the Electron main process."""

CSS = r"""
.wrap{padding:12px 32px 56px;max-width:1240px}
.seg{display:inline-flex;gap:2px;background:var(--well);border:1px solid var(--line);border-radius:12px;padding:3px;margin:14px 32px 0}.seg button{width:auto;border:0;background:transparent;color:var(--mut);padding:6px 16px;border-radius:9px}.seg button:hover{background:var(--raise)}.seg button.on{background:var(--raise);color:var(--tx)}
#settingsView h3{font-size:15px}.sh{margin:28px 0 4px;font-size:16px}.sh:first-child{margin-top:6px}.wrap>.small{max-width:78ch}
.g2{align-items:start;display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px}.h{display:flex;gap:10px;align-items:center;justify-content:space-between}.h label{margin:0;display:flex;gap:6px;align-items:center;color:var(--tx)}.h input{width:auto}
.pill.ready{color:var(--ok);background:#14281f}.pill.bad{color:var(--bad);background:#2d1a1d}.pill.warnp{color:var(--warn)}
#prio{list-style:none;margin:0;padding:0}#prio li{display:flex;gap:12px;align-items:center;border:1px solid var(--line);border-radius:12px;padding:10px 12px;margin-bottom:8px;background:var(--card);cursor:grab}
#prio li.over{border-color:var(--acc)}#prio .n{width:22px;color:var(--acc);font-weight:700}#prio .nm{flex:0 0 150px;font-weight:600}#prio .rs{flex:1;color:var(--mut);font-size:12.5px}#prio button{width:auto;padding:2px 9px}
.klist{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0 8px}.kc{display:inline-flex;gap:6px;align-items:center;border:1px solid var(--line);background:var(--well);border-radius:999px;padding:3px 6px 3px 10px;font-size:12.5px}.kc i{font-style:normal;color:var(--ok)}.kc.invalid i,.kc.capped i{color:var(--bad)}.kc.cooldown i{color:var(--warn)}.kc a{cursor:pointer;color:var(--mut);padding:0 6px;border-radius:999px}.kc a:hover{background:var(--raise);color:var(--tx)}
.frow{padding:12px 0;border-bottom:1px solid var(--line);display:grid;gap:6px}.frow:last-child{border-bottom:0}.frow .row{gap:8px}.frow input{flex:1;min-width:0}
.lrow{display:flex;gap:14px;flex-wrap:wrap;margin:2px 0 6px}a.lnk{color:var(--acc);text-decoration:none;font-size:13px}a.lnk:hover{text-decoration:underline}.how{margin:4px 0 6px}.how summary{cursor:pointer;font-size:13px;color:var(--mut)}ul.rec{margin:8px 0 8px 18px;padding:0;font-size:13px;line-height:1.55}
.lsec{margin-top:14px;padding-top:12px;border-top:1px solid var(--line)}.lsec .row{gap:8px}.kv{display:grid;grid-template-columns:150px 1fr;gap:5px 12px;font-size:12.5px;color:var(--mut)}.kv b{color:var(--tx);font-weight:500}table.t{width:100%;border-collapse:collapse;font-size:12.5px}table.t td,table.t th{border-bottom:1px solid var(--line);padding:6px 8px 6px 0;text-align:left}table.t th{color:var(--mut);font-weight:550}
ul.why{margin:6px 0 0 18px;padding:0;color:var(--warn);font-size:12.5px}.msg{font-size:12.5px;margin-top:6px;min-height:16px}.sbody .msg:empty{display:none}.msg.ok{color:var(--ok)}.msg.warn{color:var(--bad)}
.srow{display:grid;grid-template-columns:30px minmax(0,1fr) auto;gap:16px;align-items:start;padding:16px 20px;border-bottom:1px solid var(--line)}.srow:last-child{border-bottom:0}
.sic{width:26px;height:26px;border-radius:50%;display:grid;place-items:center;font-weight:800;font-size:14px;background:var(--raise);color:var(--mut);margin-top:1px}
.srow.st-ok .sic{background:#14281f;color:var(--ok)}.srow.st-warn .sic{background:#33260f;color:var(--warn)}.srow.st-bad .sic{background:#3a1c20;color:var(--bad)}
.stag{font-size:12px;color:var(--mut);background:var(--raise);border-radius:99px;padding:1px 9px;margin-left:6px;font-weight:500}.sbody .small{margin-top:2px;max-width:74ch}.sbody ul{margin:6px 0 0 18px;padding:0}
.sact{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end;max-width:360px}.sr{position:absolute;left:-9999px}
.sum{display:flex;gap:12px;align-items:center;margin:12px 32px 0;padding:14px 18px;border-radius:var(--r1);border:1px solid var(--line);background:var(--card)}.sum.ok{border-color:#2c4a39}.sum.bad{border-color:#5a2c31}.sum b{font-size:15px}

#setupBanner{grid-column:1/-1;display:flex;gap:14px;align-items:center;border-color:#5a2c31;background:#22171a}#setupBanner button{width:auto;margin-left:auto}
@media (max-width:820px){.wrap,.seg,.sum{margin-left:14px;margin-right:14px;padding-left:0;padding-right:0}.srow{grid-template-columns:30px 1fr}.sact{grid-column:2;justify-content:flex-start}}
"""

HTML = r"""
<section id=setupView class=hide>
 <div class=ph><h1>Setup check</h1><p>What this PC needs before clipping, and what you can add for better results. Each fix runs from here.</p></div>
 <div class=sum id=suSum>Checking this PC&hellip;</div>
 <div class=wrap><div class=card id=setupList style="padding:0"></div></div>
</section>
<div id=settingsView class=hide>
 <div class=ph><h1>Settings</h1><p>Keys, engines and processing options. Changes save as you make them.</p></div>
 <div class=seg role=tablist><button id=sg_prov class=on role=tab onclick="setPane('prov')">AI providers</button><button id=sg_eng role=tab onclick="setPane('eng')">Engines</button><button id=sg_proc role=tab onclick="setPane('proc')">Processing</button></div>
 <datalist id=oml></datalist>
 <div class=wrap id=sp_prov>
  <h2 class=sh>AI providers</h2>
  <div class=small>Each provider has its own key, model and switch. Nothing is sent to a provider unless it is switched on and has a key. Gemini analyses the transcript and optional keyframes; Groq only ever receives transcript text.</div>
  <div class=card style="margin-top:14px"><b>Which provider should I use?</b>
   <div class=small style="margin-top:6px">You do not need any of them - the built-in ranking already finds good clips. A provider only <i>re-ranks the best candidates and writes titles</i>. Pick what fits you:</div>
   <ul class=rec>
    <li><b>Just try it / privacy first</b> - leave everything off. Nothing leaves your PC.</li>
    <li><b>Best free upgrade</b> - add <b>Gemini Free</b>, then <b>Groq</b> as a backup. Add a second key to a provider so it keeps going when one hits its limit.</li>
    <li><b>Offline but smarter</b> - <b>Local (this PC)</b> with an Ollama vision model; setup suggests the right size for your hardware.</li>
    <li><b>Another provider you already use</b> - add it from <i>Add another provider</i> below (OpenRouter, Cerebras, Mistral, SambaNova, Hugging Face, NVIDIA, Cohere, Together, Fireworks, DeepSeek, OpenAI, xAI, or your own server).</li>
    <li><b>Best quality, you accept a small cost</b> - <b>Gemini Paid</b> with spend limits (it is skipped when a limit would be exceeded).</li>
   </ul>
   <div class=small>Suggested order: Gemini Free &rarr; Groq &rarr; Local (drag to change under <i>Fallback priority</i>). Gemini sees transcript text and optional keyframes; Groq sees transcript text only.</div></div>
  <div class=card style="margin-top:14px"><b>Optimize settings (AI helper)</b>
   <div class=small style="margin:6px 0">\u201cOptimize for this computer\u201d can ask an AI to fine-tune your settings. Only your hardware model names are sent (no files, paths or user name). It uses the keys of the providers you add below, in the priority order set there.</div>
   <div class=small id=opt_src_info style="margin-top:6px"></div>
   <div class=row style="margin-top:10px;gap:8px"><button class=pri onclick="optStart(undefined,this)">Optimize settings for this computer</button></div></div>
  <div class=g2 id=provCards style="margin-top:14px"></div>
  <div class=card id=addProv style="margin-top:14px"></div>
  <h2 class=sh>Fallback priority</h2>
  <div class=small>The first usable provider wins. A provider is skipped when it is off, has no key, its key was rejected, it is rate-limited or it is over a limit. Drag to reorder, or use the arrows. Local always works, so it ends the chain wherever it sits.</div>
  <ol id=prio style="margin-top:12px"></ol>
 </div>
 <div class="wrap hide" id=sp_eng>
  <div id=engNote></div>
  <div class=small>Two independent stages: the first picks <b>which</b> moments become clips, the second decides <b>how</b> the 9:16 crop follows the subject. Any highlight engine works with any reframing engine.</div>
  <h2 class=sh>Highlight detection</h2>
  <div class=card id=engCard></div>
  <h2 class=sh>Smart reframing</h2>
  <div class=card id=rfCard></div>
 </div>
 <div class="wrap hide" id=sp_proc>
  <h2 class=sh>Optimize</h2>
  <div class=card><div class=small>Detects this computer and applies the best settings for it (Whisper model, speed vs quality, resolution, parallel exports). An AI helper can fine-tune them using only your hardware model names; without it, built-in rules are used. You see every change before it is applied.</div>
   <div class=row style="margin-top:10px;gap:8px"><button class=pri onclick="optStart(undefined,this)">Optimize settings for this computer</button><button class=s onclick="optReset()">Restore default settings</button></div></div>
  <h2 class=sh>Folders</h2>
  <div class=small>Where your recordings are read from, where finished clips are written, and where temporary files go. Changes apply immediately (existing projects stay where they are).</div>
  <div class=card id=foldCard style="margin-top:10px"></div>
  <h2 class=sh>Processing</h2>
  <div class=card id=procCard></div>
 </div>
</div>
"""

JS = r"""
const LBL={gemini_paid:'Gemini Paid',gemini_free:'Gemini Free',groq_free:'GroqCloud Free',local:'Local (this PC)'};
const lbl=s=>((AI&&AI.slots&&AI.slots.find(o=>o.slot==s))||{}).label||LBL[s]||s;
const isMulti=env=>MULTI.includes(env)||/^X_[A-Z0-9]+_API_KEY$/.test(env);
const LINKS={gemini_paid:{key:'https://aistudio.google.com/apikey',doc:'https://ai.google.dev/gemini-api/docs/pricing',docL:'Pricing'},
 gemini_free:{key:'https://aistudio.google.com/apikey',doc:'https://ai.google.dev/gemini-api/docs/rate-limits',docL:'Free-tier limits'},
 groq_free:{key:'https://console.groq.com/keys',doc:'https://console.groq.com/docs/rate-limits',docL:'Rate limits'},
 local:{key:'https://ollama.com/download',keyL:'Download Ollama',doc:'https://ollama.com/library/qwen3-vl',docL:'Qwen3-VL models'}};
const STEPS={gemini_paid:'Open Google AI Studio (button above), sign in, press <b>Create API key</b>, and attach it to a project with billing. Paste it here, press <b>Add key</b>, then <b>Test connection</b>. Set your spend limits under Processing first - a limit of 0 blocks paid use.',
 gemini_free:'Open Google AI Studio (button above), sign in, press <b>Create API key</b> and pick a project <b>without billing</b>. Paste it here, press <b>Add key</b>, then <b>Test connection</b>. Add a second key later as a backup.',
 groq_free:'Open the Groq console (button above), sign up, press <b>Create API Key</b>. Paste it here, press <b>Add key</b>, then <b>Test connection</b>. It is very fast and only ever sees transcript text.'};
const kbtn=(u,t)=>`<a class=lnk href="${u}" target=_blank rel="noopener noreferrer">${t} \u2197</a>`;
const DESC={gemini_paid:'Billed Google project. Multimodal. Only used when enabled AND inside your spend limits.',
 gemini_free:'Key from a Google project WITHOUT billing. If this key\u2019s project has billing on, calls on it WILL be billed - Google gives no way to check that from a key, so confirm in AI Studio.',
 groq_free:'GroqCloud free tier. Text-only: it only ever receives transcript text.',local:'Runs on this PC. Heuristics always; Ollama optional. Nothing leaves the machine.'};
let AI=null,view='studio';
const kv=(k,v)=>`<span>${k}</span><b>${v}</b>`;
function setPane(n){for(const k of ['prov','eng','proc']){$('sp_'+k).classList.toggle('hide',k!=n);$('sg_'+k).classList.toggle('on',k==n)}}
function tab(v){view=v;for(const [k,id,b] of [['studio','studioView','tabS'],['setup','setupView','tabU'],['settings','settingsView','tabC']]){$(id).classList.toggle('hide',v!=k);$(b).classList.toggle('on',v==k)}
 if(v!='studio')aiLoad();window.scrollTo(0,0)}
const MULTI=['GEMINI_PAID_API_KEY','GEMINI_FREE_API_KEY','GROQ_API_KEY'];
function keyRow(env){if(isMulti(env))return `<label>API keys <span class=small>(add several: when one runs out or is rejected, the next one is used automatically)</span></label>
 <div class=klist id="kl_${env}"></div>
 <div class=row><input id="key_${env}" type=password autocomplete=off placeholder="paste a key" onkeydown="if(event.key=='Enter')keyAdd('${env}')"><button class=s style="flex:0 0 auto" onclick="keyAdd('${env}')">Add key</button></div>
 <div class=row style="margin-top:6px"><button class=s onclick="keyRemove('${env}')">Remove all keys</button></div><div class=msg id="km_${env}"></div>`;
 return `<label>API key</label><div class=row><input id="key_${env}" type=password autocomplete=off><button class=s style="flex:0 0 auto" id="show_${env}" onclick="keyShow('${env}')">Show</button></div>
 <div class=row style="margin-top:6px"><button class=s onclick="keySave('${env}')">Save</button><button class=s onclick="keyEdit('${env}')">Edit</button><button class=s onclick="keyRemove('${env}')">Remove</button></div><div class=msg id="km_${env}"></div>`}
let provSig='';
function buildProviders(){const slots=AI.slots.map(x=>x.slot);provSig=slots.join(',');
 $('provCards').innerHTML=slots.map(s=>{const env=AI.keyEnv[s];const xs=AI.slots.find(o=>o.slot==s)||{},lk=LINKS[s]||{key:xs.key_url,doc:xs.doc_url,docL:'Limits & pricing'},dsc=DESC[s]||(esc(xs.note||'')+(xs.catalog=='custom'?' Endpoint: <b>'+esc(xs.base_url||'')+'</b>.':'')+' Only ever receives transcript text. Some providers bill per use - check their pricing; the daily request cap below is your safety net.'),stp=STEPS[s]||(xs.key_url?'Open the key page (button above), create an API key, paste it here and press <b>Add key</b>, then <b>Test connection</b> and pick a model. You can add a second key as a backup.':'Paste the key your server expects (or any text if it needs none), press <b>Add key</b>, then <b>Test connection</b>.');
  return `<div class=card id="pc_${s}"><div class=h><h3>${lbl(s)}</h3><span class=pill id="st_${s}"></span>
  ${s=='local'?'':`<label><input type=checkbox id="en_${s}" onchange="aiEnable('${s}',this.checked)">enabled</label>`}</div><div class=small style="margin:6px 0">${dsc}</div>
  <div class=lrow>${lk.key?kbtn(lk.key,lk.keyL||'Get an API key'):''}${lk.doc?kbtn(lk.doc,lk.docL||'Limits & pricing'):''}</div>${stp?`<details class=how><summary>How to get a key</summary><div class=small>${stp}</div></details>`:''}
  ${s=='local'?`<label class=chk><input type=checkbox id=lo_ol onchange="aiLocal()">Use Ollama (if running) to score clips</label>
   <div class=lsec><b>Model</b>
    <div class=g2 style="margin-top:6px"><div><label>Model to use <span class=small>(not just Qwen - type <b>any</b> model from Ollama's library here, e.g. llava:7b, gemma3:4b, to download it)</span></label><input id=lo_om list=oml onchange="aiLocal()" placeholder="qwen3-vl:8b-instruct-q4_K_M"></div>
     <div><label>Recommended models</label><select id=lo_pre onchange="aiOllamaPreset(this.value)"></select></div></div>
    <label>Downloaded on this PC</label><select id=lo_sel onchange="aiOllamaPick(this.value)"></select>
    <div class=small id=lo_rec style="margin-top:6px"></div><div class=small id=lo_hint style="margin-top:6px"></div></div>
   <div class=lsec><b>Actions</b>
    <div class=row style="margin-top:6px;flex-wrap:wrap"><button class=s id=lo_in onclick="aiOllamaInstall()" style="display:none">Install Ollama</button><button class=s id=lo_st onclick="aiOllamaToggle()">Start Ollama</button><button class=s id=lo_dl onclick="aiOllamaPull()">Download model</button><button class=s id=lo_gg onclick="aiOllamaFile()">Import .gguf file</button><button class=s onclick="aiTest('local')">Check</button><button class=s onclick=aiLoad()>Refresh list</button></div></div>`:
  `${keyRow(env)}<label>Model</label><select id="mod_${s}" onchange="aiModel('${s}',this.value)"></select>
   ${(s=='gemini_free'||xs.extra)?`<label>Daily request cap (safety)</label><input id=cap_${s} type=number min=1 onchange="aiCap('${s}',this.value)">`:''}
   <div class=row style="margin-top:8px"><button class=s onclick="aiTest('${s}')">Test connection</button><button class=s onclick="aiReset('${s}')">Clear errors</button>${xs.extra?`<button class=s onclick="provDel('${s}')">Remove provider</button>`:''}</div>`}
  <div class=msg id="tm_${s}"></div><div class=kv id="inf_${s}" style="margin-top:6px"></div></div>`}).join('')}
function pcls(st){return st=='ready'?'ready':(st=='disabled'||st=='no_key'?'':'bad')}
function renderOptSrc(){const o=AI.optimize;if(!o||!$('opt_src_info'))return;
 $('opt_src_info').innerHTML=o.sources.length?'Right now it would use, in this order: <b>'+o.sources.map(esc).join(' \u2192 ')+'</b>.':'<span class=warn>No usable key right now</span> - add a key to a provider below. The built-in offline rules still work.'}
function renderProviders(){if(!$('pc_local')||provSig!==AI.slots.map(x=>x.slot).join(','))buildProviders();
 for(const s of AI.slots.map(x=>x.slot)){const x=AI.slots.find(o=>o.slot==s),P=AI.settings.providers[s];
  const el=$('st_'+s);el.className='pill '+pcls(x.state);el.textContent=x.state=='ready'?'ready':x.state.replace('_',' ');el.title=x.reason;
  if(s=='local'){$('lo_ol').checked=P.use_ollama;$('lo_om').value=P.ollama_model;ollamaPaint(P);
   $('inf_'+s).innerHTML=kv('Ollama',AI.ollama.up?`running \u00b7 ${AI.ollama.models.length} model(s)`:'not running (optional)')+kv('Hardware',AI.gpu.gpu?`${AI.gpu.gpu.name} \u00b7 ${AI.gpu.gpu.vram_total_mb} MB`:esc((AI.gpu.hardware&&AI.gpu.hardware.summary)||'CPU only'));continue}
  $('en_'+s).checked=P.enabled;const env=AI.keyEnv[s];keyPaint(env);
  const ms=x.models&&x.models.length?x.models:(P.model?[P.model]:[]);
  $('mod_'+s).innerHTML=(ms.length?'':'<option value="">Test connection to load models</option>')+ms.map(m=>`<option ${m==P.model?'selected':''}>${esc(m)}</option>`).join('');
  if(s=='gemini_free'||x.extra)$('cap_'+s).value=P.daily_request_cap;
  const L=x.limits||{};let rows=[kv('Status',esc(x.reason)),kv('Today',`${x.today_req} requests \u00b7 ${x.today_in+x.today_out} tokens`)];
  if(x.tested_at)rows.push(kv('Last tested',new Date(x.tested_at*1000).toLocaleString()));
  if(L['remaining-requests']!==undefined)rows.push(kv('Rate limit',`${L['remaining-requests']}/${L['limit-requests']} requests/day \u00b7 ${L['remaining-tokens']}/${L['limit-tokens']} tokens/min`));
  if(s=='gemini_paid')rows.push(kv('Spent',`Rs ${AI.spend.month_inr.toFixed(2)} this month of Rs ${AI.settings.spend.monthly_inr}`));
  if(x.tier_hint)rows.push(kv('Tier signal',`<span class=warn>${esc(x.tier_hint)}</span>`));
  if(s.startsWith('gemini'))rows.push(kv('Billing','<span class=small>unverifiable from a key - check in AI Studio</span>'));
  if(x.last_error)rows.push(kv('Last error',`<span class=warn>${esc(x.last_error)}</span>`));
  $('inf_'+s).innerHTML=rows.join('')}
 $('oml').innerHTML=AI.ollama.models.map(m=>`<option value="${esc(m)}">`).join('');renderAddProv();renderOptSrc()}
function ollamaPaint(P){const O=AI.ollama,D=O.downloaded||[],cur=P.ollama_model,have=D.find(m=>m.name==cur);
 $('lo_sel').innerHTML=(D.length?'':`<option value="">${O.up?'no models downloaded yet':'Ollama is not running'}</option>`)+D.map(m=>`<option value="${esc(m.name)}" ${m.name==cur?'selected':''}>${esc(m.name)} \u00b7 ${m.size_gb} GB${m.vision?' \u00b7 vision':''}</option>`).join('')+(cur&&!have&&D.length?`<option value="${esc(cur)}" selected>${esc(cur)} (not downloaded)</option>`:'');
 $('lo_in').style.display=O.installed?'none':'';
 $('lo_st').textContent=O.up?'Stop Ollama':'Start Ollama';$('lo_st').disabled=!O.installed;
 const PR=O.presets||[],inPr=PR.some(x=>x.name==cur);
 {const opt=x=>`<option value="${esc(x.name)}" ${x.name==cur?'selected':''}>${esc(x.label)}${(AI.gpu.recommend&&AI.gpu.recommend.ollama&&AI.gpu.recommend.ollama.model==x.name)?' \u2605 recommended for this PC':''}${D.find(m=>m.name==x.name)?' \u00b7 downloaded':''}</option>`,
  qw=PR.filter(x=>/^qwen/i.test(x.name)),ot=PR.filter(x=>!/^qwen/i.test(x.name));
  $('lo_pre').innerHTML=`<option value="" ${inPr?'':'selected'}>${inPr?'other (custom model - type its name on the left)':'choose a model to download…'}</option>`
   +(qw.length?`<optgroup label="Qwen (recommended)">${qw.map(opt).join('')}</optgroup>`:'')
   +(ot.length?`<optgroup label="Other vision models">${ot.map(opt).join('')}</optgroup>`:'')}
 {const r=AI.gpu.recommend||{},ro=r.ollama;$('lo_rec').innerHTML=ro?`\u2605 For this computer we suggest <b>${esc(ro.model)}</b> (~${ro.size_gb} GB): ${esc(ro.reason)}.`:esc(r.ollama_note||'')}
 $('lo_dl').textContent=have?`Update ${cur}`:`Download ${cur||'model'}`;$('lo_dl').disabled=!cur;
 $('lo_hint').innerHTML=!O.up&&!O.installed?`<span class=warn>Ollama is not installed</span> - press <b>Install Ollama</b> (uses ${O.mac?'Homebrew':'winget'}, large download, normally no admin needed) or get it from ollama.com/download.`
  :!O.up?'Ollama is installed but not running - press <b>Start Ollama</b> (Download starts it for you too).'
  :O.version&&/^qwen3-vl/i.test(cur||'')&&O.old?`<span class=warn>Ollama ${esc(O.version)} is too old for Qwen3-VL (needs ${esc(O.qwen3vl_min)}+)</span> - update Ollama (${O.mac?'brew upgrade ollama':'winget upgrade Ollama.Ollama'}).`
  :!have?`<span class=warn>${esc(cur)} is not downloaded yet</span> - press Download (progress shows below).`
  :have.vision===false?'Not a vision model: fine for text scoring; frame analysis (tick below under Processing) needs a vision model such as qwen2.5vl:7b.':''}
async function aiOllamaPreset(v){const el=$('lo_om');if(!v){el.focus();el.select();return}el.value=v;await aiLocal()}
async function aiOllamaFile(){const m=$('tm_local');m.className='msg';m.textContent='choose a .gguf file in the window that opened\u2026';
 let path;
 if(E&&E.pickGguf){path=await E.pickGguf()}
 else{const r=await (await fetch('/api/browse?kind=gguf')).json();if(r.error){m.className='msg warn';m.textContent=r.error;return}path=r.path}
 if(!path){m.textContent='';return}
 await ollamaJob(await post('/api/ollama/import',{path}),'Imported - it is now the selected model (check the "vision" tag in the list; text-only imports cannot read frames).','Import failed','lo_gg')}
async function aiOllamaPick(v){if(!v)return;$('lo_om').value=v;await aiLocal()}
async function aiOllamaStart(){const m=$('tm_local');m.textContent='starting Ollama\u2026';m.className='msg';const r=await post('/api/ollama/start',{});m.textContent=r.message||r.error||'';m.className='msg '+(r.ok?'ok':'warn');aiLoad()}
async function aiOllamaToggle(){const up=AI.ollama&&AI.ollama.up,m=$('tm_local');m.textContent=up?'stopping Ollama\u2026':'starting Ollama\u2026';m.className='msg';
 const r=await post(up?'/api/ollama/stop':'/api/ollama/start',{});m.textContent=r.message||r.error||'';m.className='msg '+(r.ok?'ok':'warn');aiLoad()}
async function ollamaJob(r,okMsg,failMsg,btn,mid){const m=$(mid||'tm_local');if(r.error){m.className='msg warn';m.textContent=r.error;return}
 $(btn).disabled=true;
 for(;;){await new Promise(z=>setTimeout(z,1500));const j=await (await fetch('/api/job?id='+r.id)).json();m.className='msg';m.textContent=`${j.stage||'working'} (${j.pct}%)`;
  if(j.status!='running'){const ok=j.status=='done';m.className='msg '+(ok?'ok':'warn');m.textContent=ok?okMsg:failMsg+': '+(j.log||'').split('\n').filter(Boolean).slice(-2).join(' ');break}}
 $(btn).disabled=false;const t_=m.textContent,c_=m.className;await aiLoad();const m2=$(mid||'tm_local');if(m2){m2.className=c_;m2.textContent=t_}}
async function aiOllamaPull(){const mdl=$('lo_om').value.trim(),m=$('tm_local');if(!mdl)return;m.className='msg';m.textContent='starting download\u2026';
 await ollamaJob(await post('/api/ollama/pull',{model:mdl}),'Downloaded '+mdl+'.','Download failed','lo_dl')}
async function aiOllamaInstall(){const m=$('tm_local');m.className='msg';m.textContent='starting install\u2026';
 await ollamaJob(await post('/api/ollama/install',{}),'Ollama installed - now press Start Ollama, then Download model.','Install failed','lo_in')}
function renderPrio(){const ol=$('prio');ol.innerHTML=AI.priority.map((s,i)=>{const x=AI.slots.find(o=>o.slot==s);
 return `<li draggable=true data-i=${i}><span class=n>${i+1}</span><span class=nm>${lbl(s)}</span><span class="pill ${pcls(x.state)}">${x.state.replace('_',' ')}</span><span class=rs>${esc(x.reason)}</span>
 <button onclick="prioMove(${i},-1)" ${i==0?'disabled':''}>\u25b2</button><button onclick="prioMove(${i},1)" ${i==AI.priority.length-1?'disabled':''}>\u25bc</button></li>`}).join('');
 let from=-1;ol.querySelectorAll('li').forEach(li=>{li.ondragstart=e=>{from=+li.dataset.i;e.dataTransfer.effectAllowed='move'};li.ondragover=e=>{e.preventDefault();li.classList.add('over')};
  li.ondragleave=()=>li.classList.remove('over');li.ondrop=e=>{e.preventDefault();li.classList.remove('over');const to=+li.dataset.i;if(from<0||from==to)return;
   const a=[...AI.priority];const [m]=a.splice(from,1);a.splice(to,0,m);savePrio(a)}})}
async function savePrio(a){await post('/api/ai/settings',{priority:a});aiLoad()}
function prioMove(i,d){const a=[...AI.priority];const [m]=a.splice(i,1);a.splice(i+d,0,m);savePrio(a)}
function ocPanel(R_){const oc=AI.openclipper,O_=AI.settings.openclipper;
 const gpu=oc.gpu_provider?`<span class=ok>GPU: ${esc(oc.gpu_provider)}</span>`:(oc.installed?'<span class=warn>CPU only (no DirectML/CUDA provider active)</span>':'-');
 const why=oc.available?'<div class="msg ok">OpenClipper engine is installed and ready.</div>':`<div class=small style="margin-top:6px"><b class=warn>OpenClipper not ready</b> (the Static Crop is used instead):</div><ul class=why>${oc.reasons.map(r=>`<li>${esc(r)}</li>`).join('')}</ul>`;
 return `<details ${R_!='static'&&!oc.available?'open':''} style="margin-top:10px"><summary>OpenClipper setup &amp; status</summary>${why}
 <div class=kv style="margin-top:6px">${kv('Installed',oc.installed?'<span class=ok>yes</span> '+esc(oc.installed_at||''):'<span class=warn>no</span>')}${kv('Inference',gpu+(oc.onnxruntime?' \u00b7 onnxruntime '+esc(oc.onnxruntime):''))}${kv('Planner runtime',esc(oc.runtime||'not found'))}${kv('Upstream',`GrepCut/OpenClipper @ ${esc(oc.upstream_commit)} \u00b7 ${esc(oc.license)}`)}</div>
 <div class=small style="margin-top:8px"><b>What this engine does:</b> OpenClipper\u2019s own YOLOX detector + AutoFlip camera planner (GPU via DirectML) keep the main subject \u2014 a person or a car/truck/bike/boat/plane \u2014 inside the 9:16 crop, with smooth tracking and shot-cut handling. Transcription, highlight ranking, captions, effects, facecam layouts and CapCut export are the SONIVERSE ones (OpenClipper has no headless clip picker or captioner). Faces/pose are not used. Everything runs in its own environment (<code>engines/openclipper/.venv</code>), offline after install.</div>
 <div class=g2 style="margin-top:8px"><div><label>Inference device</label><select id=oc_dev onchange="aiOC()">${['auto','dml','cuda','cpu'].map(v=>`<option value=${v} ${O_.device==v?'selected':''}>${{auto:'Auto (DirectML GPU \u2192 CUDA \u2192 CPU)',dml:'DirectML (Windows: any DX12 GPU)',cuda:'CUDA (needs onnxruntime-gpu)',cpu:'CPU'}[v]}</option>`).join('')}</select></div>
 <div><div class=chk style="margin-top:22px"><input type=checkbox id=oc_hero ${O_.hero_lock?'checked':''} onchange="aiOC()"><span>Lock onto the main character/vehicle (keeps it in frame even when other things move)</span></div></div></div>
 <div class=row style="margin-top:8px">${AI.tools&&!AI.tools.ffmpeg?'<button class=s id=oc_ff onclick="aiFfmpegInstall()">Install FFmpeg (required)</button>':''}<button class=s onclick="aiOCSetup('install')">${oc.installed?'Reinstall / repair':'Install OpenClipper engine'}</button><button class=s onclick="aiOCSetup('uninstall')" ${oc.installed?'':'disabled'}>Remove</button><button class=s onclick=aiLoad()>Re-check</button></div>
 <div class=small style="margin-top:6px">Install downloads ~55 MB (numpy, onnxruntime-directml and the YOLOX model from the pinned upstream commit, sha256-verified). Progress shows under Activity (Studio tab).</div><div class=msg id=oc_msg></div></details>`}
function renderEngine(){const H_=AI.settings.highlight_engine,R_=AI.settings.reframe_engine,sc=AI.supoclip,oc=AI.openclipper,S_=AI.settings.supoclip;
 const opt=(grp,fn,cur,v,t,d)=>`<label class=chk style="align-items:flex-start"><input type=radio name=${grp} value=${v} ${cur==v?'checked':''} onchange="${fn}('${v}')"><span><b>${t}</b><br><span class=small>${d}</span></span></label>`;
 const why=sc.available?'<div class="msg ok">SupoClip is available.</div>':`<div class=small style="margin-top:6px"><b class=warn>SupoClip unavailable</b> (Local AI is used instead):</div><ul class=why>${sc.reasons.map(r=>`<li>${esc(r)}</li>`).join('')}</ul>`;
 const hlEff=H_=='local'?'Local AI':H_=='supoclip'?(sc.available?'SupoClip':'Local AI (SupoClip unavailable)'):((sc.available&&S_.local_whisper_configured)?'SupoClip':'Local AI'),
  rfEff=R_=='static'?'Static Crop':(oc.available?'OpenClipper'+(oc.gpu_provider?' ('+oc.gpu_provider+')':' (CPU)'):'Static Crop (OpenClipper not ready)');
 const mig=AI.settings.migrated_from?`<div class="msg ok" style="margin:8px 0">Your previous single engine setting <b>${esc(AI.settings.migrated_from)}</b> was converted to <b>${esc(HLN[H_])}</b> highlights + <b>${esc(RFN[R_])}</b> reframing. The original file is kept as <code>ai_settings.pre-two-stage.json</code>.</div>`:'';
 $('engNote').innerHTML=mig+`<div class=card><b>Right now this runs as:</b> ${hlEff} highlights \u2192 ${rfEff} reframing${(hlEff=='SupoClip'&&rfEff.startsWith('OpenClipper'))?' <span class=small>(SupoClip chooses the moments; clips are rendered locally from your recording)</span>':''}${(hlEff=='SupoClip'&&rfEff.startsWith('Static'))?' <span class=small>(SupoClip\u2019s own finished vertical MP4s; no facecam/mic, no tracking)</span>':''}</div>`;
 $('engCard').innerHTML=opt('hl','aiHL',H_==='local'?(AI.settings.providers.local.use_ollama?'smart':'fast'):H_,'fast','Fast - local scoring (default)','Whisper on your RTX GPU transcribes; highlights are scored from motion, game sound, your voice and keywords. Same result every time, fastest, nothing leaves this PC.')+
 opt('hl','aiHL',H_==='local'?(AI.settings.providers.local.use_ollama?'smart':'fast'):H_,'smart','Smart - local scoring + Ollama','As Fast, then your local Ollama model reads the transcript and re-orders the moments (better for funny / commentary / story). Needs Ollama running; if it is not, the run says so and uses Fast.')+
 opt('hl','aiHL',H_,'supoclip','SupoClip (optional)','Separate open-source project you run yourself in Docker. It chooses the moments. With OpenClipper reframing its timestamps are rendered locally (facecam/mic, captions and effects stay SONIVERSE); with Static Crop you get SupoClip\u2019s own finished MP4s (facecam/mic ignored).')+
 opt('hl','aiHL',H_,'auto','Auto','SupoClip only when it is fully available, transcribes locally (no audio leaves the PC) and - if the output would be SupoClip\u2019s own MP4s - the job needs no facecam/mic; otherwise Local AI.')+
 `<details ${H_!='local'?'open':''} style="margin-top:10px"><summary>SupoClip setup &amp; status</summary><div class=small style="margin:6px 0"><b>SupoClip is optional - Local AI works with no setup.</b> To use it: <b>1</b> tick the licence box and press <b>Install SupoClip</b> (git clone + a generated .env, no keys written) &middot; <b>2</b> start Docker Desktop and press <b>Start SupoClip</b> (first start builds images - slow) &middot; <b>3</b> press <b>Open SupoClip</b>, create your account, then Settings &gt; Agents &amp; API &gt; create a key and paste it into <i>SupoClip API key</i> below. SupoClip does not let this app create that key for you.</div>${why}
 <div class=small style="margin-top:8px">Licence: <b>SupoClip Noncommercial Source License v1.1</b> (Shiori LLC). Free for noncommercial use and for an <i>individual creator</i> using their own self-hosted copy for their own channels. Companies, agencies, teams, client work and redistribution need written permission (support@supoclip.com). No SupoClip code is copied into or bundled with this app - you clone and run it yourself.</div>
 <div class=chk><input type=checkbox id=sc_lic ${S_.ack_license?'checked':''} onchange="aiSupo()"><span>I am a single creator using my own copy for my own channels (or noncommercial use)</span></div>
 <label>SupoClip folder (cloned outside this app)</label><input id=sc_path value="${esc(S_.path)}" onchange="aiSupo()" placeholder="C:\\Tools\\supoclip">
 <label>Backend URL (localhost only)</label><input id=sc_url value="${esc(S_.url)}" onchange="aiSupo()">
 <label>SupoClip LLM (picks the moments)</label><select id=sc_llm onchange="aiSupo()"><option value=env_file ${S_.llm_source!='gemini_free'?'selected':''}>whatever SupoClip's own .env says (its default needs an OpenRouter key)</option><option value=gemini_free ${S_.llm_source=='gemini_free'?'selected':''}>My Gemini key - Paid if switched on below, else Free, whichever currently works (given to Docker only when you press Start, never written to a file)</option></select>
 <div class=small style="margin-top:4px">SupoClip's own code only understands Gemini / OpenAI / Anthropic / OpenRouter / local Ollama as its LLM - not Groq - so that is as far as this fallback can reach.</div>
 <div class=chk><input type=checkbox id=sc_lw ${S_.local_whisper_configured?'checked':''} onchange="aiSupo()"><span>My SupoClip is configured for local Whisper (no AssemblyAI)</span></div>
 <div class=chk><input type=checkbox id=sc_ca ${S_.ack_cloud_audio?'checked':''} onchange="aiSupo()"><span>Allow SupoClip to upload this audio to AssemblyAI (cloud)</span></div>
 <div class=g2><div><b>AssemblyAI key</b> <span class=small>(optional - not needed with local Whisper)</span>${keyRow(AI.keyEnv.assemblyai)}</div><div><b>SupoClip API key</b>${keyRow(AI.keyEnv.supoclip)}</div></div>
 <div class=row style="margin-top:8px"><button class=s id=sc_in onclick="aiSupoInstall()">${sc.installed?'Reinstall SupoClip':'Install SupoClip'}</button>${sc.docker?(sc.docker_running?'':'<button class=s id=sc_dd onclick="aiDockerStart()">Start Docker Desktop</button>'):'<button class=s id=sc_dk onclick="aiDockerInstall()">Install Docker Desktop</button>'}<span class=small style="align-self:center;margin-right:6px">Status: <b class="${sc.state==='running'?'ok':'warn'}">${sc.state==='running'?'running':sc.state==='partial'?'worker stopped':'stopped'}</b></span>${sc.state!=='running'?`<button class=s onclick="aiCompose('up')">Start SupoClip</button>`:''}${sc.state!=='stopped'?`<button class=s onclick="aiCompose('down')">Stop SupoClip</button>`:''}<button class=s onclick="aiSupoOpen()">Open SupoClip</button><button class=s onclick=aiLoad()>Re-check</button></div><div class=msg id=sc_msg></div></details>`;
 $('rfCard').innerHTML=opt('rf','aiRF',R_,'openclipper','OpenClipper (AI Smart Reframing)','OpenClipper\u2019s subject tracking + AutoFlip camera keep the main person or vehicle in the 9:16 crop, on your GPU. Works with Local AI or SupoClip highlights; keeps SONIVERSE presets, captions, effects, facecam layouts and CapCut export.')+
 opt('rf','aiRF',R_,'static','Static Crop','The plain SONIVERSE crop (coarse horizontal motion following only). No subject detection. Fastest.')+
 opt('rf','aiRF',R_,'auto','Auto','OpenClipper when it is installed and ready, otherwise the Static Crop.')+
 `<div class=small style="margin-top:8px"><b>Tracking status:</b> every clip card shows whether OpenClipper really detected a person/vehicle and moved the crop with it, or fell back to the static crop (and why). It reports detection coverage only - <b class=warn>it cannot tell which person or car is the player; that is NOT verified on real GTA gameplay.</b></div>`+ocPanel(R_);
 for(const e of [AI.keyEnv.assemblyai,AI.keyEnv.supoclip])keyPaint(e)}
function keyPaint(env){const k=$('key_'+env);if(!k)return;
 if(isMulti(env)){const L=(AI.keyList&&AI.keyList[env])||[];k.disabled=false;k.placeholder=L.length?'paste another key':'paste a key (Enter or Add key)';
  $('kl_'+env).innerHTML=L.length?L.map((c,i)=>`<span class="kc ${c.state}" title="${esc(c.reason)}"><b>#${i+1}</b> \u2022\u2022\u2022\u2022${esc(c.tail)} <i>${c.state}</i><a onclick="keyDel('${env}',${i})" title="remove this key">\u00d7</a></span>`).join(''):'<span class=small>no key saved</span>';return}
 if(k.dataset.edit)return;const has=AI.keys[env];k.value='';k.disabled=!!has;k.type='password';k.placeholder=has?'\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022 stored (encrypted)':'paste key, then Save'}
function renderProc(){foldLoad();const g=AI.gpu,S_=AI.settings,sp=S_.spend,u=AI.ui;
 $('procCard').innerHTML=`<div class=g2><div><b>Engine &amp; hardware</b><div class=kv style="margin-top:6px">${kv('Current engine',AI.current.engine?`${AI.current.engine}${AI.current.ai?' \u00b7 AI: '+esc(AI.current.ai):''}`:'idle (no job yet)')}
  ${kv('Computer',g.hardware?`${esc(g.hardware.os)} \u00b7 ${g.hardware.cores} cores \u00b7 ${g.hardware.ram_gb} GB RAM`:'-')}${kv('GPU',g.gpu?`${esc(g.gpu.name)} \u00b7 ${g.gpu.util_pct}% \u00b7 ${g.gpu.vram_used_mb}/${g.gpu.vram_total_mb} MB`:esc((g.hardware&&g.hardware.gpus.join(', '))||'none detected - everything runs on the CPU (slower)'))}
  ${kv('Video encoder',g.encoder=='x264'?'<span class=warn>CPU (x264) - no hardware encoder found</span>':'<span class=ok>'+esc(ENCN[g.encoder]||g.encoder)+' (hardware)</span>')}${kv('Whisper',g.whisper?`${esc(g.whisper.model)} on ${g.whisper.device.toUpperCase()}${g.whisper.auto?' (automatic)':''}`:'-')}</div>
  <label>Transcription</label><select id=tp><option value=local>Local Whisper (free, private; uses your GPU when there is one)</option><option value=groq>Groq Whisper (UPLOADS AUDIO; needs Groq key)</option><option value=none>Skip (no captions)</option></select>
  <label>Local Whisper model</label><select id=wm onchange="wmChange()"></select><input id=wm_c style="display:none;margin-top:6px" placeholder="model name, Hugging Face id (Systran/faster-whisper-large-v3) or folder path"><div class=small id=wm_h style="margin-top:4px"></div><div class=row style="margin-top:6px"><button class=s id=wm_dl onclick="wmFetch()">Download / verify model</button></div><div class=msg id=wm_m></div><div class=chk><input type=checkbox id=ov><span>Local Ollama vision model also looks at 3 frames/clip</span></div>
  <button class=s style="margin-top:8px" onclick=saveProc()>Save</button></div>
  <div><b>Cloud analysis &amp; spend limits</b>
  <div class=chk><input type=checkbox id=pf ${S_.send_frames?'checked':''} onchange="aiGem()"><span>Gemini also receives keyframes (small JPEGs) - not full video</span></div>
  <label>Frames per candidate (0\u20136)</label><input id=pn type=number min=0 max=6 value=${S_.gemini_frames} onchange="aiGem()">
  <div class=row><div><label>Per-run limit (Rs)</label><input id=sp1 type=number min=0 value=${sp.per_run_inr} onchange="aiGem()"></div><div><label>Monthly limit (Rs)</label><input id=sp2 type=number min=0 value=${sp.monthly_inr} onchange="aiGem()"></div></div>
  <div class=row><div><label>Rs per USD</label><input id=sp3 type=number min=1 value=${sp.inr_per_usd} onchange="aiGem()"></div><div><label>Est. $/1M tokens in / out</label><div class=row><input id=sp4 type=number step=0.01 value=${sp.est_usd_per_mtok_in} onchange="aiGem()"><input id=sp5 type=number step=0.01 value=${sp.est_usd_per_mtok_out} onchange="aiGem()"></div></div></div>
  <div class=small style="margin-top:6px">Estimated cost of one run on Gemini Paid (6 candidates): <b>~Rs ${AI.spend.est_run_inr.toFixed(2)}</b>. Prices are editable ESTIMATES, not Google\u2019s live price list; real usage tokens from each response are used after the call. This month on Gemini Paid: <b>Rs ${AI.spend.month_inr.toFixed(2)}</b>.</div></div></div>
  <table class=t style="margin-top:12px"><tr><th>Provider</th><th>State</th><th>Today</th><th>Quota / rate-limit status</th></tr>${AI.slots.map(x=>{const L=x.limits||{};return `<tr><td>${lbl(x.slot)}</td><td>${x.state.replace('_',' ')}</td><td>${x.slot=='local'?'-':x.today_req+' req'}</td><td>${esc(x.slot=='gemini_free'?`cap ${S_.providers.gemini_free.daily_request_cap}/day`:'')} ${L['remaining-requests']!==undefined?`${L['remaining-requests']}/${L['limit-requests']} req/day, ${L['remaining-tokens']}/${L['limit-tokens']} tok/min`:''} ${x.cooldown_s?`cooling down ${x.cooldown_s}s`:''}</td></tr>`}).join('')}</table>`;
 {const W=AI.gpu.whisper||{},cur=u.whisper_model,known=AI.whisperModels.includes(cur);
 $('wm').innerHTML=AI.whisperModels.map(m=>`<option value="${m}">${m=='auto'?'Automatic - best for this PC'+(W.auto_model?' ('+W.auto_model+')':''):m}</option>`).join('')+'<option value="__custom__">Custom model name / path\u2026</option>';
 $('wm').value=known?cur:'__custom__';$('wm_c').value=known?'':cur;wmChange()};$('tp').value=u.transcription;$('ov').checked=u.ollama_vision}
async function aiLoad(){AI=await (await fetch('/api/ai/state')).json();
 if(E){const st=await E.keyStatus();for(const k in st)AI.keys[k]=st[k]}
 renderProviders();renderPrio();renderEngine();renderProc();hdr2()}
function hdr2(){renderSetup()}
const sbtn=(id,t,fn)=>`<button class=s id="${id}" onclick="${fn}">${t}</button>`;
async function suJob(url,body,ok,fail,btn,mid){const m=$(mid);m.className='msg';m.textContent='starting\u2026';await ollamaJob(await post(url,body),ok,fail,btn,mid)}
let FOLD=null;
const FOLDM={input:['Import folder','Your recordings are read from here (and listed in the Studio tab).'],output:['Export folder','Finished clips, previews and CapCut bundles are written here.'],
 cache:['Cache folder','Proxies, audio and transcripts. Can be large (it makes re-runs fast) and is safe to delete.'],install:['Installation folder','Where the app itself lives. Move the whole folder to relocate it.']};
async function foldLoad(){try{FOLD=await (await fetch('/api/folders')).json()}catch(e){return}renderFolders()}
function renderFolders(){const el=$('foldCard');if(!el||!FOLD)return;
 el.innerHTML=['input','output','cache','install'].map(k=>{const f=FOLD[k],m=FOLDM[k],ro=k=='install';
  return `<div class=frow><div><b>${m[0]}</b><div class=small>${m[1]}</div></div>
   <div class=row><input id=fp_${k} value="${esc(f.path)}" ${ro?'readonly':''} spellcheck=false>${ro?'':`<button class=s style="flex:0 0 auto" onclick="foldBrowse('${k}')">Browse\u2026</button><button class=s style="flex:0 0 auto" onclick="foldApply('${k}')">Apply</button>`}<button class=s style="flex:0 0 auto" onclick="foldOpen('${k}')">Open</button></div>
   <div class=small>${f.free_gb!=null?f.free_gb+' GB free on this drive':''}${f.exists?'':' \u00b7 <span class=warn>folder does not exist yet (it is created when you press Apply)</span>'}</div><div class=msg id=fm_${k}></div></div>`}).join('')}
async function foldApply(k){const m=$('fm_'+k),r=await post('/api/folders',{which:k,path:$('fp_'+k).value});
 if(r.error){m.className='msg warn';m.textContent=r.error;return}FOLD=r.folders;renderFolders();const n=$('fm_'+k);n.className='msg ok';n.textContent='Saved. New work uses this folder.';if(typeof state=='function')state()}
async function foldBrowse(k){if(E&&E.pickFolder){const p=await E.pickFolder();if(p){$('fp_'+k).value=p;foldApply(k)}}else{const m=$('fm_'+k);m.className='msg';m.textContent='Type the full folder path above and press Apply (the desktop app has a Browse dialog).'}}
async function foldOpen(k){await post('/api/folders/open',{which:k})}
let suOl=null;
async function suAll(){const m=$('su_all_m');m.className='msg';m.textContent='starting\u2026';const c=$('su_olc');
 await ollamaJob(await post('/api/setup/all',{ollama:!!(c&&c.checked&&!c.disabled)}),'Setup finished. Check the list below for anything that still needs attention.','Setup did not finish','su_all','su_all_m')}
async function suPull(){const mdl=AI.settings.providers.local.ollama_model;await suJob('/api/ollama/pull',{model:mdl},'Downloaded '+mdl+'.','Download failed','su_ol','su_ol_m')}
async function suMsg(r,mid){await aiLoad();const m=$(mid);if(m){m.textContent=r.message||r.error||'';m.className='msg '+(r.ok?'ok':'warn')}}
async function suOllamaStart(){$('su_ol_m').textContent='starting Ollama\u2026';await suMsg(await post('/api/ollama/start',{}),'su_ol_m')}
async function suOllamaStop(){$('su_ol_m').textContent='stopping Ollama\u2026';await suMsg(await post('/api/ollama/stop',{}),'su_ol_m')}
async function suDockerStart(){$('su_sc_m').textContent='starting Docker Desktop\u2026';await suMsg(await post('/api/docker/start',{}),'su_sc_m')}
async function suOpen(){const r=await post('/api/supoclip/open',{});if(r.url)toast('Opened '+r.url,'good');else toast(r.error||'Could not open SupoClip','bad')}
async function goPickModel(){tab('settings');setPane('prov');await aiLoad();const el=$('lo_om');if(el){el.focus();el.select();el.scrollIntoView({behavior:'smooth',block:'center'})}}
function suRow(st,t,tag,d,act,mid){const ic={ok:'\u2713',warn:'!',bad:'\u00d7',opt:'\u2013'}[st],w={ok:'OK',warn:'Needs attention',bad:'Missing',opt:'Optional'}[st];
 return `<div class="srow st-${st}"><span class=sic aria-hidden=true>${ic}</span><div class=sbody><div><b>${t}</b><span class=stag>${tag}</span><span class=sr> ${w}</span></div><div class=small>${d}</div><div class=msg id="${mid}"></div></div><div class=sact>${act||''}</div></div>`}
function renderSetup(){if(!AI||!$('setupList'))return;
 const O=AI.ollama,oc=AI.openclipper,sc=AI.supoclip,g=AI.gpu,T=AI.tools||{},cur=AI.settings.providers.local.ollama_model,have=(O.downloaded||[]).find(m=>m.name==cur),R=[];
 R.push(['ff',T.ffmpeg?'ok':'bad',suRow(T.ffmpeg?'ok':'bad','FFmpeg','Required',T.ffmpeg?'Found. Clips can be cut and exported.':'Not found. Clips cannot be cut or exported without it.',T.ffmpeg?'':sbtn('su_ff','Install FFmpeg',"suJob('/api/tools/ffmpeg',{},'FFmpeg installed. If a step still says ffmpeg not found, close and reopen the app once.','FFmpeg install failed','su_ff','su_ff_m')"),'su_ff_m')]);
 const nv=g.encoder=='nvenc';
 R.push(['enc','ok',suRow(nv?'ok':'opt','Video encoder','Automatic',nv?esc((g.gpu&&g.gpu.name)||'NVIDIA GPU')+' is encoding with NVENC.':(g.gpu?esc(g.gpu.name)+' was found, but hardware encoding is not active. Exports use the CPU encoder and take longer.':'No NVIDIA GPU found. Exports use the CPU encoder and take longer.'),'','su_enc_m')]);
 let st,d,act='';
 if(!O.up&&!O.installed){st='opt';d='Not installed. Local AI still scores clips without it; Ollama adds a vision model that looks at frames.';act=sbtn('su_ol','Install Ollama',"suJob('/api/ollama/install',{},'Ollama installed. Now press Start Ollama.','Install failed','su_ol','su_ol_m')")}
 else if(!O.up){st='warn';d='Installed, but not running.';act=sbtn('su_ol','Start Ollama','suOllamaStart()')}
 else if(/^qwen3-vl/i.test(cur||'')&&O.old){st='warn';d=`Ollama ${esc(O.version)} is too old for ${esc(cur)} (needs ${esc(O.qwen3vl_min)} or newer). Update it with: ${O.mac?'brew upgrade ollama':'winget upgrade Ollama.Ollama'}`}
 else if(!have){st='warn';d=`Running. The selected model ${esc(cur)} is not downloaded yet.`;act=sbtn('su_ol','Download model','suPull()')+sbtn('su_olc','Change model','goPickModel()')}
 else{st='ok';d=`Running. ${esc(cur)} is ready${have.vision===false?' (text only, no frame analysis)':''}.`;act=sbtn('su_ol','Stop Ollama','suOllamaStop()')+sbtn('su_olc','Change model','goPickModel()')}
 R.push(['ol',st,suRow(st,'Local AI model (Ollama)','Optional',d,act,'su_ol_m')]);
 let os_,od,oa='';
 if(oc.available){os_='ok';od=`Ready. Tracking runs on ${esc(oc.gpu_provider||'the CPU')}.`}
 else if(!T.ffmpeg){os_='warn';od='Needs FFmpeg first.'}
 else{os_='warn';od=oc.installed?esc((oc.reasons||[])[0]||'Installed, but not ready.'):'Not installed. Until it is, vertical crops use the plain Static Crop.';oa=sbtn('su_oc',oc.installed?'Reinstall OpenClipper':'Install OpenClipper',"suJob('/api/openclipper/setup',{action:'install'},'OpenClipper installed.','Install failed','su_oc','su_oc_m')")}
 R.push(['oc',os_,suRow(os_,'Smart reframing (OpenClipper)','Recommended',od,oa,'su_oc_m')]);
 let ss,sd,sa='';
 if(sc.available){ss='ok';sd='Running and ready.'}
 else{ss='opt';sd=(!sc.docker?'Docker Desktop is not installed.':!sc.docker_running?'Docker Desktop is installed but not running.':sc.installed?'SupoClip is installed and Docker is running - a few things are still needed before it can be used:':'Docker is running.')+' Local AI works fine without SupoClip.'+((sc.reasons||[]).length?`<details><summary>What is missing</summary><ul>${sc.reasons.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></details>`:'');
  sa=(!sc.docker?sbtn('su_dk','Install Docker Desktop',"suJob('/api/docker/install',{},'Docker Desktop installed. Open it once from Applications/Launchpad (Mac) or restart Windows if it asked, then start Docker Desktop.','Docker install failed','su_dk','su_sc_m')"):(!sc.docker_running?sbtn('su_dd','Start Docker Desktop','suDockerStart()'):''))+sbtn('su_in',sc.installed?'Reinstall SupoClip':'Install SupoClip',"suJob('/api/supoclip/install',{},'SupoClip prepared. Start Docker, then open SupoClip to create your API key.','Install failed','su_in','su_sc_m')")+(sc.backend_up?sbtn('su_op','Open SupoClip','suOpen()'):'')}
 R.push(['sc',ss,suRow(ss,'SupoClip highlights (Docker)','Optional',sd,sa,'su_sc_m')]);
 const names=Object.entries(AI.keyEnv).filter(([k,e])=>AI.keys[e]).map(([k])=>lbl(k));
 R.push(['key',names.length?'ok':'opt',suRow(names.length?'ok':'opt','Cloud AI keys','Optional',names.length?`Saved: ${esc(names.join(', '))}. A provider still has to be switched on in Settings.`:'No keys saved. Local AI is used for everything.',`<button class=s onclick="tab('settings');setPane('prov')">Open AI providers</button>`,'su_key_m')]);
const rec=(g.recommend||{}),ro=rec.ollama,wh=g.whisper||{},todo=[];
 if(!T.ffmpeg)todo.push('FFmpeg');
 if(!wh.ready)todo.push(`Whisper model <b>${esc(wh.model||'')}</b> (speech to text)`);
 if(!(oc.installed||oc.available))todo.push('Smart reframing engine (OpenClipper, ~55 MB)');
 const olHave=ro&&(O.downloaded||[]).some(m=>m.name==ro.model),olTodo=ro&&!olHave;
 if(suOl===null)suOl=!!olTodo;
 const olLine=ro?`<label class=chk style="margin:8px 0 0"><input type=checkbox id=su_olc ${suOl?'checked':''} ${olHave?'disabled':''} onchange="suOl=this.checked"><span>Local AI vision model for this computer: <b>${esc(ro.model)}</b> (~${ro.size_gb} GB${olHave?' - already downloaded':''}) <span class=small>${esc(ro.reason)}. Installs Ollama too if it is missing. Optional - ranking works without it.</span></span></label>`:`<div class=small style="margin-top:8px">${esc(rec.ollama_note||'')}</div>`;
 const allDone=!todo.length&&!(ro&&!olHave&&suOl);
 const one=`<div class=srow style="grid-template-columns:30px minmax(0,1fr) auto"><div></div><div><b>${allDone?'Everything recommended for this computer is installed.':'One-click setup for this computer'}</b>
  <div class=small style="margin-top:4px">${g.hardware?esc(g.hardware.summary):''}</div>
  ${todo.length?`<ul class=why style="color:var(--tx)">${todo.map(x=>`<li>${x}</li>`).join('')}</ul>`:''}${olLine}<div class=msg id=su_all_m></div></div>
  <div>${allDone&&!(ro&&!olHave)?'':'<button class=pri id=su_all onclick="suAll()">Install everything recommended</button>'}</div></div>`;
 $('setupList').innerHTML=one+R.map(r=>r[2]).join('');
 const need=R.filter(r=>r[0]!='enc'&&(r[1]=='bad'||r[1]=='warn')).length,bad=!T.ffmpeg;
 const sm=$('suSum');sm.className='sum '+(bad?'bad':'ok');
 sm.innerHTML=bad?'<b>FFmpeg is missing.</b> <span class=small>Install it below to start clipping.</span>':`<b>Ready to clip.</b> <span class=small>${need?need+' recommended '+(need>1?'fixes are':'fix is')+' waiting below.':'Everything checked is in place.'}</span>`;
 const bd=$('setupBadge');bd.textContent=need;bd.classList.toggle('hide',!need);
 const bn=$('setupBanner');if(bn)bn.classList.toggle('hide',!bad)}
const aiPost=async(b)=>{const r=await post('/api/ai/settings',b);if(r.error)alert(r.error);return r};
async function aiEnable(s,on){if(s=='gemini_paid'&&on&&!confirm(`Enable Gemini Paid?\nCalls on this key can be billed. They stay inside your limits: Rs ${AI.settings.spend.per_run_inr} per run, Rs ${AI.settings.spend.monthly_inr} per month.`)){$('en_'+s).checked=false;return}
 await aiPost({providers:{[s]:{enabled:on}}});aiLoad()}
async function aiModel(s,m){await aiPost({providers:{[s]:{model:m}}})}
let addSel='';
function renderAddProv(){const el=$('addProv');if(!el)return;const C=AI.catalog||[];
 if(!C.length){el.innerHTML='<div class=small>Every provider in the list has been added.</div>';return}
 if(!C.some(c=>c.id==addSel))addSel=C[0].id;const c=C.find(x=>x.id==addSel),grp=(t,f)=>{const l=C.filter(f);return l.length?`<optgroup label="${t}">${l.map(x=>`<option value="${x.id}" ${x.id==addSel?'selected':''}>${esc(x.label)}</option>`).join('')}</optgroup>`:''};
 const keep=['ap_name','ap_url'].map(i=>$(i)?$(i).value:'');
 el.innerHTML=`<div class=h><h3>Add another provider</h3></div><div class=small style="margin:6px 0">Choose one and a card with its own key list, model and switch appears above. They all only ever receive transcript <b>text</b>, and nothing is sent until you add a key and switch the card on.</div>
  <label>Provider</label><select id=ap_sel onchange="addSel=this.value;renderAddProv()">${grp('Has a free tier',x=>x.free&&x.id!='custom')}${grp('Pay as you go',x=>!x.free&&x.id!='custom')}${grp('Your own server',x=>x.id=='custom')}</select>
  <div class=small style="margin-top:6px">${esc(c.note)}${c.free&&c.id!='custom'?' <b>Free tier available</b> (limits change - check their page).':''}</div>
  ${c.id=='custom'?`<label>Name</label><input id=ap_name placeholder="My server" value="${esc(keep[0])}"><label>Base URL</label><input id=ap_url placeholder="https://host/v1   or   http://127.0.0.1:1234/v1" value="${esc(keep[1])}">`:''}
  <div class=lrow>${c.key_url?kbtn(c.key_url,'Get an API key'):''}${c.doc_url?kbtn(c.doc_url,'Limits & pricing'):''}</div>
  <div class=row style="margin-top:8px"><button class=s onclick=addProv()>Add provider</button></div><div class=msg id=ap_m></div>`}
async function addProv(){const m=$('ap_m'),b={catalog:addSel};if(addSel=='custom'){b.label=$('ap_name').value;b.base_url=$('ap_url').value}
 const r=await post('/api/ai/provider/add',b);if(r.error){m.className='msg warn';m.textContent=r.error;return}
 await aiLoad();const k=$('km_'+r.env);if(k){k.className='msg ok';k.textContent='Added. Paste your API key above, then press Test connection.'}
 const c=$('pc_'+r.slot);if(c)c.scrollIntoView({behavior:'smooth',block:'center'})}
async function provDel(s){if(!confirm('Remove this provider and its saved keys?'))return;const env=AI.keyEnv[s],r=await post('/api/ai/provider/remove',{slot:s});
 if(r.error){alert(r.error);return}if(E&&env)await E.removeKey(env);await aiLoad()}
async function aiCap(s,v){await aiPost({providers:{[s]:{daily_request_cap:+v}}});aiLoad()}
async function aiLocal(){await aiPost({providers:{local:{use_ollama:$('lo_ol').checked,ollama_model:$('lo_om').value}}});aiLoad()}
async function aiHL(v){if(v==='fast'||v==='smart'){await aiPost({highlight_engine:'local',providers:{local:{use_ollama:v==='smart'}}})}else{await aiPost({highlight_engine:v})}aiLoad()}
async function aiRF(v){await aiPost({reframe_engine:v});aiLoad()}
async function aiSupo(){await aiPost({supoclip:{ack_license:$('sc_lic').checked,path:$('sc_path').value,url:$('sc_url').value,local_whisper_configured:$('sc_lw').checked,llm_source:$('sc_llm').value,ack_cloud_audio:$('sc_ca').checked}});aiLoad()}
async function aiSupoInstall(){const m=$('sc_msg');m.className='msg';m.textContent='starting install\u2026';
 await ollamaJob(await post('/api/supoclip/install',{}),'SupoClip prepared. Next: start Docker Desktop, press Start SupoClip, then Open SupoClip to create your API key.','Install failed','sc_in','sc_msg')}
async function aiDockerInstall(){const m=$('sc_msg');m.className='msg';m.textContent='starting Docker Desktop install\u2026 approve the Windows admin prompt';
 await ollamaJob(await post('/api/docker/install',{}),'Docker Desktop installed. Open it once from Applications/Launchpad (Mac) or restart Windows if it asked, then wait for "Engine running" before pressing Start SupoClip.','Docker install failed','sc_dk','sc_msg')}
async function aiDockerStart(){const r=await post('/api/docker/start',{});$('sc_msg').className='msg '+(r.ok?'ok':'warn');$('sc_msg').textContent=r.message||r.error||''}
async function aiFfmpegInstall(){const m=$('oc_msg');m.className='msg';m.textContent='starting FFmpeg install\u2026';
 await ollamaJob(await post('/api/tools/ffmpeg',{}),'FFmpeg installed. If a step still says "ffmpeg not found", close and reopen the app once.','FFmpeg install failed','oc_ff','oc_msg')}
async function aiSupoOpen(){const r=await post('/api/supoclip/open',{});$('sc_msg').className='msg';$('sc_msg').textContent=r.url?'Opened '+r.url:(r.error||'')}
async function aiOC(){await aiPost({openclipper:{device:$('oc_dev').value,hero_lock:$('oc_hero').checked}});aiLoad()}
async function aiOCSetup(a){if(a=='uninstall'&&!confirm('Remove the OpenClipper environment and models? (Your clips and settings are untouched.)'))return;
 const r=await post('/api/openclipper/setup',{action:a});if(r.error)alert(r.error);else{alert('Started - progress under Activity (Studio tab).');state()}}
async function aiGem(){await aiPost({send_frames:$('pf').checked,gemini_frames:+$('pn').value,spend:{per_run_inr:+$('sp1').value,monthly_inr:+$('sp2').value,inr_per_usd:+$('sp3').value,est_usd_per_mtok_in:+$('sp4').value,est_usd_per_mtok_out:+$('sp5').value}});aiLoad()}
async function aiTest(s){const m=$('tm_'+s);m.textContent='testing\u2026';m.className='msg';const r=await post('/api/ai/test',{slot:s});m.textContent=r.message||r.error;m.className='msg '+(r.ok?'ok':'warn');aiLoad()}
async function aiReset(s){await post('/api/ai/reset',{slot:s});aiLoad()}
async function aiCompose(a){const r=await post('/api/supoclip/compose',{action:a});if(r.error)alert(r.error);else{alert('Started - progress under Activity (Studio tab).');state()}}
const ENCN={nvenc:'NVIDIA NVENC',videotoolbox:'Apple VideoToolbox',amf:'AMD AMF',qsv:'Intel Quick Sync'};
const wmVal=()=>$('wm').value=='__custom__'?$('wm_c').value.trim():$('wm').value;
function wmChange(){const c=$('wm').value=='__custom__';$('wm_c').style.display=c?'':'none';const W=AI.gpu.whisper||{};
 $('wm_h').textContent=c?'Any faster-whisper (CTranslate2) model: a size, a Hugging Face repo id, or a local folder that contains model.bin.':$('wm').value=='auto'?`Picks the model by hardware: ${W.reason||''}.`:'';}
async function wmFetch(){const v=wmVal(),m=$('wm_m');if(!v)return;m.className='msg';m.textContent='starting\u2026';
 await ollamaJob(await post('/api/whisper/fetch',{model:v==='auto'?((AI.gpu.whisper||{}).auto_model||'small'):v}),'Model is ready.','Download failed','wm_dl','wm_m')}
async function saveProc(){const r=await post('/api/settings',{whisper_model:wmVal(),transcription:$('tp').value,ollama_vision:$('ov').checked});alert(r.ok?'Saved':(r.error||'failed'))}
const kmsg=(env,t,ok)=>{const m=$('km_'+env);if(m){m.textContent=t;m.className='msg '+(ok?'ok':'warn')}};
function keyEdit(env){const k=$('key_'+env);k.dataset.edit=1;k.disabled=false;k.value='';k.type='password';k.placeholder='paste the new key, then Save';k.focus()}
async function keySave(env){if(!E)return kmsg(env,NOE);const k=$('key_'+env),v=k.value.trim();if(!v)return kmsg(env,'Paste a key first.');
 const r=await E.setKey(env,v);delete k.dataset.edit;k.value='';kmsg(env,r?'Saved (encrypted by Windows). Press Test to verify.':'Not saved.',r);await aiLoad()}
const splitKeys=v=>[...new Set((v||'').split(/[\s,;]+/).filter(Boolean))];
async function keyAdd(env){if(!E)return kmsg(env,NOE);const k=$('key_'+env),add=splitKeys(k.value);if(!add.length)return kmsg(env,'Paste a key first.');
 const cur=AI.keys[env]?splitKeys(await E.revealKey(env)):[],all=[...new Set([...cur,...add])];
 const r=await E.setKey(env,all.join('\n'));k.value='';kmsg(env,r?`Saved (${all.length} key${all.length>1?'s':''}, encrypted by your OS). Press Test connection to verify them.`:'Not saved.',r);await aiLoad()}
async function keyDel(env,i){if(!E)return kmsg(env,NOE);const cur=splitKeys(await E.revealKey(env));cur.splice(i,1);
 if(cur.length)await E.setKey(env,cur.join('\n'));else await E.removeKey(env);kmsg(env,'Key removed.',true);await aiLoad()}
const NOE='Storing keys here needs the desktop app. Without it, put them in the .env file (GEMINI_FREE_API_KEY=key1,key2) - see the README.';
async function keyRemove(env){if(!E)return;if(!confirm(isMulti(env)?'Remove ALL stored keys of this provider?':'Remove this stored key?'))return;await E.removeKey(env);const k=$('key_'+env);delete k.dataset.edit;kmsg(env,'Removed.',true);await aiLoad()}
const _t={};
async function keyShow(env){const k=$('key_'+env),b=$('show_'+env);
 if(b.textContent=='Hide'){clearTimeout(_t[env]);k.type='password';if(!k.dataset.edit){k.value='';k.disabled=!!AI.keys[env]}b.textContent='Show';return}
 if(k.dataset.edit||!AI.keys[env]){k.type='text';b.textContent='Hide';return}
 if(!E)return;const v=await E.revealKey(env);if(!v)return kmsg(env,'Could not read the stored key.');k.disabled=false;k.value=v;k.type='text';b.textContent='Hide';
 _t[env]=setTimeout(()=>{if(b.textContent=='Hide')keyShow(env)},15000)}

setTimeout(()=>aiLoad().catch(()=>{}),0);
"""

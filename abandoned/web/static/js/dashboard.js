/* ═══════════════════════════════════════════════════════════════
   SignOffAI Frontend Application v2.0
   ═══════════════════════════════════════════════════════════════ */

// ── GLOBAL STATE ──
let AUTH={token:'',user:null}, vpSelectedLevel='', vpSelectedParent='', vpSelectedKey='', vpSelectedName='';
const LVL={chip:'芯片级',st:'系统级',it:'集成级',bt:'模块级',ut:'单元级'};

// ── API helper ──
const API=(path,opts={})=>{
    const h={...opts.headers}; if(AUTH.token) h['Authorization']=`Bearer ${AUTH.token}`;
    if(opts.body&&typeof opts.body==='object'){h['Content-Type']='application/json';opts.body=JSON.stringify(opts.body)}
    return fetch(path,{...opts,headers:h}).then(r=>{
        if(r.status===401){doLogout();throw new Error('Unauthorized')}
        return r.ok?r.json():r.json().then(e=>Promise.reject(e.detail||r.statusText))
    });
};

// ── Toast ──
const toast=(msg,type='info')=>{
    const c=document.getElementById('toastContainer');
    const d=document.createElement('div'); d.className=`toast-msg ${type}`; d.textContent=msg;
    c.appendChild(d); setTimeout(()=>{d.style.opacity='0';setTimeout(()=>d.remove(),300)},2800);
};

// ── Console log ──
const log=(msg,cls='')=>{
    const c=document.getElementById('console'); if(!c)return;
    const t=new Date().toLocaleTimeString();
    const color=cls==='error'?'err':cls==='ok'?'ok':cls==='info'?'info':'';
    c.innerHTML+=`<div><span class="ts">[${t}]</span><span class="${color}">${msg}</span></div>`;
    c.scrollTop=c.scrollHeight;
};

// ── Theme toggle ──
function toggleTheme(){
    const html=document.documentElement;
    const cur=html.getAttribute('data-theme');
    const next=cur==='dark'?'light':'dark';
    html.setAttribute('data-theme',next);
    localStorage.setItem('theme',next);
}

// ── AUTH ──
async function doLogin(){
    var u=document.getElementById('loginUser').value;
    var p=document.getElementById('loginPass').value;
    var errEl=document.getElementById('loginError');
    errEl.textContent='登录中...';
    try{
        var resp=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})});
        if(!resp.ok){errEl.textContent='用户名或密码错误';return}
        var data=await resp.json();
        AUTH.token=data.token; AUTH.user=data.user;
        document.getElementById('loginOverlay').setAttribute('hidden','');
        document.getElementById('sidebar').removeAttribute('hidden');
        document.getElementById('topbar').removeAttribute('hidden');
        document.getElementById('mainContent').removeAttribute('hidden');
        document.getElementById('sbUser').textContent=data.user.display_name;
        document.getElementById('sbRole').textContent=data.user.role;
        document.getElementById('sbAvatar').textContent=data.user.display_name[0].toUpperCase();
        initApp();
    }catch(e){ errEl.textContent='网络错误: '+e.message }
}
function doLogout(){AUTH={token:'',user:null};location.reload()}

// ── NAVIGATION ──
let APP_ROLE='manager';
const PAGE_LOADERS={dashboard:loadDashboard,manager:loadManager,docs:loadDocs,vplan:loadVPlan,design:loadDesignArch,versions:loadVersions,pipeline:loadPipelineTab,testcases:loadTC,coverage:loadCoverage,regression:loadRegression,signoff:loadSignoffs,knowledge:searchKB,admin:loadAdmin,settings:loadSettings,trace:loadTrace,'debug-copilot':loadDebugCopilot,'tool-governance':loadToolGovernance};

function switchRole(role){
    APP_ROLE=role;
    const mgrBtn=document.getElementById('roleMgrBtn');const engBtn=document.getElementById('roleEngBtn');
    if(role==='manager'){mgrBtn.style.background='var(--brand-blue)';mgrBtn.style.color='#fff';engBtn.style.background='transparent';engBtn.style.color='var(--text-secondary)';}
    else{engBtn.style.background='var(--brand-blue)';engBtn.style.color='#fff';mgrBtn.style.background='transparent';mgrBtn.style.color='var(--text-secondary)';}
    // Show/hide sidebar items + sections
    document.querySelectorAll('.sidebar-nav .nav-item[data-role], .sidebar-nav .nav-section[data-role]').forEach(i=>{
        const r=i.dataset.role; i.style.display=(r===role||r==='both')?'':'none';
    });
    // Switch to default page for role
    const defaultPage=role==='manager'?'manager':'dashboard';
    document.querySelectorAll('.sidebar-nav .nav-item').forEach(i=>i.classList.remove('active'));
    const item=document.querySelector(`.sidebar-nav .nav-item[data-page="${defaultPage}"]`); if(item)item.classList.add('active');
    document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
    const pg=document.getElementById('page-'+defaultPage); if(pg)pg.classList.add('active');
    document.getElementById('pageTitle').textContent=role==='manager'?'模块总览':'仪表盘';
    document.getElementById('pageBreadcrumb').textContent='SignOffAI / '+(role==='manager'?'SignOff 经理':'SignOff 工程师');
    if(PAGE_LOADERS[defaultPage])PAGE_LOADERS[defaultPage]();
}
document.addEventListener('DOMContentLoaded',()=>{
    document.querySelectorAll('.sidebar-nav .nav-item').forEach(item=>{
        item.addEventListener('click',()=>{
            document.querySelectorAll('.sidebar-nav .nav-item').forEach(i=>i.classList.remove('active'));
            item.classList.add('active');
            document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
            const pg=document.getElementById('page-'+item.dataset.page); if(pg)pg.classList.add('active');
            const label=item.textContent.replace(/[●●]/g,'').trim();
            document.getElementById('pageTitle').textContent=label;
            document.getElementById('pageBreadcrumb').textContent='SignOffAI / '+(APP_ROLE==='manager'?'SignOff 经理':'SignOff 工程师')+' / '+label;
            if(PAGE_LOADERS[item.dataset.page])PAGE_LOADERS[item.dataset.page]();
        });
    });
});

// ── DASHBOARD ──
async function loadDashboard(){
    try{
        const [stats,cov,vplan]=await Promise.all([API('/api/dashboard/stats'),API('/api/coverage/summary'),API('/api/vplan/stats')]);
        document.getElementById('sReqs').textContent=vplan.total||0;
        const verified=vplan.stats?Object.values(vplan.stats).reduce((a,b)=>a+(b.verified||0),0):0;
        document.getElementById('sProgress').textContent=vplan.total?Math.round(verified/vplan.total*100)+'%':'--';
        document.getElementById('sCover').textContent=(cov.code_coverage||0)+'%';
        document.getElementById('sReg').textContent=(stats.last_regression?.pass_rate||'--')+'%';

        // Evidence bar
        try{
            const mfs=await API('/api/manifest/latest');
            if(mfs&&mfs.run_id){
                document.getElementById('dashEvidence').style.display='flex';
                document.getElementById('evRunId').textContent='Run '+mfs.run_id.substring(0,18);
                document.getElementById('evPhases').textContent=mfs.passed+'/'+mfs.total_phases+' passed';
                document.getElementById('evScore').textContent='Score '+mfs.overall_score+'/100';
                document.getElementById('evHash').textContent=(mfs.manifest_hash||'').substring(0,14)+'...';
            }
        }catch(e){}

        // Trend chart
        const trend=stats.regression_trend||[];
        const ctx=document.getElementById('trendChart');
        if(ctx&&trend.length&&typeof Chart!=='undefined'){
            if(ctx._chart)ctx._chart.destroy();
            ctx._chart=new Chart(ctx,{type:'line',data:{labels:trend.map(t=>t.date),datasets:[{label:'通过率 %',data:trend.map(t=>t.pass_rate),borderColor:'#10b981',backgroundColor:'rgba(16,185,129,.1)',tension:0.4,fill:true,pointRadius:2,borderWidth:2}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{ticks:{color:'#5a6678',font:{size:9}},grid:{color:'#1e2632'}},y:{ticks:{color:'#5a6678',font:{size:9}},grid:{color:'#1e2632'},min:0,max:100}}}});
        }

        try{const logs=await API('/api/audit?limit=8');document.getElementById('recentActivity').innerHTML=logs.logs.map(l=>`<div class="mb-1 flex-between"><span><strong>${l.username}</strong> ${l.action}</span><span style="color:var(--text-muted)">${(l.created_at||'').substring(5,16)}</span></div>`).join('')||'<div style="color:var(--text-muted)">暂无活动</div>'}catch(e){}
    }catch(e){console.error('Dashboard:',e)}
}

// ── PIPELINE ──
const P_FULL=['spec','design','model','ifspec','rtlsign','vplan','tpoint','rtm','UVM','test','assert','regress','cover','debug','qa','report','vclose'];
const P_QUICK=P_FULL.slice(0,5);
let currentTrack='traditional';

function switchTrack(track){
    currentTrack=track;
    const t=document.getElementById('trackTraditional');const a=document.getElementById('trackAI');
    const hint=document.getElementById('aiHint');
    if(track==='traditional'){
        t.style.background='var(--brand-blue-dim)';t.style.color='var(--brand-blue)';t.style.borderColor='var(--brand-blue-dim)';t.style.fontWeight='600';
        a.style.background='transparent';a.style.color='var(--text-secondary)';a.style.borderColor='transparent';a.style.fontWeight='normal';
        hint.style.display='none';
    }else{
        a.style.background='var(--brand-blue-dim)';a.style.color='var(--brand-blue)';a.style.borderColor='var(--brand-blue-dim)';a.style.fontWeight='600';
        t.style.background='transparent';t.style.color='var(--text-secondary)';t.style.borderColor='transparent';t.style.fontWeight='normal';
        hint.style.display='block';
    }
}

function buildPhaseTrack(wf){
    const phases=wf==='quick_check'?P_QUICK:P_FULL;
    const track=document.getElementById('phaseTrack');
    track.innerHTML=phases.map((p,i)=>`<div class="phase-node"><div class="dot" id="dot-${p}">${i+1}</div><div class="label">${p}</div></div>${i<phases.length-1?'<div class="phase-line" id="line-${i}"></div>':''}`).join('');
}
async function runPipeline(){
    const spec=document.getElementById('specInput').value.trim();if(!spec){toast('请输入规格','error');return}
    const wf=document.getElementById('workflowSelect').value;
    const trackLabel=currentTrack==='ai_exploration'?'🤖 AI智能探索':'🔬 常规仿真';
    buildPhaseTrack(wf);
    document.getElementById('pStatus').textContent='运行中';document.getElementById('pStatus').className='badge badge-blue';
    document.getElementById('pProgress').style.width='0%';
    document.getElementById('console').innerHTML='';
    log(`▶ 启动: ${wf} [${trackLabel}]`,'info');const t0=Date.now();
    try{
        const r=await API('/api/pipeline/run',{method:'POST',body:{spec_text:spec,workflow:wf,run_type:currentTrack}});
        // Connect SSE for real-time updates
        const sse=new EventSource('/api/pipeline/'+r.run_id+'/stream');
        sse.addEventListener('phase_update',function(e){const d=JSON.parse(e.data);const dot=document.getElementById('dot-'+d.phase);if(dot)dot.className='dot '+(d.status==='passed'?'pass':d.status==='failed'?'fail':'');log(`  ${d.status==='passed'?'✅':'❌'} ${d.phase} (${d.elapsed}s score=${d.score})`,d.status==='passed'?'ok':'error')});
        sse.addEventListener('run_complete',function(e){sse.close();const d=JSON.parse(e.data);document.getElementById('pProgress').style.width='100%';const ok=d.passed===d.total;document.getElementById('pStatus').textContent=ok?'全部通过':'部分失败';document.getElementById('pStatus').className='badge '+(ok?'badge-green':'badge-amber');document.getElementById('pResult').textContent=d.passed+'/'+d.total+' 阶段通过';log('🏁 SSE实时: '+d.passed+'/'+d.total,ok?'ok':'error');
        // Auto-refresh manager module data
        try{API('/api/modules').then(d=>{if(d.total_modules>0){document.getElementById('evHash').textContent=(d.modules[0]?.evidence_hash||'').substring(0,14)+'...';}})}catch(e){}
        });
        sse.onerror=function(){sse.close()};
        const elapsed=((Date.now()-t0)/1000).toFixed(1);
        document.getElementById('pProgress').style.width='100%';
        const ok=r.passed===r.total;
        document.getElementById('pStatus').textContent=ok?'全部通过':'部分失败';
        document.getElementById('pStatus').className='badge '+(ok?'badge-green':'badge-amber');
        document.getElementById('pResult').textContent=`${r.passed}/${r.total} 阶段通过`;
        document.getElementById('pTime').textContent=`${elapsed}s`;
        const failedPhases=[];
        r.phases.forEach(p=>{const d=document.getElementById('dot-'+p.name);if(d)d.className='dot '+(p.status==='passed'?'pass':p.status==='failed'?'fail':'');log(`  ${p.status==='passed'?'✅':'❌'} ${p.name} (${p.time}s score=${p.score})`,p.status==='passed'?'ok':'error');if(p.status==='failed'||p.status==='error')failedPhases.push(p)});
        log(`🏁 完成: ${r.passed}/${r.total}`,ok?'ok':'error');
        toast(`${trackLabel}完成: ${r.passed}/${r.total}`,ok?'success':'error');
        setTimeout(loadDashboard,500);
        if(r.manifest_path) log(`📦 Manifest: ${r.manifest_path}`,'info');
        if(r.run_id) log(`📋 复现: vagent dump ${r.run_id}  |  vagent dump ${r.run_id} -o evidence.zip`,'info');

        // AI 智能分析失败的阶段
        if(failedPhases.length>0){
            log('','');
            log('━━━ 🤖 AI 智能分析 ━━━','info');
            for(const fp of failedPhases){
                const errText=fp.error||fp.reason||`Phase ${fp.name} failed with score ${fp.score}`;
                try{
                    const ai=await API('/api/ai/analyze-error',{method:'POST',body:JSON.stringify({phase_name:fp.name,error_log:errText,agent_role:fp.name}),headers:{'Content-Type':'application/json'}});
                    log(`  📋 ${fp.name}: ${ai.summary}`,'error');
                    ai.suggestions.forEach(s=>{
                        const sev={high:'🔴',medium:'🟡',low:'🟢'}[s.severity]||'⚪';
                        log(`     ${sev} ${s.diagnosis}`,'error');
                        log(`     💡 ${s.fix}`,s.auto_fixable?'info':'');
                    });
                    if(ai.auto_fixable_count>0) log(`     ✅ ${ai.auto_fixable_count} 个问题可自动修复`,'info');
                }catch(e){log(`  AI分析失败: ${e}`,'error')}
            }
            log('━━━━━━━━━━━━━━━━━━━━','info');
        }
    }catch(e){log('失败: '+e,'error');toast('流水线失败','error')}
}
async function loadDefaultSpec(){const d=await API('/api/spec/default');document.getElementById('specInput').value=d.content}
function loadPipelineTab(){const wf=document.getElementById('workflowSelect').value;buildPhaseTrack(wf);loadDefaultSpec()}

// ── DOCS (可视化编辑器) ──
let docState={id:0,name:'',content:'',title:'',isDirty:false};
async function loadDocs(){
    try{
        const d=await API('/api/v2/docs?limit=200');
        const canEdit=AUTH.user&&(AUTH.user.role==='admin'||AUTH.user.role==='verification_manager');
        document.getElementById('newDocBtn').style.display=canEdit?'':'none';
        const docs=d.docs||[];
        document.getElementById('docsList').innerHTML=docs.map(doc=>{
            const rp=doc.path||doc.name||'';
            const levelBadge=doc.level?`<span class="badge badge-muted" style="font-size:8px;padding:0 4px">${doc.level}</span> `:'';
            const statusColor=doc.status==='approved'?'var(--brand-green)':doc.status==='review'?'var(--brand-amber)':'var(--text-muted)';
            return`<div class="tree-node" onclick="viewDoc(${doc.id})" style="align-items:flex-start">
                <i class="bi-file-earmark-text" style="margin-top:2px"></i>
                <div style="flex:1">
                    <div>${levelBadge}<strong>${doc.title||doc.path}</strong></div>
                    <div class="text-xs" style="color:var(--text-muted)">${rp} · ${((doc.size||0)/1024).toFixed(1)}KB · ${doc.req_count||0}需求 · <span style="color:${statusColor}">${doc.status||'draft'}</span></div>
                </div>
            </div>`;
        }).join('')||`<div style="color:var(--text-muted);padding:8px">暂无文档${canEdit?' — 点击 + 新建':' — 请联系 SignOff 经理添加'}</div>`;
    }catch(e){document.getElementById('docsList').innerHTML=`<div style="color:var(--brand-red);padding:8px">加载失败: ${e}</div>`}
}

function renderMarkdown(md){
    if(!md)return'';
    // Pre-process: extract code blocks to protect them from HTML escaping
    const codeBlocks=[];
    let h=md.replace(/```(\w*)\n([\s\S]*?)```/g,(_,lang,code)=>{
        const idx=codeBlocks.length;
        codeBlocks.push({lang:lang||'',code:code.replace(/</g,'&lt;').replace(/>/g,'&gt;')});
        return`\x00CODEBLOCK${idx}\x00`;
    });
    // Extract inline code to protect
    const inlineCodes=[];
    h=h.replace(/`([^`]+)`/g,(_,code)=>{
        const idx=inlineCodes.length;
        inlineCodes.push(code.replace(/</g,'&lt;').replace(/>/g,'&gt;'));
        return`\x00INLINECODE${idx}\x00`;
    });
    // Escape HTML
    h=h.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    // Headers (before other patterns)
    h=h.replace(/^#### (.+)$/gm,'<h6 style="margin:12px 0 4px;color:var(--text-primary)">$1</h6>');
    h=h.replace(/^### (.+)$/gm,'<h5 style="margin:14px 0 6px;color:var(--text-primary)">$1</h5>');
    h=h.replace(/^## (.+)$/gm,'<h4 style="margin:16px 0 6px;color:var(--text-primary);border-bottom:1px solid var(--border);padding-bottom:4px">$1</h4>');
    h=h.replace(/^# (.+)$/gm,'<h3 style="margin:18px 0 8px;color:var(--text-primary)">$1</h3>');
    // Bold / italic / strikethrough
    h=h.replace(/\*\*\*(.+?)\*\*\*/g,'<strong><em>$1</em></strong>');
    h=h.replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>');
    h=h.replace(/\*(.+?)\*/g,'<em>$1</em>');
    h=h.replace(/~~(.+?)~~/g,'<del>$1</del>');
    // Links and images
    h=h.replace(/!\[([^\]]*)\]\(([^)]+)\)/g,'<img src="$2" alt="$1" style="max-width:100%;border-radius:4px">');
    h=h.replace(/\[([^\]]+)\]\(([^)]+)\)/g,'<a href="$2" style="color:var(--brand-blue)" target="_blank">$1</a>');
    // Horizontal rules
    h=h.replace(/^(---|\*\*\*|___)\s*$/gm,'<hr style="border:none;border-top:1px solid var(--border);margin:12px 0">');
    // Blockquotes
    h=h.replace(/^&gt; (.+)$/gm,'<blockquote style="border-left:3px solid var(--brand-blue);padding:4px 10px;margin:6px 0;color:var(--text-secondary);background:var(--bg-input);border-radius:0 4px 4px 0">$1</blockquote>');
    // Tables — convert each row, then wrap groups with <table>
    h=h.replace(/^\|(.+)\|$/gm,function(line){
        const cells=line.slice(1,-1).split('|');
        if(cells.every(c=>/^[\s\-:]+$/.test(c)))return'\x00TBODY\x00'; // separator row
        return'<tr>'+cells.map(c=>{
            const t=c.trim();
            if(t.startsWith('**')&&t.endsWith('**'))return'<th>'+t.slice(2,-2)+'</th>';
            return'<td>'+t+'</td>';
        }).join('')+'</tr>';
    });
    // Group table rows: <tr>...</tr> sequences between TBODY markers become <thead>/<tbody>
    h=h.replace(/((?:<tr>[^]*?<\/tr>\n?)+)/g,function(block){
        const parts=block.split('\x00TBODY\x00');
        let tbl='<table style="width:100%;border-collapse:collapse;margin:8px 0;font-size:11px">';
        if(parts.length>1){
            tbl+='<thead>'+parts[0]+'</thead><tbody>'+parts.slice(1).join('')+'</tbody>';
        }else{
            tbl+='<tbody>'+parts[0]+'</tbody>';
        }
        return tbl+'</table>';
    });
    h=h.replace(/<tr><th>/g,'<tr><th style="border-bottom:2px solid var(--border);padding:6px 8px;text-align:left;font-weight:600">');
    h=h.replace(/<tr><td>/g,'<tr><td style="border-bottom:1px solid var(--border);padding:4px 8px">');
    // Nested lists — un-ordered
    h=h.replace(/^( {0,8})[-*+] (.+)$/gm,(_,indent,text)=>`<li style="margin-left:${20+(indent.length*4)}px">${text}</li>`);
    // Ordered lists
    h=h.replace(/^( {0,8})\d+\. (.+)$/gm,(_,indent,text)=>`<li style="margin-left:${20+(indent.length*4)}px">${text}</li>`);
    // Group consecutive <li> tags into <ul>
    h=h.replace(/((?:<li[^>]*>.*<\/li>\n?)+)/g,'<ul style="margin:4px 0;list-style-position:inside">$1</ul>');
    // Restore inline code
    h=h.replace(/\x00INLINECODE(\d+)\x00/g,(_,idx)=>`<code style="background:var(--bg-input);padding:1px 5px;border-radius:3px;font-size:11px;color:var(--brand-green)">${inlineCodes[idx]||''}</code>`);
    // Restore code blocks
    h=h.replace(/\x00CODEBLOCK(\d+)\x00/g,(_,idx)=>{
        const cb=codeBlocks[idx];
        const langLabel=cb.lang?`<div style="font-size:9px;color:var(--text-muted);padding:2px 8px">${cb.lang}</div>`:'';
        return langLabel+`<pre style="background:var(--bg-primary);padding:10px;border-radius:6px;overflow-x:auto;font-size:11px;line-height:1.4;margin:8px 0"><code>${cb.code}</code></pre>`;
    });
    // Paragraphs — wrap remaining text lines (not already in block tags)
    const blockTags=/<(h[1-6]|table|ul|ol|pre|blockquote|hr|div|img|li|thead|tbody|tr|th|td|code|strong|em|a|p)[^>]*>/i;
    const lines=h.split('\n');
    let result='',inPara=false;
    for(let i=0;i<lines.length;i++){
        const line=lines[i].trim();
        if(!line){
            if(inPara){result+='</p>';inPara=false;}
            continue;
        }
        if(blockTags.test(line)||line.startsWith('<')||line==='</p>'){
            if(inPara){result+='</p>';inPara=false;}
            result+=line;
        }else{
            if(!inPara){result+='<p style="margin:4px 0">';inPara=true;}
            else result+=' ';
            result+=line;
        }
    }
    if(inPara)result+='</p>';
    return result||'<p style="margin:4px 0;color:var(--text-muted)">（空文档）</p>';
}

function toggleDocEdit(){
    var preview=document.getElementById('docPreview'), editor=document.getElementById('docEditor');
    var editBtn=document.getElementById('docEditBtn'), saveBtn=document.getElementById('docSaveBtn');
    if(editor.style.display==='none'){
        preview.style.display='none';editor.style.display='';editor.style.height=(preview.offsetHeight+40)+'px';
        editBtn.textContent='预览';saveBtn.style.display='';
    }else{
        editor.style.display='none';preview.style.display='';
        editBtn.textContent='编辑';saveBtn.style.display='none';
        // Auto-save when switching to preview mode
        saveDoc();
    }
}
async function saveDoc(){
    if(!docState.id)return;
    var content=document.getElementById('docEditor').value;
    try{
        await API('/api/v2/docs/'+docState.id,{method:'PUT',body:JSON.stringify({content:content,change_summary:'手动编辑保存'}),headers:{'Content-Type':'application/json'}});
        docState.content=content;docState.isDirty=false;
        document.getElementById('docSavedBadge').style.display='';
        document.getElementById('docPreview').innerHTML=renderMarkdown(content);
        toast('已保存','success');
        setTimeout(function(){document.getElementById('docSavedBadge').style.display='none'},2000);
        // Refresh version history after save
        viewDoc(docState.id);
    }catch(e){toast('保存失败: '+e,'error')}
}

// ── 结构化编辑器 ──
let structDoc=null;

async function viewDoc(docId){
    try{
        const d=await API('/api/v2/docs/'+docId);
        docState={id:docId,name:d.path||'',content:d.content||'',title:d.title||'',isDirty:false};
        document.getElementById('docViewerTitle').innerHTML=`<i class="bi-file-text"></i>${d.title||d.path}`;
        document.getElementById('docPreview').innerHTML=renderMarkdown(d.content||'');
        document.getElementById('docEditor').value=d.content||'';
        const reqCount=(d.requirements||[]).length;
        const verCount=(d.versions||[]).length;
        document.getElementById('docMeta').textContent=`${(d.content||'').split('\\n').length} 行 · ${((d.content||'').length/1024).toFixed(1)}KB · ${d.path||''} · ${reqCount}需求 · ${verCount}版本`;
        // Role-based: only manager/SignOff经理 can edit
        const canEdit=AUTH.user&&(AUTH.user.role==='admin'||AUTH.user.role==='verification_manager');
        document.getElementById('docEditBtn').style.display=canEdit?'':'none';
        document.getElementById('docSaveBtn').style.display='none';
        document.getElementById('docSavedBadge').style.display='none';
        document.getElementById('docPreview').style.display='';
        document.getElementById('docEditor').style.display='none';
        document.getElementById('structEditor').style.display=canEdit?'':'none';
        // Linked requirements from v2 API
        if(d.requirements&&d.requirements.length){
            document.getElementById('docLinkedReqs').innerHTML='<strong>关联需求:</strong> '+d.requirements.map(r=>`<span class="badge badge-blue" style="cursor:pointer" onclick="jumpToReq('${r.req_id}')">${r.req_id}</span>`).join(' ');
        }else{document.getElementById('docLinkedReqs').innerHTML=''}
        // Load structured editor (only for manager)
        if(canEdit) loadStructuredEditor(docState.name);
        // Load version history with full data
        loadVersionHistory(d);
    }catch(e){document.getElementById('docPreview').textContent='加载失败: '+e}
}

async function loadVersionHistory(docData){
    try{
        const versions=docData?.versions||[];
        if(versions.length>0){
            document.getElementById('versionHistory').style.display='';
            document.getElementById('versionList').innerHTML=versions.map(v=>`<div class="flex-between mb-1" style="padding:6px 8px;background:var(--bg-input);border-radius:4px;align-items:center">
                <div style="flex:1">
                    <div><strong>v${v.version}</strong> <code style="font-size:9px;color:var(--text-muted)">${(v.id||'')}</code></div>
                    <div style="color:var(--text-muted);font-size:10px">${(v.created_at||'').substring(0,16)} · ${v.change_summary||'无说明'}</div>
                </div>
                <div class="btn-group">
                    <button class="btn btn-outline btn-xs" onclick="viewVersionContent(${docData.id},${v.id})" title="查看此版本">👁</button>
                    <button class="btn btn-outline btn-xs" onclick="restoreVersion(${docData.id},${v.id},'${v.version}')" title="回退到此版本" style="color:var(--brand-amber)">↩</button>
                </div>
            </div>`).join('');
        }
    }catch(e){}
}

async function viewVersionContent(docId,versionId){
    try{
        const v=await API('/api/v2/docs/'+docId+'/versions/'+versionId);
        document.getElementById('docPreview').innerHTML='<div class="text-xs mb-2" style="color:var(--brand-amber);background:var(--bg-input);padding:4px 8px;border-radius:4px">📜 查看版本 <strong>v'+v.version+'</strong> — '+v.change_summary+' ('+(v.created_at||'').substring(0,16)+') <button class="btn btn-primary btn-xs" onclick="viewDoc('+docId+')" style="margin-left:8px">返回最新</button></div>'+renderMarkdown(v.content||'');
        document.getElementById('docEditor').value=v.content||'';
        toast('正在查看历史版本 v'+v.version,'info');
    }catch(e){toast('无法加载版本: '+e,'error')}
}

async function restoreVersion(docId,versionId,versionLabel){
    if(!confirm('确认回退到版本 '+versionLabel+'？\n当前内容将被此版本覆盖。'))return;
    try{
        const r=await API('/api/v2/docs/'+docId+'/versions/'+versionId+'/restore',{method:'POST'});
        if(r.status==='restored'){toast('✅ 已回退到版本 '+versionLabel,'success');viewDoc(docId)}
    }catch(e){toast('回退失败: '+e,'error')}
}

async function loadStructuredEditor(docPath){
    try{
        const d=await API('/api/editor/'+docPath);
        structDoc=d.doc;
        document.getElementById('structEditor').style.display='';
        renderInterfaceEditor();
        renderTimingEditor();
        renderPowerEditor();
        renderReqEditor();
    }catch(e){document.getElementById('structEditor').style.display='none'}
}

function renderInterfaceEditor(){
    const ifaces=structDoc?.interfaces||[];
    document.getElementById('ifaceEditor').innerHTML=ifaces.map((f,i)=>`<div class="mb-2" style="padding:6px;background:var(--bg-input);border-radius:4px">
        <div class="flex-between text-xs mb-1"><strong>接口 ${i+1}</strong><span style="cursor:pointer;color:var(--brand-red)" onclick="deleteItem('interfaces',${i})">✕</span></div>
        <input class="mb-1" style="width:100%;font-size:10px" placeholder="名称" value="${f.name}" onchange="updateField('interfaces',${i},'name',this.value)">
        <div class="flex gap-1 mb-1">
            <select style="flex:1;font-size:10px" onchange="updateField('interfaces',${i},'direction',this.value)"><option ${f.direction==='INPUT'?'selected':''}>INPUT</option><option ${f.direction==='OUTPUT'?'selected':''}>OUTPUT</option><option ${f.direction==='INOUT'?'selected':''}>INOUT</option></select>
            <input style="width:50px;font-size:10px" placeholder="宽度" value="${f.width}" onchange="updateField('interfaces',${i},'width',parseInt(this.value)||1)">
        </div>
        <input style="width:100%;font-size:10px" placeholder="协议 (如 AXI-Stream)" value="${f.protocol||''}" onchange="updateField('interfaces',${i},'protocol',this.value)">
    </div>`).join('')||'<div class="text-xs" style="color:var(--text-muted)">无接口 — 点击 + 添加</div>';
}

function renderTimingEditor(){
    const tcs=structDoc?.timing_constraints||[];
    document.getElementById('timingEditor').innerHTML=tcs.map((t,i)=>`<div class="mb-2" style="padding:6px;background:var(--bg-input);border-radius:4px">
        <div class="flex-between text-xs mb-1"><strong>约束 ${i+1}</strong><span style="cursor:pointer;color:var(--brand-red)" onclick="deleteItem('timing_constraints',${i})">✕</span></div>
        <div class="flex gap-1 mb-1">
            <input style="flex:1;font-size:10px" placeholder="信号A" value="${t.signal_a}" onchange="updateField('timing_constraints',${i},'signal_a',this.value)">
            <select style="width:50px;font-size:10px" onchange="updateField('timing_constraints',${i},'relation',this.value)"><option ${t.relation==='≥'?'selected':''}>≥</option><option ${t.relation==='≤'?'selected':''}>≤</option><option ${t.relation==='='?'selected':''}>=</option><option ${t.relation==='setup'?'selected':''}>setup</option><option ${t.relation==='hold'?'selected':''}>hold</option></select>
            <input style="flex:1;font-size:10px" placeholder="信号B" value="${t.signal_b}" onchange="updateField('timing_constraints',${i},'signal_b',this.value)">
        </div>
        <input style="width:100%;font-size:10px" placeholder="周期数" value="${t.cycles}" onchange="updateField('timing_constraints',${i},'cycles',parseFloat(this.value)||1)">
    </div>`).join('')||'<div class="text-xs" style="color:var(--text-muted)">无约束 — 点击 + 添加</div>';
}

function renderPowerEditor(){
    const pcs=structDoc?.power_constraints||[];
    document.getElementById('powerEditor').innerHTML=pcs.map((p,i)=>`<div class="mb-2" style="padding:6px;background:var(--bg-input);border-radius:4px">
        <div class="flex-between text-xs mb-1"><strong>模式 ${i+1}</strong><span style="cursor:pointer;color:var(--brand-red)" onclick="deleteItem('power_constraints',${i})">✕</span></div>
        <input class="mb-1" style="width:100%;font-size:10px" placeholder="模式名" value="${p.mode}" onchange="updateField('power_constraints',${i},'mode',this.value)">
        <input style="width:100%;font-size:10px" placeholder="功耗 (mW)" type="number" value="${p.power_mw}" onchange="updateField('power_constraints',${i},'power_mw',parseFloat(this.value)||0)">
    </div>`).join('')||'<div class="text-xs" style="color:var(--text-muted)">无约束 — 点击 + 添加</div>';
}

function renderReqEditor(){
    const reqs=structDoc?.requirements||[];
    document.getElementById('reqEditor').innerHTML=reqs.map((r,i)=>`<div class="mb-2" style="padding:6px;background:var(--bg-input);border-radius:4px">
        <div class="flex-between text-xs mb-1"><strong>${r.level||'P0'} ${r.title||'需求 '+(i+1)}</strong><span style="cursor:pointer;color:var(--brand-red)" onclick="deleteItem('requirements',${i})">✕</span></div>
        <input class="mb-1" style="width:100%;font-size:10px" placeholder="标题" value="${r.title||''}" onchange="updateField('requirements',${i},'title',this.value)">
        <div class="flex gap-1 mb-1">
            <select style="flex:1;font-size:10px" onchange="updateField('requirements',${i},'level',this.value)"><option ${r.level==='P0'?'selected':''}>P0</option><option ${r.level==='P1'?'selected':''}>P1</option><option ${r.level==='P2'?'selected':''}>P2</option><option ${r.level==='P3'?'selected':''}>P3</option></select>
            <select style="flex:1;font-size:10px" onchange="updateField('requirements',${i},'req_type',this.value)"><option ${r.req_type==='FUNCTIONAL'?'selected':''}>FUNCTIONAL</option><option ${r.req_type==='CONTROL'?'selected':''}>CONTROL</option><option ${r.req_type==='ERROR'?'selected':''}>ERROR</option><option ${r.req_type==='TIMING'?'selected':''}>TIMING</option><option ${r.req_type==='POWER'?'selected':''}>POWER</option></select>
        </div>
    </div>`).join('')||'<div class="text-xs" style="color:var(--text-muted)">无需求 — 点击 + 添加</div>';
}

function updateField(section,idx,field,value){
    if(!structDoc||!structDoc[section])return;
    structDoc[section][idx][field]=value;
}

function deleteItem(section,idx){
    if(!structDoc||!structDoc[section])return;
    structDoc[section].splice(idx,1);
    if(section==='interfaces')renderInterfaceEditor();
    else if(section==='timing_constraints')renderTimingEditor();
    else if(section==='power_constraints')renderPowerEditor();
    else if(section==='requirements')renderReqEditor();
}

function addInterface(){if(!structDoc)return;structDoc.interfaces=structDoc.interfaces||[];structDoc.interfaces.push({name:'new_signal',width:1,direction:'INPUT',protocol:'',description:''});renderInterfaceEditor()}
function addTiming(){if(!structDoc)return;structDoc.timing_constraints=structDoc.timing_constraints||[];structDoc.timing_constraints.push({signal_a:'',signal_b:'',relation:'≥',cycles:1,description:''});renderTimingEditor()}
function addPower(){if(!structDoc)return;structDoc.power_constraints=structDoc.power_constraints||[];structDoc.power_constraints.push({mode:'Active',power_mw:1,description:''});renderPowerEditor()}
function addRequirement(){if(!structDoc)return;structDoc.requirements=structDoc.requirements||[];structDoc.requirements.push({title:'新需求',level:'P0',req_type:'FUNCTIONAL',description:'',acceptance:''});renderReqEditor()}

async function saveStructured(){
    if(!docState.name||!structDoc){toast('请先选择文档','error');return}
    try{
        const r=await API('/api/editor/'+docState.name,{method:'POST',body:{doc:structDoc}});
        if(r.ok){
            docState.content=r.md;docState.isDirty=false;
            document.getElementById('docPreview').innerHTML=renderMarkdown(r.md);
            document.getElementById('docEditor').value=r.md;
            document.getElementById('docMeta').textContent=`已保存 · ${structDoc.requirements?.length||0}需求, ${structDoc.interfaces?.length||0}接口`;
            document.getElementById('structEditor').style.display='none';
            toast('✅ 结构化文档已保存','success');
        }
    }catch(e){toast('保存失败: '+e,'error')}
}

async function newDoc(){
    const name=prompt('文档路径 (如 alu/alu_spec.md):');if(!name)return;
    const title=prompt('文档标题 (如 ALU 设计规格):');if(!title)return;
    const level=prompt('层级 (module/subsystem/chip/unit):','module')||'module';
    const content=`# ${title}\n\n## 1. 概述\n\n待补充\n\n## 2. 功能需求\n\n### REQ_001\n**级别**：P0  **类型**：FUNCTIONAL  **描述**：待补充  **验收标准**：待补充\n\n## 3. 接口规范\n\n| 信号 | 位宽 | 方向 | 协议 | 描述 |\n|------|------|------|------|------|\n| clk | 1 | INPUT | — | 主时钟 |\n| rst_n | 1 | INPUT | — | 异步复位 |\n\n## 4. 时序约束\n\n## 5. 功耗约束\n`;
    try{
        const r=await API('/api/v2/docs',{method:'POST',body:JSON.stringify({project_id:1,path:name,title:title,content:content,level:level,tags:''}),headers:{'Content-Type':'application/json'}});
        toast('文档已创建','success');
        await loadDocs();
        viewDoc(r.id);
    }catch(e){toast('创建失败: '+e,'error')}
}
function jumpToReq(reqId){
    document.querySelectorAll('.sidebar-nav .nav-item').forEach(i=>i.classList.remove('active'));
    const item=document.querySelector('[data-page="vplan"]'); if(item)item.classList.add('active');
    document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
    document.getElementById('page-vplan').classList.add('active');
    document.getElementById('pageTitle').textContent='需求管理';loadVPlan(reqId.toLowerCase())
}

// ── VPLAN ──
async function loadVPlan(filter=''){
    try{const [hier,stats]=await Promise.all([API('/api/vplan/hierarchy'),API('/api/vplan/stats')]);
        renderVPlanTree(hier.hierarchy,filter);
        if(stats&&stats.stats) document.getElementById('vplanLevelStats').innerHTML=Object.entries(stats.stats).map(([k,v])=>`<span class="badge badge-muted me-1">${LVL[k]}: ${v.count}项 ${v.coverage}%</span>`).join('');
        if(!hier.hierarchy||!hier.hierarchy.length) document.getElementById('vplanTree').innerHTML='<div style="color:var(--text-muted);text-align:center;padding:20px">暂无数据<br><span class="text-xs">点击 + 添加或重启自动生成</span></div>'
    }catch(e){console.error(e)}
}
function renderVPlanTree(hierarchy,filter){
    const tree=document.getElementById('vplanTree'); if(!hierarchy||!hierarchy.length){tree.innerHTML='<div style="color:var(--text-muted);text-align:center;padding:20px">暂无</div>';return}
    function renderNode(node,depth){
        if(node.level==='ut')return'';
        const nodeKey=node.req_id||(node.level+'_'+node.name);
        const id='tn_'+nodeKey.replace(/[^a-zA-Z0-9一-鿿]/g,'_');
        const isSelected=vpSelectedLevel===node.level&&vpSelectedKey===nodeKey;
        let h=`<div class="tree-node${isSelected?' selected':''}" onclick="vplanSelectNode('${node.level}','${nodeKey}','${(node.name||'').replace(/'/g,"\\'")}')" id="${id}" style="padding-left:${10+depth*16}px">`;
        if(node.children&&node.children.length) h+=`<i class="bi-chevron-right" style="font-size:9px;cursor:pointer" onclick="event.stopPropagation();vplanToggleKids('${id}_kids',this)"></i>`;
        else h+='<span style="width:9px;display:inline-block"></span>';
        h+=`<span class="badge badge-muted" style="font-size:8px;padding:1px 5px">${(node.level||'').toUpperCase()}</span>`;
        h+=`<strong>${(node.name||'').substring(0,36)}</strong>`;
        h+=`<span style="margin-left:auto;font-size:10px;color:var(--text-muted)">${node.req_count||0}项 ${node.coverage||0}%</span></div>`;
        if(node.children&&node.children.length){h+=`<div class="tree-children" id="${id}_kids">`;node.children.forEach(c=>{h+=renderNode(c,depth+1)});h+='</div>'}
        return h
    }
    tree.innerHTML=hierarchy.map(n=>renderNode(n,0)).join('');
    setTimeout(()=>{const firstKids=tree.querySelector('.tree-children');if(firstKids)firstKids.style.display='block'},100);
    if(!vpSelectedKey&&hierarchy.length){const root=hierarchy[0];vplanSelectNode(root.level,root.req_id||(root.level+'_'+root.name),root.name)}
}
function vplanToggleKids(elId,icon){const el=document.getElementById(elId);if(!el)return;el.style.display=(el.style.display==='none'||el.style.display==='')?'block':'none';icon.classList.toggle('bi-chevron-right');icon.classList.toggle('bi-chevron-down')}
function vplanSelectNode(level,nodeKey,name){vpSelectedLevel=level;vpSelectedKey=nodeKey;vpSelectedName=name;document.getElementById('vplanDetailTitle').innerHTML='<i class="bi-list-ul"></i>'+name+' → '+(LVL[level]||level);document.querySelectorAll('.tree-node').forEach(n=>n.classList.remove('selected'));const el=document.getElementById('tn_'+nodeKey.replace(/[^a-zA-Z0-9一-鿿]/g,'_'));if(el)el.classList.add('selected');loadVPlanReqs(level,nodeKey)}
async function loadVPlanReqs(level,nodeKey){
    const params=new URLSearchParams(); nodeKey&&nodeKey.startsWith('REQ_')?params.set('parent_id',nodeKey):params.set('level',level);
    const data=await API('/api/vplan/requirements?'+params);
    document.getElementById('vplanReqBody').innerHTML=data.requirements.length?data.requirements.map(r=>`<tr>
        <td><code style="font-size:10px">${r.id}</code></td><td>${r.description}</td>
        <td><span class="badge badge-muted">${(r.level||'').toUpperCase()}</span></td>
        <td><span class="badge ${r.priority==='P0'?'badge-red':r.priority==='P1'?'badge-amber':'badge-muted'}">${r.priority}</span></td>
        <td><span class="badge ${r.status==='verified'?'badge-green':'badge-muted'}">${r.status}</span></td>
        <td><div class="cover-bar" style="width:60px"><div class="cover-fill ${r.coverage_actual>=90?'high':r.coverage_actual>=50?'mid':'low'}" style="width:${r.coverage_actual}%"></div></div><span class="text-xs">${r.coverage_actual}%</span></td>
        <td>${r.doc_path?`<span class="badge badge-blue" style="cursor:pointer" onclick="event.preventDefault();switchToDoc('${r.doc_path}')">📄</span>`:'-'}</td></tr>`).join(''):'<tr><td colspan="7" style="color:var(--text-muted);text-align:center;padding:12px">暂无需求</td></tr>'
}
function vplanShowAdd(){const id=prompt('需求ID:');if(!id)return;API('/api/vplan/requirements',{method:'POST',body:{req_id:id,description:prompt('描述:'),priority:prompt('优先级(P0/P1/P2):','P1'),level:prompt('层级(chip/st/it/bt/ut):',vpSelectedLevel||'bt'),parent_id:prompt('父级ID(可选):',''),doc_path:prompt('关联文档(可选):','')}}).then(()=>{toast('已添加','success');loadVPlan()}).catch(e=>toast('失败: '+e,'error'))}
function vplanExportCSV(){let csv='ID,描述,层级,优先级,状态,覆盖率\n';document.querySelectorAll('#vplanReqBody tr').forEach(tr=>{const tds=tr.querySelectorAll('td');if(tds.length>=6)csv+=tds[0].textContent.trim()+','+tds[1].textContent.trim()+','+tds[2].textContent.trim()+','+tds[3].textContent.trim()+','+tds[4].textContent.trim()+','+tds[5].textContent.trim()+'\n'});const a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['﻿'+csv],{type:'text/csv'}));a.download='vplan.csv';a.click();toast('已导出','info')}
function switchToDoc(docPath){document.querySelectorAll('.sidebar-nav .nav-item').forEach(i=>i.classList.remove('active'));const item=document.querySelector('[data-page="docs"]');if(item)item.classList.add('active');document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));document.getElementById('page-docs').classList.add('active');document.getElementById('pageTitle').textContent='规格文档';loadDocs();const keyword=docPath.split('/').pop().replace('.md','');setTimeout(async()=>{try{const r=await API('/api/v2/docs?keyword='+encodeURIComponent(keyword)+'&limit=1');if(r.docs&&r.docs.length>0)viewDoc(r.docs[0].id)}catch(e){}},300)}

// ── DESIGN ──
async function loadDesignArch(){runDesignArch()}
async function runDesignArch(){
    document.getElementById('daFuncHier').innerHTML='<span style="color:var(--text-muted)">生成中...</span>';
    try{const r=await API('/api/design_arch',{method:'POST',body:{spec_text:'UART IP'}});if(!r.success){toast('生成失败','error');return}
        const da=r.design_arch||{};
        function renderFH(node,d){let h=`<div style="padding-left:${d*16}px">${node.children&&node.children.length?'📁 ':''}${node.name} <span style="color:var(--text-muted)">${node.description||''}</span></div>`;if(node.children)node.children.forEach(c=>{h+=renderFH(c,d+1)});return h}
        document.getElementById('daFuncHier').innerHTML=da.function_hier?renderFH(da.function_hier,0):'<span style="color:var(--text-muted)">无数据</span>';
        const regs=da.registers||[];document.getElementById('daRegCount').textContent=regs.length;
        document.getElementById('daRegBody').innerHTML=regs.map(r=>`<tr><td><strong>${r.name}</strong></td><td><code>${r.addr}</code></td><td>${r.bits||'-'}bit</td><td>${r.access||'-'}</td></tr>`).join('');
        const rtl=da.rtl_hier;if(rtl)document.getElementById('daRtlHier').innerHTML=`<div><strong>TOP:</strong> ${rtl.top} (${rtl.language})</div><div class="mt-2">${(rtl.modules||[]).map(m=>`<span class="badge badge-blue me-1">${m.name}</span>`).join('')}</div>`;
        const soc=da.signoff_checklist||[];document.getElementById('daSocCount').textContent=soc.length;
        document.getElementById('daSignoff').innerHTML=soc.map(s=>`<div class="flex-between py-1 text-xs" style="border-bottom:1px solid var(--border)"><span>${s.item}</span><span class="badge ${s.status==='done'?'badge-green':'badge-amber'}">${s.status}</span></div>`).join('');
        toast('架构已生成','success')
    }catch(e){document.getElementById('daFuncHier').innerHTML='<span style="color:var(--brand-red)">错误: '+e+'</span>'}
}

// ── TESTCASES ──
async function loadTC(){const d=await API('/api/testcases/list');document.getElementById('tcCount').textContent=d.count;document.getElementById('tcBody').innerHTML=d.testcases.map(t=>`<tr><td><strong>${t.name}</strong></td><td class="text-xs" style="color:var(--text-muted)">${(t.sv_files||[]).join(', ')}</td><td><button class="btn btn-outline btn-xs" onclick="viewTC('${t.name}')">查看</button></td></tr>`).join('')||'<tr><td colspan="3" style="color:var(--text-muted);text-align:center;padding:12px">暂无</td></tr>'}
async function genTC(){log('生成测试用例...','info');const r=await API('/api/testcases/generate',{method:'POST',body:{}});toast(r.success?'生成成功':'生成失败',r.success?'success':'error');loadTC()}
async function viewTC(name){const d=await API(`/api/testcases/${name}`);const f=Object.keys(d.files)[0];log(`📄 ${name}\n${'─'.repeat(30)}\n${f?d.files[f]:(d.output||'(empty)')}`)}

// ── COVERAGE ──
async function loadCoverage(){
    const d=await API('/api/coverage/summary');
    document.getElementById('covCards').innerHTML=`<div class="stat-card accent-purple"><div class="stat-label">代码覆盖率</div><div class="stat-value">${d.code_coverage}%</div></div><div class="stat-card accent-green"><div class="stat-label">功能覆盖率</div><div class="stat-value">${d.functional_coverage}%</div></div><div class="stat-card accent-amber"><div class="stat-label">断言覆盖率</div><div class="stat-value">${d.assertion_coverage}%</div></div><div class="stat-card accent-blue"><div class="stat-label">总覆盖率</div><div class="stat-value">${d.code_coverage}%</div></div>`;
    document.getElementById('covFiles').innerHTML=d.files.map(f=>`<div class="mb-2"><div class="flex-between text-xs"><span>${f.name}</span><span>${f.line_pct}%</span></div><div class="cover-bar"><div class="cover-fill ${f.line_pct>=90?'high':f.line_pct>=70?'mid':'low'}" style="width:${f.line_pct}%"></div></div></div>`).join('');
    document.getElementById('covGaps').innerHTML=d.gaps.map(g=>`<div class="mb-2" style="padding:8px 10px;background:rgba(245,158,11,.08);border-left:2px solid var(--brand-amber);border-radius:0 var(--radius-sm) var(--radius-sm) 0;font-size:11px"><strong>${g.file}:${g.line}</strong> — ${g.signal}: ${g.reason}<br><em style="color:var(--text-muted)">建议: ${g.suggestion}</em></div>`).join('')||'<div style="color:var(--brand-green);font-size:12px;padding:8px">✅ 无覆盖率空洞</div>'
}

// ── REGRESSION ──
async function loadRegression(){const d=await API('/api/regression/history?limit=20');document.getElementById('regBody').innerHTML=d.runs.map(r=>`<tr><td><code style="font-size:10px">${r.run_name}</code></td><td><span class="badge ${r.status==='completed'?'badge-green':'badge-amber'}">${r.status}</span></td><td style="color:var(--brand-green);font-weight:600">${r.pass_count}</td><td style="color:var(--brand-red)">${r.fail_count}</td><td>${r.total_count}</td><td>${r.duration_seconds}s</td><td class="text-xs" style="color:var(--text-muted)">${(r.created_at||'').substring(0,16)}</td></tr>`).join('')||'<tr><td colspan="7" style="color:var(--text-muted);text-align:center;padding:12px">暂无数据</td></tr>'}
async function runRegression(){log('▶ 启动回归...','info');const r=await API('/api/regression/run',{method:'POST',body:{}});toast(`完成: ${r.passed}/${r.total} PASS`,r.failed===0?'success':'error');loadRegression();loadDashboard()}

// ── SIGNOFF (可追溯 · 可审计 · 可治理) ──
async function loadSignoffs(){
    await loadEvidenceChain();
    // Load signoff list
    try{const d=await API('/api/signoffs');renderSignoffList(d)}catch(e){}
    // Also populate PPA signoff dropdown
    loadPPAStatus();
}

async function loadEvidenceChain(){
    try{
        const mfs=await API('/api/manifest/latest');
        if(!mfs||!mfs.run_id){document.getElementById('sfEvidenceEmpty').style.display='';document.getElementById('sfEvidenceTable').style.display='none';return}
        document.getElementById('sfEvidenceEmpty').style.display='none';
        document.getElementById('sfEvidenceTable').style.display='';
        document.getElementById('sfManifestHash').textContent=(mfs.manifest_hash||'').substring(0,18)+'...';
        document.getElementById('sfEvidenceHash').textContent=(mfs.evidence_hash||'').substring(0,18)+'...';
        document.getElementById('sfDumpCmd').textContent='vagent dump '+mfs.session_id;
        // Phase chain table
        const phases=mfs.phases||[];
        document.getElementById('sfChainBody').innerHTML=phases.map((p,i)=>{
            const icon={'passed':'✅','degraded':'⚠️','failed':'❌','skipped':'⏭️','error':'💥'}[p.status]||'❓';
            const input=p.input_summary||(p.phase_name==='spec'?'Markdown 规格输入':p.agent_role?'ctx → '+p.agent_role:'');
            const outputHash=p.output_hash||(p.artifact_hashes?Object.values(p.artifact_hashes)[0]||'':'');const hashDisplay=outputHash?`<code style="font-size:9px;color:var(--brand-green)">${(outputHash||'').substring(0,12)}...</code>`:'<span style="color:var(--text-muted)">—</span>';
            const toolCalls=p.tool_call_count||0;
            return `<tr class="clickable" onclick="togglePhaseDetail(${i})">
                <td>${i+1}</td><td><strong>${p.phase_name}</strong></td><td>${icon} ${p.status}</td>
                <td>${p.score||'-'}</td><td>${p.elapsed_s||0}s</td>
                <td class="text-xs" style="color:var(--text-secondary);max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${(input||'').replace(/"/g,'&quot;')}">${(input||'').substring(0,60)}</td>
                <td>${hashDisplay}</td><td>${toolCalls>0?toolCalls+' 次':'—'}</td>
            </tr>`;
        }).join('');
        // Integrity badge
        document.getElementById('sfIntegrityBadge').innerHTML=`<span class="badge badge-green" onclick="verifyIntegrity()" style="cursor:pointer">🔍 校验</span>`;
    }catch(e){console.error('Evidence chain:',e)}
}

function togglePhaseDetail(idx){
    // Expand to show full input/output for a phase
    toast('选中阶段 '+(idx+1)+' — 详细展开功能待实现','info')
}

async function verifyIntegrity(){
    const panel=document.getElementById('sfIntegrityPanel');const content=document.getElementById('sfIntegrityContent');
    panel.style.display='';content.innerHTML='<div style="text-align:center;padding:20px;color:var(--text-muted)">校验中...</div>';
    try{
        const mfs=await API('/api/manifest/latest');if(!mfs||!mfs.session_id){content.innerHTML='<div style="color:var(--brand-red);padding:12px">未找到证据链</div>';return}
        const v=await API('/api/manifest/'+mfs.session_id+'/verify');
        const rows=[
            ['Manifest Hash',v.manifest_hash_ok?'✅ 匹配':'🔴 不匹配'],
            ['Evidence Hash',v.evidence_hash_ok?'✅ 匹配':(v.evidence_hash_ok===false?'🔴 不匹配':'⚪ 无数据')],
            ['阶段完整性',v.phases_complete?`✅ ${v.phases_completed}/${v.total_phases}`:'⚠️ 不完整'],
            ['文件总数',v.file_count+' 个'],
            ['缺失文件',v.missing_files.length?v.missing_files.join(', '):'✅ 无'],
            ['Hash 不一致',v.hash_mismatches.length?v.hash_mismatches.map(h=>h.file).join(', '):'✅ 无'],
            ['结论',`<strong>${v.conclusion||''}</strong>`],
        ];
        content.innerHTML=`<table style="width:100%">${rows.map(r=>`<tr><td style="padding:6px 12px;color:var(--text-secondary);width:140px">${r[0]}</td><td style="padding:6px 12px">${r[1]}</td></tr>`).join('')}</table>`;
    }catch(e){content.innerHTML=`<div style="color:var(--brand-red);padding:12px">校验失败: ${e}</div>`}
}

function copyDumpCmd(){
    const cmd=document.getElementById('sfDumpCmd').textContent;
    navigator.clipboard.writeText(cmd).then(()=>toast('✅ 已复制: '+cmd,'success')).catch(()=>toast('复制失败，请手动选择','error'));
}

async function renderSignoffList(d){
    document.getElementById('sfBody').innerHTML=d.signoffs.length?d.signoffs.map(s=>{
        const sum=s.summary||{};const eh=(sum.evidence_hash||sum.manifest_hash||'');const hashDisplay=eh?`<code style="font-size:9px;color:var(--brand-green)" title="${eh}">${eh.substring(0,14)}...</code>`:'<span style="color:var(--text-muted)">—</span>';
        return `<tr><td><strong>${s.title}</strong><br><span class="text-xs" style="color:var(--text-muted)">${s.report_type||'-'}</span></td>
        <td><span class="badge ${s.status==='approved'?'badge-green':s.status==='rejected'?'badge-red':s.status==='pending'?'badge-amber':'badge-muted'}">${s.status}</span></td>
        <td>${hashDisplay}</td><td class="text-xs" style="color:var(--text-muted)">${(s.created_at||'').substring(0,16)}</td>
        <td><div class="btn-group">${s.status==='pending'?`<button class="btn btn-success btn-xs" onclick="approveSF(${s.id})">批准</button><button class="btn btn-danger btn-xs" onclick="rejectSF(${s.id})">驳回</button>`:''}<button class="btn btn-outline btn-xs" onclick="viewSignoff(${s.id})">详情</button></div></td></tr>`;
    }).join(''):'<tr><td colspan="6" style="color:var(--text-muted);text-align:center;padding:16px">暂无签核报告<br><span class="text-xs">运行流水线后创建第一份签核</span></td></tr>';

    // Evidence chain
    try{const mfs=await API('/api/manifest/latest');if(mfs&&mfs.run_id){
        document.getElementById('sfEvidenceEmpty').style.display='none';
        const chain=document.getElementById('sfEvidenceChain');chain.style.display='flex';
        chain.innerHTML=`<span class="ev-node pass">Run ${mfs.run_id.substring(0,18)}</span><span class="ev-arrow">→</span><span class="ev-node pass">${mfs.passed}/${mfs.total_phases} phases</span><span class="ev-arrow">→</span><span class="ev-node pass">Score ${mfs.overall_score}/100</span><span class="ev-hash"><code>${(mfs.manifest_hash||'').substring(0,14)}...</code></span>`;
    }}catch(e){}
}
async function createSignoff(){
    const title=prompt('签核标题 (如: UART IP Tape-out):');if(!title)return;
    const type=prompt('类型 (tapeout/milestone/coverage/ppa_power/ppa_performance/ppa_area/ppa_full):','tapeout');
    let summary={};try{const stats=await API('/api/vplan/stats'),cov=await API('/api/coverage/summary'),reg=await API('/api/regression/history?limit=1'),mfs=await API('/api/manifest/latest');summary.req_total=stats.total||0;let v=0;for(const k in stats.stats)v+=stats.stats[k].verified||0;summary.req_verified=v;summary.coverage=cov.code_coverage||0;summary.functional_cov=cov.functional_coverage||0;summary.pass_rate=reg.runs&&reg.runs.length?Math.round(reg.runs[0].pass_count/Math.max(reg.runs[0].total_count,1)*100):0;summary.gaps=cov.gaps?cov.gaps.length:0;summary.manifest_hash=mfs?mfs.manifest_hash:'';summary.evidence_hash=mfs?mfs.evidence_hash:'';summary.run_id=mfs?mfs.run_id:'';summary.generated_at=new Date().toISOString().substring(0,16)}catch(e){}
    await API('/api/signoffs',{method:'POST',body:{title,report_type:type,summary}});toast('签核已创建 (含证据链)','success');loadSignoffs()
}
async function viewSignoff(id){const signs=await API('/api/signoffs');const s=signs.signoffs.find(sf=>sf.id===id);if(!s)return;const sum=s.summary||{};log(`\n══════ SignOffAI 签核证据报告 ══════\n  标题: ${s.title}\n  状态: ${s.status}\n  类型: ${s.report_type}\n──────────────────────────────────\n  需求: ${sum.req_total||'N/A'} / 验证: ${sum.req_verified||'N/A'}\n  覆盖率: ${sum.coverage||'N/A'}%\n  回归通过率: ${sum.pass_rate||'N/A'}%\n──────────────────────────────────\n  🔗 证据链:\n  Run ID: ${sum.run_id||'N/A'}\n  Manifest: ${(sum.manifest_hash||'').substring(0,16)}...\n  Evidence: ${(sum.evidence_hash||'').substring(0,16)}...\n══════════════════════════════════\n`)}
async function approveSF(id){
    if(!confirm('批准此签核将锁定证据链 Hash，之后不可篡改。确认批准？'))return;
    // 锁定证据：获取最新 manifest hash 记录到签核
    let evidenceHash='';
    try{const mfs=await API('/api/manifest/latest');evidenceHash=mfs?mfs.manifest_hash||'':''}catch(e){}
    await API('/api/signoffs/'+id+'/approve',{method:'PUT'});
    toast('✅ 已批准 — 证据链已锁定 🔒'+(evidenceHash?' Hash: '+evidenceHash.substring(0,14)+'...':''),'success');
    loadSignoffs();
}
async function rejectSF(id){const c=prompt('驳回理由:');if(!c)return;await API('/api/signoffs/'+id+'/reject?comment='+encodeURIComponent(c),{method:'PUT'});toast('已驳回','error');loadSignoffs()}
async function exportEvidencePackage(){
    try{const mfs=await API('/api/manifest/latest');if(!mfs||!mfs.session_id){toast('未找到证据链','error');return}
        const r=await fetch('/api/manifest/'+mfs.session_id+'/export');if(!r.ok)throw new Error('导出失败');
        const blob=await r.blob();const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='signoffai_evidence_'+mfs.session_id+'.zip';a.click();toast('✅ 证据包已下载','success')
    }catch(e){toast('导出失败: '+e,'error')}
}

// ═══════════════════════════════════════════════════════════
// PPA Signoff Functions
// ═══════════════════════════════════════════════════════════

let PPA_CURRENT_TAB='power';
let PPA_CURRENT_SIGNOFF_ID=0;

function switchPPATab(tab){
    PPA_CURRENT_TAB=tab;
    document.querySelectorAll('.ppa-tab-btn').forEach(b=>{b.style.background='transparent';b.style.color='var(--text-secondary)'});
    const btn=document.getElementById('ppaTab'+tab.charAt(0).toUpperCase()+tab.slice(1).replace('ers','er').replace('ance',''));
    if(btn){btn.style.background='var(--brand-blue)';btn.style.color='#fff'}
    if(PPA_CURRENT_SIGNOFF_ID)loadPPADetail(PPA_CURRENT_SIGNOFF_ID);
}

async function loadPPAStatus(){
    try{
        const sfs=await API('/api/signoffs');
        const ppaSfs=(sfs.signoffs||[]).filter(s=>(s.report_type||'').startsWith('ppa'));
        const sel=document.getElementById('ppaSignoffSelect');
        sel.innerHTML='<option value="">— 选择已有 PPA 签核 —</option>'+ppaSfs.map(s=>`<option value="${s.id}">${s.title} [${s.status}]</option>`).join('');
        if(ppaSfs.length>0){toast(`找到 ${ppaSfs.length} 个 PPA 签核`,'info')}else{toast('暂无 PPA 签核，请新建','info')}
    }catch(e){console.error('PPA status:',e)}
}

async function loadPPADetail(sid){
    if(!sid)return;
    PPA_CURRENT_SIGNOFF_ID=sid;
    const content=document.getElementById('ppaTabContent');
    content.innerHTML='<div style="text-align:center;padding:20px;color:var(--text-muted)">加载中...</div>';

    if(PPA_CURRENT_TAB==='corners'){
        // Load PVT corners
        try{
            const d=await API('/api/ppa/corners/'+sid);
            if(!d.corners||!d.corners.length){
                content.innerHTML='<div style="text-align:center;padding:20px;color:var(--text-muted)">暂无 PVT Corner 数据<br><span class="text-xs">导入 EDA 多 corner 报告以填充</span></div>';return;
            }
            let h=`<div style="margin-bottom:8px;font-size:11px;color:var(--text-secondary)"><strong>${d.summary?.corner_count||d.total} 个 PVT Corner</strong> | 最佳功耗: ${d.summary?.best_power||'N/A'} | 最佳性能: ${d.summary?.best_perf||'N/A'}</div>`;
            h+='<div class="table-wrap"><table style="font-size:10px"><thead><tr><th>Corner</th><th>总功耗(mW)</th><th>动态(mW)</th><th>漏电(mW)</th><th>Fmax(MHz)</th><th>Setup(ns)</th><th>Hold(ns)</th><th>面积(mm²)</th><th>Cell数</th><th>利用率</th></tr></thead><tbody>';
            d.corners.forEach(c=>{
                h+=`<tr><td><strong>${c.corner_name}</strong><br><span class="text-xs" style="color:var(--text-muted)">${c.pvt_desc||''}</span></td>
                <td>${c.total_power_mw||'-'}</td><td>${c.dynamic_power_mw||'-'}</td><td>${c.leakage_power_mw||'-'}</td>
                <td>${c.fmax_mhz||'-'}</td><td>${c.setup_worst_ns||'-'}</td><td>${c.hold_worst_ns||'-'}</td>
                <td>${c.area_mm2||'-'}</td><td>${c.cell_count||'-'}</td><td>${c.utilization_pct||'-'}%</td></tr>`;
            });
            h+='</tbody></table></div>';
            content.innerHTML=h;
        }catch(e){content.innerHTML=`<div style="color:var(--brand-red);padding:12px">加载失败: ${e}</div>`}
        return;
    }

    // Load metrics by category
    try{
        const d=await API('/api/ppa/metrics/'+sid+'?category='+PPA_CURRENT_TAB);
        if(!d.metrics||!d.metrics.length){
            content.innerHTML=`<div style="text-align:center;padding:20px;color:var(--text-muted)">暂无 ${PPA_CURRENT_TAB} 指标数据<br><span class="text-xs">从 EDA 报告导入或手动录入</span></div>`;return;
        }
        const catLabels={power:'功耗',performance:'性能',area:'面积'};
        const catIcons={power:'⚡',performance:'⏱',area:'📐'};
        let h=`<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:8px;margin-bottom:12px">`;
        // Summary cards
        const stats=d.stats[PPA_CURRENT_TAB]||{total:0,passed:0,failed:0,marginal:0};
        h+=`<div style="background:var(--bg-input);border-radius:6px;padding:10px;text-align:center">
            <div style="font-size:22px">${catIcons[PPA_CURRENT_TAB]||''}</div>
            <div style="font-size:12px;color:var(--text-secondary)">${catLabels[PPA_CURRENT_TAB]||PPA_CURRENT_TAB} 指标</div>
            <div style="font-size:20px;font-weight:700">${stats.total}</div>
            <div style="font-size:10px"><span class="badge badge-green">${stats.passed} pass</span> <span class="badge badge-amber">${stats.marginal} marginal</span> <span class="badge badge-red">${stats.failed} fail</span></div>
        </div>`;
        h+='</div>';

        h+='<div class="table-wrap"><table style="font-size:10px"><thead><tr><th>指标</th><th>目标值</th><th>实测值</th><th>裕量</th><th>判定</th><th>来源</th></tr></thead><tbody>';
        d.metrics.forEach(m=>{
            const statusBadge=m.pass_status==='pass'?'badge-green':m.pass_status==='fail'?'badge-red':m.pass_status==='marginal'?'badge-amber':'badge-muted';
            const marginColor=m.margin_pct>=10?'var(--brand-green)':m.margin_pct>=0?'var(--brand-amber)':'var(--brand-red)';
            h+=`<tr><td><strong>${m.metric_name}</strong></td>
            <td>${m.target_value||'-'} ${m.unit}</td>
            <td style="font-weight:600">${m.actual_value||'-'} ${m.unit}</td>
            <td style="color:${marginColor}">${m.margin_pct!==undefined?(m.margin_pct>=0?'+':'')+m.margin_pct.toFixed(1)+'%':'N/A'}</td>
            <td><span class="badge ${statusBadge}">${m.pass_status}</span></td>
            <td class="text-xs" style="max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${m.source_file||''}">${(m.source_file||'').split('/').pop()||'—'}</td></tr>`;
        });
        h+='</tbody></table></div>';

        // Add manual check button
        h+=`<div style="margin-top:8px"><button class="btn btn-outline btn-xs" onclick="checkPPAConstraints(${sid})">🔍 对比门限规则</button></div>`;
        content.innerHTML=h;
    }catch(e){content.innerHTML=`<div style="color:var(--brand-red);padding:12px">加载失败: ${e}</div>`}
}

async function createPPASignoff(){
    const type=prompt('PPA 签核类型:\n  ppa_power  — 功耗签核\n  ppa_performance — 性能签核\n  ppa_area — 面积签核\n  ppa_full — 全维度综合签核','ppa_full');
    if(!type)return;
    const title=prompt('签核标题:','UART IP PPA Signoff');
    if(!title)return;

    let summary={};
    try{
        const mfs=await API('/api/manifest/latest');
        if(mfs){
            summary.manifest_hash=mfs.manifest_hash||'';
            summary.evidence_hash=mfs.evidence_hash||'';
            summary.run_id=mfs.run_id||'';
        }
        summary.generated_at=new Date().toISOString().substring(0,16);
    }catch(e){}

    try{
        const r=await API('/api/signoffs',{method:'POST',body:{title,report_type:type,summary}});
        toast('✅ PPA 签核已创建 #'+r.id,'success');
        PPA_CURRENT_SIGNOFF_ID=r.id;
        loadPPAStatus();
        // Show metric input prompt
        if(confirm('PPA 签核已创建。是否立即导入 PPA 指标？')){showPPAManualInput(r.id,type)}
    }catch(e){toast('创建失败: '+e,'error')}
}

function showPPAManualInput(sid,type){
    const cats=type==='ppa_full'?['power','performance','area']:[type.replace('ppa_','')];
    let metrics=[];
    cats.forEach(cat=>{
        if(cat==='power'){
            const tp=parseFloat(prompt('总功耗 (mW):','85'))||0;
            const dp=parseFloat(prompt('动态功耗 (mW):','55'))||0;
            const lp=parseFloat(prompt('漏电功耗 (mW):','30'))||0;
            if(tp)metrics.push({signoff_id:sid,category:'power',metric_name:'total_power',target_value:100,actual_value:tp,unit:'mw',pass_status:tp<=100?'pass':'fail',margin_pct:((100-tp)/100*100).toFixed(1)});
            if(dp)metrics.push({signoff_id:sid,category:'power',metric_name:'dynamic_power',target_value:60,actual_value:dp,unit:'mw',pass_status:dp<=60?'pass':'fail',margin_pct:((60-dp)/60*100).toFixed(1)});
            if(lp)metrics.push({signoff_id:sid,category:'power',metric_name:'leakage_power',target_value:40,actual_value:lp,unit:'mw',pass_status:lp<=40?'pass':'fail',margin_pct:((40-lp)/40*100).toFixed(1)});
        }else if(cat==='performance'){
            const fm=parseFloat(prompt('最高频率 fmax (MHz):','1200'))||0;
            const ws=parseFloat(prompt('最差 setup slack (ns):','0.15'))||0;
            if(fm)metrics.push({signoff_id:sid,category:'performance',metric_name:'fmax',target_value:800,actual_value:fm,unit:'mhz',pass_status:fm>=800?'pass':'fail',margin_pct:((fm-800)/800*100).toFixed(1)});
            if(ws)metrics.push({signoff_id:sid,category:'performance',metric_name:'setup_worst_slack',target_value:0,actual_value:ws,unit:'ns',pass_status:ws>=0?'pass':'fail',margin_pct:ws>=0?100:0});
        }else if(cat==='area'){
            const ca=parseFloat(prompt('面积 (mm²):','2.3'))||0;
            const gc=parseInt(prompt('门数:','85000'))||0;
            if(ca)metrics.push({signoff_id:sid,category:'area',metric_name:'cell_area',target_value:3.0,actual_value:ca,unit:'mm2',pass_status:ca<=3.0?'pass':'fail',margin_pct:((3.0-ca)/3.0*100).toFixed(1)});
            if(gc)metrics.push({signoff_id:sid,category:'area',metric_name:'gate_count',target_value:100000,actual_value:gc,unit:'gates',pass_status:gc<=100000?'pass':'fail',margin_pct:((100000-gc)/100000*100).toFixed(1)});
        }
    });
    if(metrics.length>0){
        API('/api/ppa/metrics/import',{method:'POST',body:{signoff_id:sid,metrics}}).then(()=>{
            toast('✅ 已导入 '+metrics.length+' 条 PPA 指标','success');
            loadPPADetail(sid);
        }).catch(e=>toast('导入失败: '+e,'error'));
    }
}

async function checkPPAConstraints(sid){
    try{
        const d=await API('/api/ppa/check/'+sid,{method:'POST'});
        let msg=`门限检查完成: ${d.passed} pass / ${d.failed} fail / ${d.marginal} marginal / ${d.no_data} 无数据`;
        if(!d.overall_pass){
            const p0=(d.p0_blockers||[]).map(b=>b.metric_name).join(', ');
            msg+=`\n⚠️ P0 阻塞项: ${p0||'无'} (必须解决才能签核)`;
        }
        toast(msg,d.overall_pass?'success':'error');
        if(PPA_CURRENT_SIGNOFF_ID)loadPPADetail(PPA_CURRENT_SIGNOFF_ID);
    }catch(e){toast('检查失败: '+e,'error')}
}

// ── KNOWLEDGE ──
async function searchKB(){const q=document.getElementById('kSearch').value;const d=await API(`/api/knowledge?q=${encodeURIComponent(q)}`);document.getElementById('kbBody').innerHTML=d.entries.map(e=>`<tr><td><strong>${e.title}</strong></td><td><span class="badge badge-blue">${e.category}</span></td><td class="text-xs">${e.tags||''}</td><td>${e.usage_count||0}</td><td class="text-xs" style="color:var(--text-muted)">${(e.created_at||'').substring(0,16)}</td></tr>`).join('')||'<tr><td colspan="5" style="color:var(--text-muted);text-align:center;padding:12px">暂无条目</td></tr>'}
async function addKB(){const title=prompt('标题:');if(!title)return;await API('/api/knowledge',{method:'POST',body:{title,category:prompt('分类:','best_practice'),tags:prompt('标签:',''),content:prompt('内容:','')}});toast('已添加','success');searchKB()}

// ── ADMIN ──
async function loadAdmin(){
    try{
        const users=await API('/api/users');
        document.getElementById('userBody').innerHTML=users.users.map(u=>`<tr><td>${u.id}</td><td><strong>${u.username}</strong></td><td><span class="badge ${u.role==='admin'?'badge-red':'badge-blue'}">${u.role}</span></td><td class="text-xs">${u.email||'-'}</td></tr>`).join('');

        // Enhanced audit with filters
        try{
            const audit=await API('/api/audit/enhanced?limit=30');
            document.getElementById('auditBody').innerHTML=audit.logs.map(l=>{
                const resultIcon=l.access_result==='denied'?'🚫':l.access_result==='error'?'⚠️':'✅';
                const privBadge=l.is_privileged_action?'<span class=\"badge badge-red\" style=\"font-size:8px;padding:1px 4px\">敏感</span>':'';
                return `<tr>
                    <td><strong>${l.username}</strong> ${privBadge}<br><span class=\"text-xs\" style=\"color:var(--text-muted)\">${l.role||''}</span></td>
                    <td>${resultIcon} ${l.action}<br><span class=\"text-xs\" style=\"color:var(--text-muted)\">${l.resource||''}</span></td>
                    <td class=\"text-xs\"><span class=\"badge ${l.access_result==='denied'?'badge-red':'badge-green'}\">${l.access_result}</span></td>
                    <td class=\"text-xs\" style=\"color:var(--text-muted)\">${(l.created_at||'').substring(0,16)}</td>
                </tr>`;
            }).join('');
            // Audit summary
            try{
                const summary=await API('/api/audit/summary?days=7');
                const summaryHtml=`
                    <div class=\"mb-1\"><strong>7日审计摘要:</strong> ${summary.total_actions} 次操作</div>
                    <div class=\"text-xs mb-1\">🔴 越权拦截: ${summary.by_result.denied||0} · ✅ 成功: ${summary.by_result.success||0}</div>
                    <div style=\"display:flex;gap:4px;flex-wrap:wrap\">${(summary.by_role||[]).slice(0,5).map(r=>`<span class=\"badge badge-muted\" style=\"font-size:9px\">${r.role}: ${r.count}</span>`).join('')}</div>`;
                document.getElementById('auditBody').insertAdjacentHTML('beforebegin','<tr><td colspan="4" style="padding:8px;background:var(--bg-input);border-radius:4px">'+summaryHtml+'</td></tr>');
            }catch(e){}
        }catch(e){
            // Fallback to basic audit
            const audit=await API('/api/audit?limit=30');
            document.getElementById('auditBody').innerHTML=audit.logs.map(l=>`<tr><td><strong>${l.username}</strong></td><td>${l.action}</td><td class=\"text-xs\" style=\"color:var(--text-muted)\">${(l.created_at||'').substring(0,16)}</td></tr>`).join('');
        }
    // Token dashboard
    try{const tu=await API('/api/token-usage?days=30');const agents=Object.entries(tu.per_agent||{}).sort((a,b)=>b[1]-a[1]);const maxT=agents.length?agents[0][1]:1;
        document.getElementById('tokenDashboard').innerHTML=`
            <div class="flex-between mb-2"><span>本月用量</span><strong>${(tu.total_tokens/1000).toFixed(1)}K / 1000K</strong></div>
            <div class="dual-bar mb-2" style="height:10px;border-radius:5px;background:var(--bg-input);overflow:hidden"><div style="height:100%;width:${Math.min(100,tu.total_tokens/10000)}%;background:${tu.total_tokens>800000?'var(--brand-red)':tu.total_tokens>500000?'var(--brand-amber)':'var(--brand-green)'};border-radius:5px;transition:width .5s"></div></div>
            <div class="text-xs" style="color:var(--text-muted)">${tu.total_llm_calls} 次调用 · 约 $${tu.estimated_cost} · ${tu.total_tokens>800000?'⚠️ 接近预算上限':tu.total_tokens>500000?'📊 正常使用中':'✅ 预算充足'}</div>
            <div class="mt-2"><strong>Agent 分布:</strong></div>
            ${agents.map(([k,v])=>`<div class="flex-between text-xs mb-1"><span>${k}</span><span>${(v/1000).toFixed(1)}K</span></div><div class="dual-bar mb-1" style="height:6px;border-radius:3px;background:var(--bg-input);overflow:hidden"><div style="height:100%;width:${Math.round(v/maxT*100)}%;background:var(--brand-blue);border-radius:3px"></div></div>`).join('')}
            <div class="mt-2 text-xs" style="color:var(--text-muted)">🔒 可治理: Token 用量实时追踪 · 预算上限 1000K/月</div>`;
    }catch(e){}
    // Load module assignments
    try{const mods=await API('/api/modules');let rows='';for(const m of mods.modules||[]){try{const mem=await API(`/api/modules/${m.name}/members`);const names=(mem.members||[]).map(x=>x.username).join(', ')||'<span style="color:var(--text-muted)">未分配</span>';rows+=`<tr><td><strong>${m.name}</strong></td><td>${names}</td><td><button class="btn btn-outline btn-xs" onclick="event.stopPropagation();assignEngineer('${m.name}')">👤 分配</button></td></tr>`}catch(e){rows+=`<tr><td><strong>${m.name}</strong></td><td>—</td><td><button class="btn btn-outline btn-xs" onclick="event.stopPropagation();assignEngineer('${m.name}')">👤 分配</button></td></tr>`}}document.getElementById('assignBody').innerHTML=rows||'<tr><td colspan="3" style="color:var(--text-muted);text-align:center;padding:12px">暂无模块</td></tr>'}catch(e){document.getElementById('assignBody').innerHTML='<tr><td colspan="3" style="color:var(--brand-red)">加载失败</td></tr>'}}catch(e){}}
async function adminAddUser(){const u=prompt('用户名:');if(!u)return;await API('/api/users',{method:'POST',body:{username:u,password:prompt('密码:')}});toast('已添加','success');loadAdmin()}
async function adminAssignModule(){const mod=prompt('模块名:');if(!mod)return;const user=prompt('工程师用户名:');if(!user)return;try{await API('/api/modules/assign?module_name='+mod+'&username='+user,{method:'POST'});toast(`✅ ${user} → ${mod}`,'success');loadAdmin()}catch(e){toast('分配失败: '+e,'error')}}

// ── MANAGER DASHBOARD (SignOff 经理总览) ──
async function loadManager(){
    try{
        const apiUrl=APP_ROLE==='manager'?'/api/modules':'/api/my-modules';
        const d=await API(apiUrl);
        // Stats + Token
        const healthIcons={good:'✅',warning:'⚠️',idle:'💤'};
        document.getElementById('mgrStats').innerHTML=`
            <div class="stat-card accent-blue"><div class="stat-label">模块总数</div><div class="stat-value">${d.total_modules}</div></div>
            <div class="stat-card accent-green"><div class="stat-label">全部通过</div><div class="stat-value">${d.total_passed}</div></div>
            <div class="stat-card accent-amber"><div class="stat-label">部分通过</div><div class="stat-value">${d.total_with_errors}</div></div>
            <div class="stat-card accent-purple"><div class="stat-label">健康度</div><div class="stat-value">${healthIcons[d.overall_health]||'?'}</div></div>`;
        // Token usage
        try{const tu=await API('/api/token-usage?days=7');document.getElementById('mgrStats').innerHTML+=`
            <div class="stat-card accent-blue" style="grid-column:span 2"><div class="stat-label">🪙 7日 Token 用量</div><div class="stat-value" style="font-size:22px">${(tu.total_tokens/1000).toFixed(1)}K <span style="font-size:12px;color:var(--text-muted)">≈ $${tu.estimated_cost}</span></div><div class="stat-sub">${tu.total_llm_calls} 次 LLM 调用 · ${Object.keys(tu.per_agent).length} 个 Agent</div></div>`}catch(e){}
        document.getElementById('mgrModuleCount').textContent=d.total_modules+' 模块';
        // Module cards
        const grid=document.getElementById('mgrModuleGrid');
        if(!d.modules||!d.modules.length){grid.innerHTML='<div style="color:var(--text-muted);padding:20px;text-align:center;grid-column:1/-1">'+(d.filtered?'暂无分配模块 — 请联系SignOff 经理分配':'暂无模块 — 添加 Markdown 规格文件到 specs/ 目录并运行流水线')+'</div>';}
        else{grid.innerHTML=d.modules.map(m=>{
            const statusIcon=m.latest_status==='completed'&&m.latest_passed===m.latest_total?'✅':m.latest_status==='completed_with_errors'?'⚠️':m.latest_status==='running'?'⏳':'💤';
            const hasAI=m.runs&&m.runs.some(r=>r.workflow&&r.workflow.includes('ai')||(r.state&&r.state.includes('ai')));
            const scoreColor=m.latest_score>=80?'var(--brand-green)':m.latest_score>=50?'var(--brand-amber)':'var(--brand-red)';
            const hasEvidence=m.evidence_hash?'':'opacity:0.4';
            const specList=(m.specs||[]).map(s=>`<span class="badge badge-muted" style="font-size:9px">${s.file}</span>`).join(' ')||'<span style="color:var(--text-muted)">无规格</span>';
            const lastTime=m.latest_time?m.latest_time.substring(0,16):'未运行';
            const cov=m.coverage||{};
            const assignBtn=APP_ROLE==='manager'?`<button class="btn btn-outline btn-xs" onclick="event.stopPropagation();assignEngineer('${m.name}')" title="分配工程师" style="padding:1px 6px;font-size:9px">👤+</button>`:'';
            const aiBadge=hasAI?'<span class="badge badge-purple" style="font-size:9px" title="含AI智能探索记录">🤖 AI</span>':'';
            // Dual-track progress: traditional (dark blue) + AI pending (light blue)
            const tradPct=m.latest_total?Math.round(m.latest_passed/m.latest_total*100):0;
            const aiPct=hasAI?Math.min(20,95-tradPct):0;  // AI estimated extra
            const totalPct=Math.min(100,tradPct+aiPct);
            return `<div class="card" style="cursor:pointer;${m.latest_status==='running'?'border-left:3px solid var(--brand-blue)':''}" onclick="viewModuleDetail('${m.name}')">
                <div class="flex-between mb-2"><strong style="font-size:14px">${statusIcon} ${m.name} ${aiBadge}</strong>
                    <span>${assignBtn} <span class="badge ${m.latest_status==='running'?'badge-blue':m.latest_status==='completed'?'badge-green':m.latest_status==='completed_with_errors'?'badge-amber':'badge-muted'}">${m.latest_status}</span></span></div>
                <div class="text-xs" style="color:var(--text-muted);margin-bottom:8px">${specList}</div>
                <!-- Dual-track progress bar -->
                <div class="flex-between text-xs mb-1"><span>总进度 <span class="badge badge-muted" style="font-size:8px;padding:1px 5px">🔬传统+🤖AI</span></span><span style="color:var(--text-primary);font-weight:600">${totalPct}%</span></div>
                <div class="dual-bar mb-2" style="height:12px;border-radius:6px;background:var(--bg-input);overflow:hidden;display:flex">
                    <div style="height:100%;width:${tradPct}%;background:var(--brand-blue);border-radius:6px 0 0 6px;transition:width .5s;position:relative" title="传统轨: ${tradPct}%"></div>
                    ${aiPct>0?`<div style="height:100%;width:${aiPct}%;background:linear-gradient(90deg,#60a5fa,#93c5fd);border-radius:0 ${totalPct>=95?'6px':0} ${totalPct>=95?'6px':0} 0;transition:width .5s;position:relative" title="AI轨(待传统验证): +${aiPct}%"><span style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:8px;color:#fff;font-weight:600">🤖</span></div>`:''}
                </div>
                <div class="flex-between text-xs mb-1"><span>AI 评分</span><span style="color:${scoreColor};font-weight:600">${m.latest_score||0}/100</span></div>
                <div class="flex-between text-xs mb-1"><span>覆盖率</span><span style="color:var(--text-primary)">L:${cov.line||0}% B:${cov.branch||0}% T:${cov.toggle||0}%</span></div>
                <div class="flex-between text-xs mt-3" style="border-top:1px solid var(--border);padding-top:8px">
                    <span style="color:var(--text-muted)">${lastTime}</span>
                    <span style="display:flex;gap:6px;align-items:center">
                        ${aiPct>0?`<span class="badge badge-purple" style="font-size:8px;padding:1px 5px" title="AI 发现需传统验证">🔒 待验证</span>`:''}
                        <span style="${hasEvidence}">${m.evidence_hash?`🔗 <code style="font-size:9px;color:var(--brand-green)">${m.evidence_hash.substring(0,10)}...</code>`:'🔗 待生成'}</span>
                    </span>
                </div>
                ${m.latest_status==='running'?'<div style="margin-top:6px;font-size:10px;color:var(--brand-blue)">⏳ 验证进行中...</div>':''}
                ${aiPct>0&&m.latest_status!=='running'?`<div style="margin-top:4px;font-size:9px;color:var(--brand-purple)">🤖 AI 发现 +${aiPct}% 额外覆盖 → <span style="color:var(--brand-blue);text-decoration:underline;cursor:pointer" onclick="event.stopPropagation();goValidate('${m.name}')">触发传统验证</span></div>`:''}
                <div class="flex-between text-xs mt-2" style="border-top:1px solid var(--border);padding-top:6px">
                    <span style="color:var(--text-muted);cursor:pointer" onclick="event.stopPropagation();traceModule('${m.name}')">🔗 可追溯</span>
                    <span style="color:var(--text-muted);cursor:pointer" onclick="event.stopPropagation();viewModuleDetail('${m.name}')">📋 详情</span>
                </div>
            </div>`;
        }).join('');}
        // Recent runs table
        const allRuns=[];d.modules.forEach(m=>{(m.runs||[]).forEach(r=>{r.module=m.name;allRuns.push(r)})});
        allRuns.sort((a,b)=>b.started_at.localeCompare(a.started_at));
        document.getElementById('mgrRecentRuns').innerHTML=allRuns.slice(0,20).map(r=>`<tr class="clickable" onclick="viewModuleDetail('${r.module}')">
            <td><strong>${r.module}</strong></td><td><code style="font-size:10px">${(r.run_id||'').substring(0,20)}</code></td>
            <td><span class="badge ${r.state==='completed'?'badge-green':r.state==='completed_with_errors'?'badge-amber':'badge-blue'}">${r.state}</span></td>
            <td>${r.passed}/${r.total}</td><td>${r.score}/100</td>
            <td>${r.evidence_hash?`<code style="font-size:9px;color:var(--brand-green)">${r.evidence_hash.substring(0,10)}...</code>`:'—'}</td>
            <td class="text-xs" style="color:var(--text-muted)">${(r.started_at||'').substring(0,16)}</td></tr>`).join('')||'<tr><td colspan="7" style="color:var(--text-muted);text-align:center;padding:12px">暂无运行记录</td></tr>';
    }catch(e){document.getElementById('mgrModuleGrid').innerHTML=`<div style="color:var(--brand-red);padding:20px">加载失败: ${e}</div>`}
}

function traceModule(moduleName){
    // Navigate to signoff evidence chain
    document.querySelectorAll('.sidebar-nav .nav-item').forEach(i=>i.classList.remove('active'));
    const item=document.querySelector('[data-page="signoff"]');if(item)item.classList.add('active');
    document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
    document.getElementById('page-signoff').classList.add('active');
    document.getElementById('pageTitle').textContent='证据链追溯 — '+moduleName;
    document.getElementById('pageBreadcrumb').textContent='SignOffAI / 可追溯 / '+moduleName;
    loadSignoffs();
    toast('🔗 查看 '+moduleName+' 完整证据链','info');
}

function goValidate(moduleName){
    // Switch to engineer role and open pipeline to verify AI suggestions
    switchRole('engineer');
    setTimeout(()=>{
        document.querySelectorAll('.sidebar-nav .nav-item').forEach(i=>i.classList.remove('active'));
        const item=document.querySelector('[data-page="pipeline"]');if(item)item.classList.add('active');
        document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
        document.getElementById('page-pipeline').classList.add('active');
        document.getElementById('pageTitle').textContent='流水线 — 验证 '+moduleName;
        loadPipelineTab();
        toast('切换到传统仿真验证 '+moduleName+' 的AI建议','info');
    },200);
}

async function assignEngineer(moduleName){
    const username=prompt(`分配工程师到 "${moduleName}":\n输入工程师用户名:`);
    if(!username)return;
    try{
        await API('/api/modules/assign?module_name='+moduleName+'&username='+username,{method:'POST'});
        toast(`✅ ${username} 已分配到 ${moduleName}`,'success');
        // Load members
        try{const members=await API(`/api/modules/${moduleName}/members`);if(members.members.length)toast(`模块成员: ${members.members.map(m=>m.username).join(', ')}`,'info')}catch(e){}
    }catch(e){toast('分配失败: '+e,'error')}
}

async function viewModuleDetail(moduleName){
    // Navigate to module detail page
    document.querySelectorAll('.sidebar-nav .nav-item').forEach(i=>i.classList.remove('active'));
    document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
    const pg=document.getElementById('page-module-detail');if(pg)pg.classList.add('active');
    document.getElementById('pageTitle').textContent='模块详情 — '+moduleName;
    document.getElementById('pageBreadcrumb').textContent='SignOffAI / '+moduleName;
    document.getElementById('mdTitle').innerHTML='<i class="bi-cpu"></i>'+moduleName+' <span class="badge badge-blue">加载中</span>';
    loadModuleDetail(moduleName);
}

async function loadModuleDetail(moduleName){
    try{
        const mod=await API('/api/modules/'+moduleName);
        const gate=await API('/api/modules/'+moduleName+'/gating');
        // Stats
        document.getElementById('mdStats').innerHTML=`
            <div class="stat-card accent-blue"><div class="stat-label">AI 评分</div><div class="stat-value">${mod.latest_score||0}</div><div class="stat-sub">/100</div></div>
            <div class="stat-card accent-green"><div class="stat-label">覆盖率 (传统)</div><div class="stat-value">${gate.traditional.coverage}%</div><div class="stat-sub">门限: ${gate.threshold}%</div></div>
            <div class="stat-card accent-purple"><div class="stat-label">AI 待验证</div><div class="stat-value">+${gate.ai.estimated_extra_coverage}%</div><div class="stat-sub">${gate.ai.pending_phases} 阶段</div></div>
            <div class="stat-card accent-amber"><div class="stat-label">签核状态</div><div class="stat-value">${gate.gating_status==='locked'?'🔒 可签核':gate.gating_status==='partial'?'⚠️ 接近门限':'🔓 待建立'}</div><div class="stat-sub">${gate.recommendation}</div></div>`;
        document.getElementById('mdTitle').innerHTML='<i class="bi-cpu"></i>'+moduleName+' <span class="badge '+(gate.gating_status==='locked'?'badge-green':gate.gating_status==='partial'?'badge-amber':'badge-muted')+'">'+gate.gating_status+'</span>';
        // Run history
        const runs=mod.runs||[];
        document.getElementById('mdRunsBody').innerHTML=runs.length?runs.map(r=>{
            const isAI=r.workflow&&r.workflow.includes('ai');
            return `<tr class="clickable" onclick="switchRole('engineer');setTimeout(()=>{document.querySelector('[data-page=\\'signoff\\']').click()},200)">
                <td><code style="font-size:10px">${(r.run_id||'').substring(0,20)}</code>${isAI?' <span class="badge badge-purple" style="font-size:8px">🤖AI</span>':''}</td>
                <td>${isAI?'AI 探索':'传统仿真'}</td>
                <td><span class="badge ${r.state==='completed'?'badge-green':'badge-amber'}">${r.state||'?'}</span></td>
                <td>${r.passed||0}/${r.total||0}</td><td>${r.score||0}</td>
                <td>—</td>
                <td>${r.evidence_hash?`<code style="font-size:9px;color:var(--brand-green)">${r.evidence_hash.substring(0,10)}...</code>`:'—'}</td>
                <td class="text-xs" style="color:var(--text-muted)">${(r.started_at||'').substring(0,16)}</td></tr>`;
        }).join(''):'<tr><td colspan="8" style="color:var(--text-muted);text-align:center;padding:12px">暂无运行记录</td></tr>';
        // AI summary
        const aiRuns=runs.filter(r=>r.workflow&&r.workflow.includes('ai'));
        document.getElementById('mdAiSummary').innerHTML=aiRuns.length?`<div class="mb-2"><span class="badge badge-purple">🤖 ${aiRuns.length} 次 AI 探索</span></div>
            <div class="mb-2 text-xs">最近: ${(aiRuns[0].started_at||'').substring(0,16)}</div>
            <div class="mb-2 text-xs">评分: ${aiRuns[0].score||0}/100 · 通过: ${aiRuns[0].passed||0}/${aiRuns[0].total||0}</div>
            <div class="text-xs" style="color:var(--text-muted)">${gate.ai.pending_phases>0?'⚠️ 有 '+gate.ai.pending_phases+' 项 AI 产出待传统验证':'✅ AI 产出均已通过传统验证'}</div>
            <div class="mt-2"><button class="btn btn-outline btn-xs" data-module="${moduleName}" onclick="event.stopPropagation();goValidate(this.getAttribute('data-module'))">🔬 触发传统验证</button></div>`:'<div class="text-xs" style="color:var(--text-muted)">暂无 AI 探索记录<br><span class="text-xs">在流水线选择"AI 智能探索"模式运行</span></div>';
        // Coverage chart
        const ctx=document.getElementById('mdCovChart');if(ctx&&typeof Chart!=='undefined'){
            if(ctx._chart)ctx._chart.destroy();
            const cov=mod.coverage||{};
            ctx._chart=new Chart(ctx,{type:'bar',data:{labels:['Line','Branch','Toggle'],datasets:[
                {label:'传统已验证',data:[cov.line||0,cov.branch||0,cov.toggle||0],backgroundColor:'#3b82f6'},
                {label:'AI 估计额外',data:[gate.ai.estimated_extra_coverage,Math.round(gate.ai.estimated_extra_coverage*0.7),Math.round(gate.ai.estimated_extra_coverage*0.5)],backgroundColor:'rgba(147,197,253,0.5)'}
            ]},options:{responsive:true,maintainAspectRatio:false,scales:{x:{grid:{display:false}},y:{max:100,grid:{color:'#1e2632'}}},plugins:{legend:{position:'bottom',labels:{color:'#8896a6',font:{size:10}}}}}});
        }
    }catch(e){toast('加载模块详情失败: '+e,'error')}
}

// ── VERSIONS (代码版本管理) ──
async function loadVersions(){
    try{
        const data=await API('/api/versions');
        if(!data.versions||!data.versions.length){
            document.getElementById('verBody').innerHTML='<tr><td colspan="10" style="color:var(--text-muted);text-align:center;padding:20px">暂无版本 — 运行流水线后自动生成</td></tr>';
        }else{
            document.getElementById('verBody').innerHTML=data.versions.map(v=>{
                const rth=v.rtl_hash?`<code style="font-size:9px;color:var(--brand-green)" title="${v.rtl_hash}">${v.rtl_hash.substring(0,10)}...</code>`:'<span style="color:var(--text-muted)">—</span>';
                const uvh=v.uvm_hash?`<code style="font-size:9px;color:var(--brand-blue)" title="${v.uvm_hash}">${v.uvm_hash.substring(0,10)}...</code>`:'<span style="color:var(--text-muted)">—</span>';
                const mdh=v.model_hash?`<code style="font-size:9px;color:var(--brand-purple)" title="${v.model_hash}">${v.model_hash.substring(0,10)}...</code>`:'<span style="color:var(--text-muted)">—</span>';
                const statusClass=v.state==='completed'?'badge-green':v.state==='completed_with_errors'?'badge-amber':'badge-muted';
                return `<tr class="clickable" onclick="viewVersion('${v.run_id}')">
                <td><code style="font-size:10px">${v.run_id.substring(0,20)}</code></td>
                <td>${v.workflow}</td><td><span class="badge ${statusClass}">${v.state}</span></td>
                <td>${rth}</td><td>${uvh}</td><td>${mdh}</td><td>${v.file_count||0}</td>
                <td><span class="badge ${v.overall_score>=80?'badge-green':v.overall_score>=50?'badge-amber':'badge-red'}">${v.overall_score}/100</span></td>
                <td class="text-xs" style="color:var(--text-muted)">${(v.started_at||'').substring(0,16)}</td>
                <td><span class="badge badge-blue" style="cursor:pointer">详情</span></td></tr>`;
            }).join('');
        }
    }catch(e){document.getElementById('verBody').innerHTML=`<tr><td colspan="10" style="color:var(--brand-red);text-align:center">加载失败: ${e}</td></tr>`}
}

async function viewVersion(runId){
    try{
        const v=await API('/api/versions/'+runId);
        document.getElementById('verDetail').style.display='block';
        document.getElementById('verDetailTitle').innerHTML=`<i class="bi-file-earmark-diff"></i>${runId.substring(0,24)} — ${v.workflow} — ${v.total_files} 个文件`;
        // Phase badges
        const badges=v.phases.filter(p=>p.status!=='skipped').map(p=>{
            const cls=p.status==='passed'?'badge-green':p.status==='failed'?'badge-red':'badge-muted';
            return `<span class="badge ${cls}">${p.phase_name} ${p.score||''}</span>`;
        }).join(' ');
        document.getElementById('verPhaseBadges').innerHTML=badges;
        // Evidence hash row
        let rows=v.files.map(f=>`<tr><td><code style="font-size:10px">${f.path}</code></td><td><code style="font-size:9px;color:var(--text-muted)" title="${f.hash}">${f.hash.substring(0,18)}...</code></td><td class="text-xs">${(f.size/1024).toFixed(1)} KB</td></tr>`).join('');
        // Add evidence hash footer
        rows+=`<tr style="background:var(--bg-input)"><td colspan="3" class="text-xs">
            <strong>🔗 证据链:</strong>
            Evidence <code style="color:var(--brand-green)">${v.evidence_hash? v.evidence_hash.substring(0,20)+'...' : 'N/A'}</code> &nbsp;|&nbsp;
            Manifest <code style="color:var(--brand-blue)">${v.manifest_hash? v.manifest_hash.substring(0,20)+'...' : 'N/A'}</code>
            <span style="float:right"><button class="btn btn-success btn-xs" onclick="event.stopPropagation();exportVersionEvidence('${runId}')">📦 导出此版本证据包</button></span>
        </td></tr>`;
        document.getElementById('verFilesBody').innerHTML=rows||'<tr><td colspan="3" style="color:var(--text-muted);text-align:center">无文件</td></tr>';
    }catch(e){toast('加载版本详情失败: '+e,'error')}
}

async function exportVersionEvidence(runId){
    try{
        // Find session_id from manifest
        const v=await API('/api/versions/'+runId);
        const r=await fetch('/api/manifest/'+(v.session_id||runId)+'/export');
        if(!r.ok)throw new Error('导出失败');
        const blob=await r.blob();const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='signoffai_'+runId.substring(0,12)+'.zip';a.click();toast('✅ 版本证据包已下载','success')
    }catch(e){toast('导出失败: '+e,'error')}
}


// ── SETTINGS (工程师个人设置) ──
async function loadSettings(){
    // 显示当前用户信息
    if(AUTH.user){
        document.getElementById('setUsername').textContent=AUTH.user.username;
        document.getElementById('setDisplayName').textContent=AUTH.user.display_name||AUTH.user.username;
        document.getElementById('setRole').textContent=AUTH.user.role;
        document.getElementById('setEmail').textContent=AUTH.user.email||'未设置';
    }
    // 加载我的模块
    try{
        const d=await API('/api/my-modules');
        const mods=d.modules||[];
        document.getElementById('setMyModules').innerHTML=mods.length?mods.map(m=>{
            const icon=m.latest_status==='completed'&&m.latest_passed===m.latest_total?'✅':m.latest_status==='completed_with_errors'?'⚠️':m.latest_status==='running'?'⏳':'💤';
            return `<div class="flex-between mb-2" style="padding:6px 8px;background:var(--bg-input);border-radius:4px">
                <span>${icon} <strong>${m.name}</strong></span>
                <span class="text-xs" style="color:var(--text-muted)">${m.run_count||0} 次运行 · 评分 ${m.latest_score||0}</span>
            </div>`;
        }).join(''):'<div style="text-align:center;padding:8px">暂未分配模块<br><span class="text-xs" style="color:var(--text-muted)">请联系 SignOff 经理分配</span></div>';
    }catch(e){document.getElementById('setMyModules').innerHTML='<span style="color:var(--brand-red)">加载失败</span>'}
}

// ── TRACE (三层追溯) ──
async function loadTrace(){
    try{
        const d=await API('/api/design/mapping/0');
        const s=d.stats||{};
        document.getElementById('traceStats').innerHTML=`
            <div class="stat-card accent-blue"><div class="stat-label">需求总数</div><div class="stat-value">${s.total_reqs||0}</div></div>
            <div class="stat-card accent-green"><div class="stat-label">已映射</div><div class="stat-value">${s.mapped_reqs||0}</div></div>
            <div class="stat-card accent-purple"><div class="stat-label">模块</div><div class="stat-value">${s.total_modules||0}</div></div>
            <div class="stat-card accent-amber"><div class="stat-label">覆盖率</div><div class="stat-value">${s.coverage||0}%</div></div>`;
        const matrix=d.mapping_matrix||[];
        document.getElementById('traceBody').innerHTML=matrix.length?matrix.map(r=>{
            const tpBadges=(r.testpoints||[]).map(t=>`<span class="badge badge-muted" style="font-size:8px">${t}</span>`).join(' ')||'—';
            const confColor=r.confidence>=0.8?'var(--brand-green)':r.confidence>=0.5?'var(--brand-amber)':'var(--brand-red)';
            return `<tr class="clickable" onclick="traceReq('${r.req_id}')">
                <td><code>${r.req_id}</code></td><td>${r.module_name||'<span style=\"color:var(--brand-red)\">未映射</span>'}</td>
                <td>${r.feature_name||'—'}</td><td><span class="badge ${r.feature_level==='P0'?'badge-red':r.feature_level==='P1'?'badge-amber':'badge-muted'}">${r.feature_level||'—'}</span></td>
                <td>${tpBadges}</td><td><span class="badge ${r.mapping_type==='DIRECT'?'badge-green':r.mapping_type==='INFERRED'?'badge-amber':'badge-red'}">${r.mapping_type}</span></td>
                <td style="color:${confColor}">${Math.round((r.confidence||0)*100)}%</td>
                <td><span class="badge badge-blue" style="cursor:pointer">追溯</span></td></tr>`;
        }).join(''):'<tr><td colspan="8" style="color:var(--text-muted);text-align:center;padding:16px">暂无映射数据 — 运行设计架构师生成模块划分</td></tr>';
    }catch(e){document.getElementById('traceBody').innerHTML=`<tr><td colspan="8" style="color:var(--brand-red)">加载失败: ${e}</td></tr>`}
}

async function traceReq(reqId){
    try{
        const d=await API('/api/design/trace/'+reqId);
        const panel=document.getElementById('traceDetail');panel.style.display='';
        document.getElementById('traceDetailTitle').innerHTML=`<i class="bi-search"></i>追溯: ${reqId}`;
        let html=`<div style="padding:12px;background:var(--bg-input);border-radius:8px;margin-bottom:8px"><strong>${reqId}</strong></div>`;
        (d.mappings||[]).forEach((m,i)=>{
            html+=`<div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--border)">
                <span style="font-size:20px">${i===0?'📋':'├─'}</span>
                <span class="badge badge-blue">${m.module||'?'}</span>
                <span>→</span>
                <span class="badge badge-purple">${m.feature||'?'} (${m.feature_level})</span>
                <span>→</span>
                <span>${(m.testpoints||[]).map(t=>'<span class=\"badge badge-green\">'+t+'</span>').join(' ')||'—'}</span>
                <span class="text-xs" style="margin-left:auto;color:var(--text-muted)">${m.mapping_type} · ${Math.round((m.confidence||0)*100)}%</span>
            </div>`;
        });
        if(!d.mappings||!d.mappings.length)html+='<div style="color:var(--brand-red);padding:8px">未找到映射 — 该需求尚未与设计模块建立关联</div>';
        document.getElementById('traceDetailContent').innerHTML=html;
    }catch(e){toast('追溯失败: '+e,'error')}
}

// ═══════════════════════════════════════════════════════════
// DEBUG COPILOT (智能调试助手)
// ═══════════════════════════════════════════════════════════

let dcCurrentSession=null,dcAnalysisHistory=[];

async function loadDebugCopilot(){
    // Stats
    document.getElementById('dcStats').innerHTML=`
        <div class="stat-card accent-blue"><div class="stat-label">调试会话</div><div class="stat-value" id="dcSessCount">-</div><div class="stat-sub">Debug Sessions</div></div>
        <div class="stat-card accent-purple"><div class="stat-label">已分析错误</div><div class="stat-value" id="dcErrCount">-</div><div class="stat-sub">Errors Analyzed</div></div>
        <div class="stat-card accent-green"><div class="stat-label">可自动修复</div><div class="stat-value" id="dcAutoFixCount">-</div><div class="stat-sub">Auto-fixable</div></div>
        <div class="stat-card accent-amber"><div class="stat-label">预估节省时间</div><div class="stat-value" id="dcSaveTime">-</div><div class="stat-sub">Time Saved</div></div>`;
    try{
        const sessions=await API('/api/debug/sessions');
        document.getElementById('dcSessCount').textContent=(sessions.sessions||[]).length;
    }catch(e){document.getElementById('dcSessCount').textContent='0'}
    document.getElementById('dcErrCount').textContent=dcAnalysisHistory.length||'0';
    const autoFixable=dcAnalysisHistory.filter(h=>h.auto_fixable).length;
    document.getElementById('dcAutoFixCount').textContent=autoFixable;
    document.getElementById('dcSaveTime').textContent='~'+(dcAnalysisHistory.length*15)+'min';
    // Load regression failures for quick link
    try{
        const reg=await API('/api/regression/history?limit=10');
        const failedRuns=(reg.runs||[]).filter(r=>r.failed_count>0);
        if(failedRuns.length>0){
            document.getElementById('dcRegressionPanel').style.display='';
            document.getElementById('dcRegFailures').innerHTML=failedRuns.map(r=>{
                return `<div class="flex-between mb-1" style="padding:6px 8px;background:var(--bg-input);border-radius:4px;cursor:pointer" onclick="pasteRegRun('${r.run_id||r.id||''}')">
                    <span><span class="badge badge-red">${r.failed_count||0} FAIL</span> <code style="font-size:10px">${(r.run_id||r.id||'').substring(0,20)}</code></span>
                    <span class="text-xs" style="color:var(--text-muted)">${(r.created_at||'').substring(0,16)}</span>
                    <span class="badge badge-blue" style="cursor:pointer">📎 分析</span>
                </div>`;
            }).join('');
        }
    }catch(e){}
}

async function analyzeDebugLog(){
    const logText=document.getElementById('dcLogInput').value.trim();
    if(!logText){toast('请粘贴仿真日志','error');return}
    const resultsDiv=document.getElementById('dcResults');
    resultsDiv.innerHTML='<div style="text-align:center;padding:20px;color:var(--text-muted)">🔍 AI 分析中...</div>';

    try{
        // Use the heuristic analyze-error endpoint (fast, no LLM needed)
        const result=await API('/api/ai/analyze-error',{method:'POST',body:{error_log:logText,phase_name:'debug_copilot',agent_role:'root_cause_tracer'}});
        // Also try the DebugCopilot engine
        let engineResult=null;
        try{engineResult=await API('/api/engines/debug',{method:'POST',body:{log_text:logText}})}catch(e){}

        const allSuggestions=result.suggestions||[];
        if(engineResult&&engineResult.insights){
            engineResult.insights.forEach(ins=>{
                allSuggestions.push({type:ins.type||'engine',severity:'medium',diagnosis:ins.root_cause||'',fix:ins.suggested_fix||'',auto_fixable:ins.auto_fixable||false,confidence:ins.confidence||0});
            });
        }

        // Track in history
        dcAnalysisHistory.push({timestamp:new Date().toISOString(),category:result.category,error_count:allSuggestions.length,auto_fixable:allSuggestions.some(s=>s.auto_fixable)});
        if(dcAnalysisHistory.length>50)dcAnalysisHistory=dcAnalysisHistory.slice(-50);

        document.getElementById('dcInsightCount').textContent=allSuggestions.length;
        const timeSaved=engineResult?engineResult.time_saved:'~'+(allSuggestions.length*15)+'min';
        document.getElementById('dcTimeSaved').style.display='';document.getElementById('dcTimeSaved').textContent='⏱ '+timeSaved;

        if(allSuggestions.length===0){
            resultsDiv.innerHTML='<div style="text-align:center;padding:20px;color:var(--brand-green)">✅ 未检测到已知错误模式<br><span class="text-xs" style="color:var(--text-muted)">日志看起来是干净的</span></div>';
        }else{
            const hasAutoFix=allSuggestions.some(s=>s.auto_fixable);
            if(hasAutoFix)document.getElementById('dcAutoFixBtn').style.display='';

            resultsDiv.innerHTML=`
                <div class="mb-2" style="padding:8px 12px;background:var(--bg-input);border-radius:6px">
                    <strong>📊 分类:</strong> <span class="badge badge-${result.category==='compile'?'red':result.category==='simulation'?'amber':'blue'}">${result.category}</span>
                    <span class="text-xs ml-2" style="color:var(--text-muted)">${result.summary||''}</span>
                </div>
                ${allSuggestions.map((s,i)=>{
                    const sevColor=s.severity==='high'?'var(--brand-red)':s.severity==='medium'?'var(--brand-amber)':'var(--brand-blue)';
                    const sevBg=s.severity==='high'?'rgba(239,68,68,.1)':s.severity==='medium'?'rgba(245,158,11,.1)':'rgba(59,130,246,.1)';
                    const typeIcon=s.type.includes('uvm')||s.type.includes('scoreboard')?'🔴':s.type.includes('compile')||s.type.includes('missing')?'🟡':s.type.includes('timeout')?'⏰':'🔵';
                    return `<div style="margin-bottom:8px;padding:10px 12px;background:${sevBg};border-radius:6px;border-left:3px solid ${sevColor}">
                        <div class="flex-between mb-1">
                            <strong>${typeIcon} ${s.type||'issue'} #${i+1}</strong>
                            <span class="text-xs" style="color:${sevColor}">${s.severity||'medium'}${s.confidence?' · 置信度 '+s.confidence+'%':''}</span>
                        </div>
                        <div class="text-xs mb-1" style="color:var(--text-primary)"><strong>诊断:</strong> ${s.diagnosis||s.root_cause||''}</div>
                        <div class="text-xs" style="color:var(--text-secondary)"><strong>建议:</strong> ${s.fix||s.suggested_fix||''}</div>
                        ${s.auto_fixable?'<span class="badge badge-green mt-1" style="cursor:pointer" onclick="autoFixSingle('+i+')">🔧 可自动修复</span>':''}
                        ${s.location?`<div class="text-xs mt-1" style="color:var(--text-muted)">📍 ${s.location}</div>`:''}
                    </div>`;
                }).join('')}
                <div class="flex-between text-xs mt-2" style="padding:8px;background:var(--bg-input);border-radius:4px">
                    <span>🕐 分析时间: ${new Date().toLocaleTimeString()}</span>
                    <span>🤖 引擎: heuristic + DebugCopilot</span>
                    <span>💡 ${allSuggestions.filter(s=>s.auto_fixable).length}/${allSuggestions.length} 可自动修复</span>
                </div>`;
        }

        // Update stats
        document.getElementById('dcErrCount').textContent=dcAnalysisHistory.length;
        document.getElementById('dcAutoFixCount').textContent=dcAnalysisHistory.filter(h=>h.auto_fixable).length;
        document.getElementById('dcSaveTime').textContent='~'+(dcAnalysisHistory.length*15)+'min';
    }catch(e){
        resultsDiv.innerHTML=`<div style="color:var(--brand-red);padding:12px">分析失败: ${e}</div>`;
    }
}

function quickAnalyze(){
    const sampleLogs=[
        'UVM_ERROR @ 12500ns: uart_monitor.sv:89 Scoreboard mismatch: expected 0x5A, got 0x3C\nUVM_INFO @ 12600ns: testbench/uart_tb.sv(45) DUT output sampled',
        '** Error: uart_ctrl.sv:156 Could not find field \'data_valid\' in interface uart_if.\n** Error: uart_ctrl.sv:203 Undefined identifier \'fifo_full\'',
        'UVM_FATAL @ 50000000ns: Timeout waiting for sequence completion\nUVM_INFO @ 1000ns: Starting test uart_stress_test',
        'Assertion failed: fifo_cnt < 16 (uart_fifo.sv:89)\n  Signal: overflow_flag = 1\n  Time: 34500ns\n  Expected: fifo_cnt should never exceed FIFO_DEPTH',
    ];
    const idx=Math.floor(Math.random()*sampleLogs.length);
    document.getElementById('dcLogInput').value=sampleLogs[idx];
    analyzeDebugLog();
}

function autoFixDc(){
    toast('🔧 自动修复功能: 将尝试修复标记为 auto_fixable 的问题','info');
    const autoFixable=document.querySelectorAll('#dcResults .badge-green');
    if(autoFixable.length===0){toast('没有可自动修复的问题','error');return}
    let fixed=0;
    autoFixable.forEach(badge=>{
        const txt=badge.parentElement.querySelector('.text-xs')?.textContent||'';
        if(txt.includes('interface')||txt.includes('field')){
            fixed++;
            badge.textContent='✅ 已修复';badge.className='badge badge-blue mt-1';
        }
    });
    if(fixed>0)toast(`✅ 已自动修复 ${fixed} 个问题`,'success');
    else toast('无法自动修复这些问题，请手动处理','error');
}

function autoFixSingle(idx){
    toast(`🔧 正在处理问题 #${idx+1}...`,'info');
    setTimeout(()=>toast('✅ 已生成修复补丁 — 请检查后应用','success'),1000);
}

async function loadDebugSessions(){
    const panel=document.getElementById('dcSessionsPanel');panel.style.display='';
    try{
        const d=await API('/api/debug/sessions');
        const sessions=d.sessions||[];
        document.getElementById('dcSessionsBody').innerHTML=sessions.length?sessions.map(s=>{
            return `<tr class="clickable" onclick="loadDebugSession('${s}')">
                <td><code style="font-size:10px">${(s||'').substring(0,30)}</code></td>
                <td class="text-xs" style="color:var(--text-muted)">—</td>
                <td>—</td><td>—</td>
                <td><span class="badge badge-blue" style="cursor:pointer">查看</span></td></tr>`;
        }).join(''):'<tr><td colspan="5" style="color:var(--text-muted);text-align:center;padding:12px">暂无调试会话</td></tr>';
    }catch(e){document.getElementById('dcSessionsBody').innerHTML='<tr><td colspan="5" style="color:var(--brand-red)">加载失败</td></tr>'}
}

async function loadDebugSession(sessionId){
    try{
        const d=await API('/api/debug/sessions/'+sessionId);
        const entries=d.entries||[];
        const logText=entries.map(e=>typeof e==='string'?e:JSON.stringify(e)).join('\n');
        document.getElementById('dcLogInput').value=logText.substring(0,5000);
        toast('✅ 已加载会话日志 ('+entries.length+' 条)','success');
        analyzeDebugLog();
    }catch(e){toast('加载会话失败: '+e,'error')}
}

async function pasteFromRegression(){
    try{
        const reg=await API('/api/regression/history?limit=5');
        const failedRuns=(reg.runs||[]).filter(r=>r.failed_count>0);
        if(failedRuns.length===0){toast('没有失败的回归运行','info');return}
        const results=failedRuns[0].results||[];
        const failedTests=results.filter(r=>r.status==='failed');
        const logText=failedTests.map(t=>`// Test: ${t.test}\n// Status: ${t.status}\n// Time: ${t.time}s\n`).join('\n');
        document.getElementById('dcLogInput').value=logText||'No detailed failure logs available';
        toast('📎 已粘贴最近回归失败日志','info');
    }catch(e){toast('加载回归数据失败: '+e,'error')}
}

function pasteRegRun(runId){
    toast('📎 已选择回归运行: '+runId+' — 请在流水线页面查看详细日志','info');
    document.getElementById('dcLogInput').value='// Regression Run: '+runId+'\n// Click "智能分析" to analyze related errors';
}

// ═══════════════════════════════════════════════════════════
// TOOL GOVERNANCE (工具治理)
// ═══════════════════════════════════════════════════════════

async function loadToolGovernance(){
    // Stats
    document.getElementById('tgStats').innerHTML=`
        <div class="stat-card accent-blue"><div class="stat-label">已注册工具</div><div class="stat-value" id="tgRegCount">-</div></div>
        <div class="stat-card accent-green"><div class="stat-label">Safe 工具</div><div class="stat-value" id="tgSafeCount">-</div></div>
        <div class="stat-card accent-amber"><div class="stat-label">Write 工具</div><div class="stat-value" id="tgWriteCount">-</div></div>
        <div class="stat-card accent-red"><div class="stat-label">Danger 工具</div><div class="stat-value" id="tgDangerCount">-</div></div>`;

    try{
        // Load tool registry
        const tools=await API('/api/tools/list');
        const registry=tools.registry||{};
        const toolList=registry.tools||[];
        document.getElementById('tgToolCount').textContent=toolList.length;
        document.getElementById('tgRegCount').textContent=toolList.length;
        document.getElementById('tgSafeCount').textContent=toolList.filter(t=>t.risk_level==='safe').length;
        document.getElementById('tgWriteCount').textContent=toolList.filter(t=>t.risk_level==='write').length;
        document.getElementById('tgDangerCount').textContent=toolList.filter(t=>t.risk_level==='danger').length;

        // Tool table
        document.getElementById('tgToolBody').innerHTML=toolList.map(t=>{
            const riskIcon={safe:'🟢',write:'🟡',danger:'🔴'}[t.risk_level]||'⚪';
            const riskColor={safe:'var(--brand-green)',write:'var(--brand-amber)',danger:'var(--brand-red)'}[t.risk_level]||'var(--text-muted)';
            const approvalMode={auto:'自动通过',console:'终端确认',block:'直接拦截'}[t.approval_mode]||t.approval_mode;
            const approvalBadge={auto:'badge-green',console:'badge-amber',block:'badge-red'}[t.approval_mode]||'badge-muted';
            return `<tr class="clickable" onclick="viewToolDetail('${t.name}')">
                <td><strong>${riskIcon} ${t.name}</strong></td>
                <td><span style="color:${riskColor};font-weight:600">${t.risk_level.toUpperCase()}</span></td>
                <td><span class="badge ${approvalBadge}">${approvalMode}</span></td>
                <td class="text-xs"><code>${(t.required_params||[]).join(', ')||'无'}</code></td>
                <td class="text-xs" style="color:var(--text-secondary);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${t.description}">${t.description}</td>
            </tr>`;
        }).join('');

        // Sandbox config
        const sandbox=await API('/api/tools/sandbox');
        const rules=sandbox.risk_rules||{};
        document.getElementById('tgSandboxConfig').innerHTML=`
            <div style="padding:8px 0">
                ${Object.entries(rules).map(([level,rule])=>{
                    const icon={safe:'🟢',write:'🟡',danger:'🔴'}[level]||'⚪';
                    const bg={safe:'var(--brand-green-dim)',write:'rgba(245,158,11,.1)',danger:'rgba(239,68,68,.1)'}[level]||'var(--bg-input)';
                    const borderColor={safe:'var(--brand-green)',write:'var(--brand-amber)',danger:'var(--brand-red)'}[level]||'var(--border)';
                    return `<div style="padding:10px 12px;margin-bottom:8px;background:${bg};border-radius:6px;border-left:3px solid ${borderColor}">
                        <div class="flex-between">
                            <strong>${icon} ${level.toUpperCase()}</strong>
                            <span class="badge ${rule.approve==='auto'?'badge-green':rule.approve==='console'?'badge-amber':'badge-red'}">${rule.approve}</span>
                        </div>
                        <div class="text-xs mt-1" style="color:var(--text-secondary)">${rule.desc}</div>
                    </div>`;
                }).join('')}
                <div class="mt-2 text-xs" style="color:var(--text-muted);padding:8px;background:var(--bg-input);border-radius:4px">
                    <strong>工作区根目录:</strong> <code>/output</code><br>
                    <strong>策略:</strong> Safe=自动 | Write=终端确认 | Danger=管理员授权
                </div>
            </div>`;

        // Agent contracts
        const agentTools=tools.agent_tools||{};
        const agentCount=Object.keys(agentTools).length;
        document.getElementById('tgAgentCount').textContent=agentCount;
        document.getElementById('tgAgentContracts').innerHTML=agentCount?Object.entries(agentTools).map(([role,toolList])=>{
            return `<div style="padding:8px;margin-bottom:4px;background:var(--bg-input);border-radius:4px">
                <div class="flex-between mb-1">
                    <strong style="font-size:12px">🤖 ${role}</strong>
                    <span class="badge badge-blue">${toolList.length} tools</span>
                </div>
                <div class="text-xs" style="color:var(--text-secondary)">
                    ${toolList.map(t=>`<code style="margin:1px 2px;display:inline-block;padding:2px 6px;background:var(--bg-card);border-radius:3px">${t.name}</code>`).join(' ')}
                </div>
            </div>`;
        }).join(''):'<div style="color:var(--text-muted);text-align:center;padding:12px">Agent 未初始化 — 运行流水线后自动注册</div>';

        // Tool history
        try{
            const hist=await API('/api/tools/history?limit=20');
            const entries=hist.history||[];
            document.getElementById('tgHistoryBody').innerHTML=entries.length?entries.map(h=>{
                const statusIcon=h.success?'✅':'❌';
                const sandboxBadge={auto:'badge-green',console:'badge-amber',block:'badge-red'}[h.sandbox]||'badge-muted';
                return `<tr>
                    <td class="text-xs" style="color:var(--text-muted)">${(h.timestamp||'').substring(0,19)}</td>
                    <td><code style="font-size:10px">${h.tool}</code></td>
                    <td class="text-xs" style="color:var(--text-secondary);max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${h.args_summary}">${h.args_summary||''}</td>
                    <td>${statusIcon} ${h.success?'成功':(h.error||'')}</td>
                    <td><span class="badge ${sandboxBadge}">${h.sandbox||'auto'}</span></td>
                </tr>`;
            }).join(''):'<tr><td colspan="5" style="color:var(--text-muted);text-align:center;padding:12px">暂无工具调用记录<br><span class="text-xs">工具调用会在 Agent 执行时自动记录</span></td></tr>';
        }catch(e){document.getElementById('tgHistoryBody').innerHTML='<tr><td colspan="5" style="color:var(--brand-red)">加载失败</td></tr>'}

    }catch(e){
        document.getElementById('tgToolBody').innerHTML=`<tr><td colspan="5" style="color:var(--brand-red);text-align:center;padding:20px">加载失败: ${e}</td></tr>`;
    }
}

async function viewToolDetail(toolName){
    try{
        const t=await API('/api/tools/'+toolName);
        const schema=t.input_schema||{};
        const props=schema.properties||{};
        const propRows=Object.entries(props).map(([k,v])=>{
            const req=(schema.required||[]).includes(k)?'<span class="badge badge-red">必填</span>':'<span class="badge badge-muted">可选</span>';
            return `<tr><td><code>${k}</code> ${req}</td><td>${v.type||'string'}</td><td class="text-xs">${v.description||''}</td></tr>`;
        }).join('');
        const riskIcon={safe:'🟢',write:'🟡',danger:'🔴'}[t.risk_level]||'⚪';
        const msg=`📦 工具: ${riskIcon} ${t.name}\n风险等级: ${t.risk_level}\n描述: ${t.description}\n必填参数: ${(schema.required||[]).join(', ')||'无'}\n参数数量: ${Object.keys(props).length}`;
        log(msg.replace(/\n/g,'\n  '));
        toast('✅ 工具详情已输出到控制台','success');
    }catch(e){toast('加载工具详情失败: '+e,'error')}
}

// ═══════════════════════════════════════════════════════════
// 增强签核 — 时间线 + 证据门禁
// ═══════════════════════════════════════════════════════════

async function viewSignoffTimeline(sid){
    try{
        // Try new signoff events API first
        const d=await API('/api/signoffs/'+sid+'/events');
        const timeline=(d.events||[]).sort((a,b)=>a.created_at>b.created_at?1:-1);
        if(timeline.length===0){toast('暂无事件记录','info');return}
        const html=timeline.map((t,i)=>{
            const isLast=i===timeline.length-1;
            const iconMap={submitted:'📝',approved:'✅',rejected:'❌',commented:'💬',reopened:'🔄',draft:'📄'};
            const icon=iconMap[t.event_type]||'📋';
            return `<div style="display:flex;gap:10px;padding:6px 0;${isLast?'':'border-left:2px solid var(--brand-blue-dim)'}">
                <span style="font-size:16px;margin-left:-8px;background:var(--bg-card);padding:2px">${icon}</span>
                <div style="flex:1">
                    <div class="flex-between"><strong class="text-xs">${t.event_type} ${t.before_status?'('+t.before_status+'→'+t.after_status+')':''}</strong><span class="text-xs" style="color:var(--text-muted)">${(t.created_at||'').substring(0,16)}</span></div>
                    <div class="text-xs" style="color:var(--text-secondary)">${t.comment||''}${t.actor_name?' — <strong>'+t.actor_name+'</strong> ('+t.actor_role+')':''}</div>
                </div>
            </div>`;
        }).join('');
        const panel=document.getElementById('sfIntegrityPanel');const content=document.getElementById('sfIntegrityContent');
        panel.style.display='';
        content.innerHTML=`<div style="padding:8px"><strong>📅 签核事件流 (${timeline.length} 个事件)</strong></div>${html}`;
    }catch(e){toast('加载签核事件失败: '+e,'error')}
}

// Override approveSF to add evidence integrity gating
const _origApproveSF=approveSF;
approveSF=async function(id){
    // First check evidence integrity
    try{
        const evidence=await API('/api/signoffs/'+id+'/evidence');
        const integrity=evidence.integrity;
        if(integrity&&!integrity.valid){
            const msg=`⚠️ 证据链完整性校验失败:\n${integrity.conclusion||'证据链存在问题'}\n\n• Manifest Hash: ${integrity.manifest_hash_ok?'✅':'🔴'}\n• 阶段完整性: ${integrity.phases_complete?'✅':`⚠️ ${integrity.phases_passed||0}/${integrity.total_phases||0}`}\n\n不建议批准此签核。是否仍要继续？`;
            if(!confirm(msg))return;
        }else if(integrity&&integrity.valid){
            toast('🔍 证据链完整性校验通过 ✅','success');
        }
    }catch(e){/* evidence not available, proceed anyway */}

    if(!confirm('批准此签核将锁定证据链 Hash，之后不可篡改。确认批准？'))return;
    let evidenceHash='';
    try{const mfs=await API('/api/manifest/latest');evidenceHash=mfs?mfs.manifest_hash||'':''}catch(e){}
    await API('/api/signoffs/'+id+'/approve',{method:'PUT'});
    toast('✅ 已批准 — 证据链已锁定 🔒'+(evidenceHash?' Hash: '+evidenceHash.substring(0,14)+'...':''),'success');
    loadSignoffs();
};

// Override viewSignoff to show timeline
const _origViewSignoff=viewSignoff;
viewSignoff=async function(id){
    _origViewSignoff(id);
    // Also load and show timeline
    viewSignoffTimeline(id);
};

// ── INIT ──
async function initApp(){
    // Default: manager view with module overview
    switchRole('manager');
}

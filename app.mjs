import * as storage from './storage.mjs';

const $=id=>document.getElementById(id);
const LABELS={greedy:'Greedy',hc:'Hill Climbing',sa:'Simulated Annealing',ga:'Genetic Algorithm',custom:'Custom Python'};
const COLORS={greedy:'#64748b',hc:'#3970db',sa:'#c77c22',ga:'#8a59c4',custom:'#0f907d'};
const STATUS={completed:'จบการค้นหา',evaluation_budget:'ครบงบประเมิน',time_limit:'ถึงเวลาที่กำหนด',error:'โค้ดผิดพลาด',invalid_solution:'ไม่ผ่านข้อห้าม',worker_timeout:'หยุดเมื่อเกินเวลา',cancelled:'ยกเลิก'};
const DAYS=['จันทร์','อังคาร','พุธ','พฤหัสบดี','ศุกร์','เสาร์','อาทิตย์'];
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=(value,digits=0)=>Number.isFinite(value)?value.toLocaleString('en-US',{minimumFractionDigits:digits,maximumFractionDigits:digits}):'—';
const state={dataset:null,datasetText:'',datasetHash:'',datasetLabel:'',batch:null,worker:null,pending:new Map(),nextId:1,
  running:false,cancelled:false,preparedHash:null,preparedMeta:null,storageFailed:false,currentProgress:[],currentLogs:[]};

function banner(message,success=false){$('banner').textContent=message;$('banner').classList.remove('hidden');$('banner').classList.toggle('success',success);}
function hideBanner(){$('banner').classList.add('hidden');}
function view(name){document.querySelectorAll('.view').forEach(el=>el.classList.toggle('hidden',el.id!==`view-${name}`));document.querySelectorAll('.nav-item').forEach(el=>{el.classList.toggle('active',el.dataset.view===name);if(el.dataset.view===name)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});if(name==='history')renderHistory();if(name==='results')renderResults();window.scrollTo({top:0,behavior:'instant'});}
document.querySelectorAll('[data-view]').forEach(el=>el.addEventListener('click',()=>view(el.dataset.view)));
document.querySelectorAll('[data-file-picker]').forEach(button=>button.addEventListener('click',()=>{const input=$(button.dataset.filePicker);if(!input.disabled)input.click();}));
async function sha(text){const bytes=typeof text==='string'?new TextEncoder().encode(text):text;const hash=await crypto.subtle.digest('SHA-256',bytes);return [...new Uint8Array(hash)].map(x=>x.toString(16).padStart(2,'0')).join('');}
function download(name,content,type='application/json'){const blob=new Blob([content],{type});const link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(link.href),5000);}
function safeFilename(name){return String(name).replace(/[^a-zA-Z0-9._-]/g,'_').slice(0,90);}
function csvCell(value){let text=String(value??'');if(/^[=+@-]/.test(text))text="'"+text;return '"'+text.replaceAll('"','""')+'"';}
function csv(rows){return '\ufeff'+rows.map(row=>row.map(csvCell).join(',')).join('\r\n');}
async function unpack(bytes){if(!globalThis.DecompressionStream)throw new Error('เบราว์เซอร์นี้ยังไม่รองรับ gzip กรุณาอัปโหลดไฟล์ JSON ที่แตกแล้ว');return new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).text();}

async function setDataset(text,label,{keepBatch=false}={}){
  if(state.running)throw new Error('รอให้การทดลองปัจจุบันจบก่อนเปลี่ยนข้อมูล');
  if(text.length>20*1024*1024)throw new Error('ข้อมูล JSON ใหญ่เกิน 20 MB');
  const data=JSON.parse(text);
  for(const field of ['classes','rooms','recurring_sessions','external_classes','student_groups','instructors'])if(!Array.isArray(data[field]))throw new Error(`ไม่พบ ${field} ในข้อมูล`);
  if(data.schema_version!=='1.0'||!data.calendar?.week_ids?.length)throw new Error('ต้องใช้ข้อมูลตาม schema_version 1.0 ของโครงงาน');
  if(!data.constraints||!data.objectives)throw new Error('ไม่พบกฎข้อจำกัดหรือวิธีคิดคะแนน');
  const hash=await sha(text);
  state.dataset=data;state.datasetText=text;state.datasetHash=hash;state.datasetLabel=label;state.preparedHash=null;
  disposeWorker();
  if(!keepBatch)state.batch=null;
  $('dataset-name').textContent=label;
  $('dataset-meta').textContent=`${data.dataset_id} · ตรวจรูปแบบ JSON แล้ว`;
  const counts=[data.classes.length,data.recurring_sessions.reduce((n,s)=>n+s.active_weeks.length,0),
    `${data.rooms.filter(r=>r.schedulable&&r.kind==='lecture').length} + ${data.rooms.filter(r=>r.schedulable&&r.kind==='computer_lab').length}`,data.calendar.week_ids.length];
  $('dataset-stats').querySelectorAll('strong').forEach((node,i)=>node.textContent=typeof counts[i]==='number'?num(counts[i]):counts[i]);
  $('dataset-hash').textContent='Dataset SHA-256: '+hash;
  const details=document.querySelector('.assumptions');
  [...details.querySelectorAll('p:not(#dataset-hash)')].forEach(p=>p.remove());
  const note=document.createElement('p');
  note.textContent=`ปฏิทิน ${data.calendar.week_ids.length} สัปดาห์ · มีคาบที่ต้องใช้ Lab ${data.recurring_sessions.reduce((n,s)=>n+s.lab_weeks.length,0)} คาบรายสัปดาห์ · Seed สร้างข้อมูล ${data.generator?.seed??'ไม่ระบุ'}`;
  details.insertBefore(note,details.querySelector('a'));
  const scope=document.createElement('p');scope.textContent=data.constraints.external_student_overlap_is_hard?'กรณีเข้มงวด: รวมความชนของนักศึกษากับตารางภายนอกเป็นข้อห้าม':'กรณีหลัก: นักศึกษาห้ามชนกันภายใน CS ส่วนภายนอกล็อกห้อง ผู้สอน และ explicit rules ตามข้อมูล';details.insertBefore(scope,details.querySelector('a'));
  const assumed=document.createElement('p');assumed.textContent=data.benchmark_kind==='adapted_synthetic_from_unitime_not_original_score'?'ข้อมูลดัดแปลงจาก UniTime มีปฏิทิน ประเภทห้อง ผู้สอนบางส่วน และ Lab รายสัปดาห์แบบจำลอง':'ตรวจที่มาและสมมติฐานในไฟล์ที่อัปโหลดก่อนสรุปผล';details.insertBefore(assumed,details.querySelector('a'));
  $('run-button').disabled=false;$('run-status').textContent='พร้อมเริ่มทดลอง';
  try{await storage.saveDataset({hash,text,label});}catch(error){storageWarning(error);}
  renderResults();
}
function storageWarning(error){if(!state.storageFailed)banner('บันทึกประวัติอัตโนมัติไม่สำเร็จ กรุณาดาวน์โหลดชุดผล JSON เก็บไว้: '+error.message);state.storageFailed=true;}
async function persist(){if(!state.batch)return;try{await storage.saveExperiment(state.batch);}catch(error){storageWarning(error);}}
async function defaultDataset(){const response=await fetch('./data/fall-cs.json.gz');if(!response.ok)throw new Error('โหลด Fall CS ไม่สำเร็จ');const text=await unpack(await response.arrayBuffer());const metadata=await (await fetch('./data/provenance.json')).json();if(await sha(text)!==metadata.dataset_sha256)throw new Error('ไฟล์ Fall CS ไม่ตรงกับ checksum ที่บันทึกไว้');await setDataset(text,'Fall CS · Weekly Labs v1');}
$('dataset-upload').addEventListener('change',async event=>{try{const file=event.target.files[0];if(!file)return;if(file.size>12*1024*1024)throw new Error('ไฟล์อัปโหลดใหญ่เกิน 12 MB');const text=file.name.endsWith('.gz')?await unpack(await file.arrayBuffer()):await file.text();hideBanner();await setDataset(text,file.name);}catch(error){banner(error.message);}finally{event.target.value='';}});
$('reset-dataset').addEventListener('click',()=>defaultDataset().catch(error=>banner(error.message)));
$('download-dataset').addEventListener('click',()=>{if(state.dataset)download(safeFilename(state.dataset.dataset_id)+'.json',state.datasetText);});

function selectedMethods(){const result=[...document.querySelectorAll('input[name=algorithm]:checked')].map(x=>x.value);if($('include-custom').checked)result.push('custom');return result;}
function queueSummary(){const count=Math.max(0,Number($('repeats').value)||0),methods=selectedMethods();$('queue-count').textContent=`${methods.length*count} รัน`;$('queue-description').textContent=`${methods.length} วิธี × ${count} seed · งบ ${num(Number($('budget').value))} / รัน`;}
document.querySelectorAll('input[name=algorithm],#include-custom,#repeats,#budget').forEach(el=>el.addEventListener('input',queueSummary));
function number(id){const input=$(id);if(!input.checkValidity())throw new Error(`ตรวจค่าที่กรอก: ${input.closest('label')?.firstChild?.textContent||id}`);return Number(input.value);}
function settings(){
  const methods=selectedMethods();if(!methods.length)throw new Error('เลือกอัลกอริทึมอย่างน้อย 1 วิธี');
  const start=number('start-seed'),repeats=number('repeats');if(start+repeats-1>4294967295)throw new Error('ช่วง seed เกิน 2^32-1');
  const parameters={hc:{restart_patience:number('hc-patience')},sa:{initial_acceptance:number('sa-acceptance'),cooling_rate:number('sa-cooling')},ga:{population_size:number('ga-population'),tournament_size:number('ga-tournament'),elites:number('ga-elites'),crossover_rate:number('ga-crossover'),mutation_rate:number('ga-mutation')},custom:JSON.parse($('custom-parameters').value)};
  if(parameters.custom===null||Array.isArray(parameters.custom)||typeof parameters.custom!=='object')throw new Error('Custom parameters ต้องเป็น JSON object');
  if(parameters.ga.elites>=parameters.ga.population_size||parameters.ga.tournament_size>parameters.ga.population_size)throw new Error('GA: Elite ต้องน้อยกว่าประชากร และ Tournament ไม่เกินประชากร');
  return {name:$('experiment-name').value.trim()||'Fall CS experiment',methods,seeds:Array.from({length:repeats},(_,i)=>start+i),budget:number('budget'),seconds:number('time-limit'),parameters};
}
function disposeWorker(){if(state.worker)state.worker.terminate();state.worker=null;state.preparedHash=null;for(const {reject,timer} of state.pending.values()){clearTimeout(timer);reject(new Error(state.cancelled?'cancelled':'Worker was restarted'));}state.pending.clear();}
function ensureWorker(){
  if(state.worker)return;
  state.worker=new Worker(new URL('./worker.mjs',import.meta.url),{type:'module'});
  state.worker.onmessage=({data})=>{
    if(data.type==='phase'){$('progress-detail').textContent=data.message;return;}
    if(data.type==='progress'){
      state.currentProgress.push(data.payload);
      $('live-metrics').textContent=`ประเมิน ${data.payload.evaluations} / ${data.payload.budget} · ขาด ${data.payload.objectives[0]} คาบ · Lab เกิน ${num(data.payload.objectives[1]/60,1)} ชม.`;
      return;
    }
    if(data.type==='stdout'||data.type==='stderr'){if(state.currentLogs.length<100)state.currentLogs.push(data.line);return;}
    const pending=state.pending.get(data.id);if(!pending)return;clearTimeout(pending.timer);state.pending.delete(data.id);if(data.error)pending.reject(new Error(data.error));else pending.resolve(data.result);
  };
  state.worker.onerror=event=>{const message=event.message||'Python worker โหลดไม่สำเร็จ ตรวจการเชื่อมต่อ CDN';for(const {reject,timer}of state.pending.values()){clearTimeout(timer);reject(new Error(message));}state.pending.clear();};
}
function rpc(type,payload,timeout){ensureWorker();const id=state.nextId++;return new Promise((resolve,reject)=>{const timer=setTimeout(()=>{state.pending.delete(id);const error=new Error(type==='run'?'worker_timeout':'โหลด Python หรือเตรียมข้อมูลนานเกินกำหนด กรุณาลองใหม่');reject(error);disposeWorker();},timeout);state.pending.set(id,{resolve,reject,timer});state.worker.postMessage({id,type,...payload});});}
async function prepare(){if(state.preparedHash===state.datasetHash)return state.preparedMeta;const result=await rpc('prepare',{datasetText:state.datasetText,datasetHash:state.datasetHash},120000);state.preparedHash=state.datasetHash;state.preparedMeta=result;return result;}
function lock(running){$('run-button').disabled=running||!state.dataset;$('stop-button').disabled=!running;for(const id of ['dataset-upload','reset-dataset','include-custom','repeats','budget','time-limit','start-seed','experiment-name'])$(id).disabled=running;document.querySelectorAll('input[name=algorithm]').forEach(el=>el.disabled=running);document.querySelector('[data-file-picker=dataset-upload]').disabled=running;document.querySelector('[data-file-picker=import-results]').disabled=running;}
function failedRun(job,error,config){return {algorithm:job.algorithm,seed:job.seed,status:error==='cancelled'?'cancelled':error==='worker_timeout'?'worker_timeout':'error',valid:false,metrics:null,validation:{valid:false,violation_count:null,violations:[]},solution:null,evaluations:state.currentProgress.at(-1)?.evaluations||0,budget:config.budget,time_limit_seconds:config.seconds,search_seconds:null,trace:state.currentProgress,error:{message:error},parameters:config.parameters[job.algorithm]||{},dataset_id:state.dataset.dataset_id,dataset_sha256:state.datasetHash,engine_version:'1.0.0'};}
async function startExperiment(){
  if(state.running)return;let config;
  try{config=settings();}catch(error){banner(error.message);return;}
  hideBanner();state.running=true;state.cancelled=false;lock(true);state.currentProgress=[];state.currentLogs=[];
  const jobs=config.seeds.flatMap(seed=>config.methods.map(algorithm=>({algorithm,seed})));
  state.batch={id:crypto.randomUUID(),name:config.name,created_at:new Date().toISOString(),status:'running',dataset_hash:state.datasetHash,dataset_id:state.dataset.dataset_id,dataset_label:state.datasetLabel,config,run_order:jobs,results:[],custom_source:config.methods.includes('custom')?$('custom-code').value:'',browser:{user_agent:navigator.userAgent,logical_processors:navigator.hardwareConcurrency||null},code_snapshot:{}};
  await persist();$('run-progress').max=jobs.length;$('run-progress').value=0;$('run-fraction').textContent=`0 / ${jobs.length}`;$('run-status').textContent='กำลังเตรียมการทดลอง';
  try{
    const meta=await prepare();if(state.cancelled)throw new Error('cancelled');
    state.batch.preparation={...meta};delete state.batch.preparation.code_snapshot;state.batch.code_snapshot=meta.code_snapshot;state.batch.engine_sha256=await sha(JSON.stringify(meta.code_snapshot));
    await persist();
    for(let index=0;index<jobs.length;index++){
      if(state.cancelled)break;const job=jobs[index];state.currentProgress=[];state.currentLogs=[];
      $('run-status').textContent=`${LABELS[job.algorithm]} · seed ${job.seed}`;$('progress-detail').textContent=`รันที่ ${index+1} จาก ${jobs.length} · เตรียมข้อมูลร่วม ${num(meta.preprocessing_seconds,2)} วินาที (ไม่นับในเวลาค้นหา)`;
      let result;
      try{
        const currentMeta=await prepare();if(await sha(JSON.stringify(currentMeta.code_snapshot))!==state.batch.engine_sha256)throw new Error('โค้ด runtime เปลี่ยนระหว่างทดลอง กรุณาเริ่มชุดใหม่');
        result=await rpc('run',{algorithm:job.algorithm,seed:job.seed,config,datasetHash:state.datasetHash,customCode:state.batch.custom_source},(config.seconds+12)*1000);
      }catch(error){result=failedRun(job,state.cancelled?'cancelled':error.message,config);disposeWorker();}
      result.run_index=index;result.logs=state.currentLogs.slice();state.batch.results.push(result);
      $('run-progress').value=index+1;$('run-fraction').textContent=`${index+1} / ${jobs.length}`;
      await persist();renderResults();
      if(job.algorithm==='custom')disposeWorker();
    }
    state.batch.status=state.cancelled?'cancelled':'completed';
  }catch(error){state.batch.status=state.cancelled?'cancelled':'error';state.batch.error=error.message;if(!state.cancelled)banner(error.message);}
  finally{
    state.batch.finished_at=new Date().toISOString();state.running=false;lock(false);await persist();
    $('run-status').textContent=state.cancelled?'หยุดและเก็บผลที่มีแล้ว':state.batch.status==='error'?'การทดลองหยุดด้วยข้อผิดพลาด':state.storageFailed?'เสร็จแล้ว · กรุณาดาวน์โหลดผล':'เสร็จและบันทึกผลแล้ว';
    $('progress-detail').textContent=`ได้ผล ${state.batch.results.length} จาก ${jobs.length} รัน · ดาวน์โหลด CSV หรือชุดผล JSON ได้`;
    renderResults();if(state.batch.results.length)view('results');
  }
}
$('run-button').addEventListener('click',startExperiment);
$('stop-button').addEventListener('click',()=>{state.cancelled=true;disposeWorker();$('run-status').textContent='กำลังหยุดและบันทึกผลที่มี';});

function mean(values){return values.length?values.reduce((a,b)=>a+b,0)/values.length:NaN;}
function median(values){if(!values.length)return NaN;const sorted=values.slice().sort((a,b)=>a-b);const m=Math.floor(sorted.length/2);return sorted.length%2?sorted[m]:(sorted[m-1]+sorted[m])/2;}
function sd(values){if(values.length<2)return values.length?0:NaN;const avg=mean(values);return Math.sqrt(values.reduce((n,v)=>n+(v-avg)**2,0)/(values.length-1));}
function methodLabel(method){return `<span class="method-label"><i class="color-dot" style="background:${COLORS[method]||'#64748b'}"></i>${esc(LABELS[method]||method)}</span>`;}
function statusLabel(run){const failed=!run.valid;const partial=run.valid&&run.metrics?.unassigned_weekly_sessions>0;return `<span class="status ${failed?'failed':partial?'partial':''}">${esc(STATUS[run.status]||run.status)}${partial?' · ตารางบางส่วน':''}</span>`;}
function renderResults(){
  const batch=state.batch,results=batch?.results||[];$('result-count').textContent=results.length;
  $('results-empty').classList.toggle('hidden',results.length>0);$('results-content').classList.toggle('hidden',!results.length);
  for(const id of ['export-csv','export-json'])$(id).disabled=!results.length;
  if(!results.length)return;
  $('results-description').textContent=`${batch.name} · ${results.length} / ${batch.run_order?.length||results.length} รัน${batch.imported?' · นำเข้า ไม่ได้รันใหม่':''}`;
  $('result-meta').innerHTML=[batch.dataset_id,`Dataset ${batch.dataset_hash.slice(0,12)}`,`งบ ${batch.config.budget} / รัน`,`Python ${batch.preparation?.pyodide_version||'native'}`,`Code ${(batch.engine_sha256||'').slice(0,12)}`].map(x=>`<span>${esc(x)}</span>`).join('');
  const methods=[...new Set(results.map(r=>r.algorithm))];
  const summaries=methods.map(algorithm=>{const rows=results.filter(r=>r.algorithm===algorithm),valid=rows.filter(r=>r.valid&&r.metrics);return{algorithm,rows,valid,key:[median(valid.map(r=>r.metrics.unassigned_weekly_sessions)),median(valid.map(r=>r.metrics.unnecessary_lab_minutes)),median(valid.map(r=>r.metrics.room_changes))]};});
  summaries.sort((a,b)=>{for(let i=0;i<3;i++){const x=Number.isFinite(a.key[i])?a.key[i]:Infinity,y=Number.isFinite(b.key[i])?b.key[i]:Infinity;if(x!==y)return x-y;}return 0;});
  $('summary-body').innerHTML=summaries.map(s=>{const hours=s.valid.map(r=>r.metrics.unnecessary_lab_hours);return`<tr><td>${methodLabel(s.algorithm)}</td><td class="number">${s.valid.length} / ${s.rows.length}</td><td class="number">${num(s.key[0],1)}</td><td class="number">${num(mean(hours),2)} ± ${num(sd(hours),2)}</td><td class="number">${num(s.key[2],1)}</td><td class="number">${num(mean(s.rows.filter(r=>Number.isFinite(r.search_seconds)).map(r=>r.search_seconds)),3)}</td></tr>`;}).join('');
  $('runs-body').innerHTML=results.map(r=>`<tr><td>${methodLabel(r.algorithm)}<br><span class="micro mono">seed ${esc(r.seed)}</span></td><td>${statusLabel(r)}${r.error?`<p class="error-text">${esc(r.error.message).slice(0,500)}</p>`:''}</td><td class="number">${num(r.metrics?.unassigned_weekly_sessions)}</td><td class="number">${num(r.metrics?.unnecessary_lab_hours,2)}</td><td class="number">${num(r.metrics?.room_changes)}</td><td class="number">${num(r.evaluations)}</td><td class="number">${num(r.search_seconds,3)}</td><td class="number">${num(r.validation?.violation_count)}</td></tr>`).join('');
  const oldSeed=$('chart-seed').value,seeds=[...new Set(results.map(r=>r.seed))];$('chart-seed').replaceChildren(...seeds.map(seed=>new Option(String(seed),String(seed))));if(seeds.includes(Number(oldSeed)))$('chart-seed').value=oldSeed;
  const oldRun=$('schedule-run').value;$('schedule-run').replaceChildren(...results.map((r,i)=>new Option(`${LABELS[r.algorithm]||r.algorithm} · ${r.seed}${r.valid?'':' · ไม่ผ่าน'}`,String(i))));if(Number(oldRun)<results.length)$('schedule-run').value=oldRun||'0';
  const oldWeek=$('schedule-week').value;$('schedule-week').replaceChildren(...state.dataset.calendar.week_ids.map(w=>new Option(String(w),String(w))));if(state.dataset.calendar.week_ids.includes(Number(oldWeek)))$('schedule-week').value=oldWeek;
  renderChart();renderSchedule();
}
function renderChart(){
  const results=(state.batch?.results||[]).filter(r=>r.valid&&r.seed===Number($('chart-seed').value));const metric=Number($('chart-metric').value),scale=metric===1?60:1;
  const traces=results.map(r=>({method:r.algorithm,points:(Array.isArray(r.trace)?r.trace:[]).filter(p=>Number.isFinite(p.objectives?.[metric])&&Number.isFinite(p.evaluations)).map(p=>[p.evaluations,p.objectives[metric]/scale])})).filter(x=>x.points.length);
  if(!traces.length){$('convergence-chart').textContent='ยังไม่มี trace ที่ตรวจผ่านสำหรับ seed นี้';$('chart-legend').textContent='';return;}
  const width=1000,height=280,left=65,right=20,top=20,bottom=40,maxX=Math.max(1,state.batch.config.budget),maxY=Math.max(1,...traces.flatMap(t=>t.points.map(p=>p[1])))*1.1;
  const x=n=>left+n/maxX*(width-left-right),y=n=>height-bottom-n/maxY*(height-top-bottom);
  let svg=`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="คำตอบดีที่สุดเทียบจำนวนครั้งประเมิน"><rect width="1000" height="280" fill="white"/>`;
  for(let i=0;i<=4;i++){const v=maxY*i/4;svg+=`<line x1="${left}" x2="${width-right}" y1="${y(v)}" y2="${y(v)}" stroke="#edf0f5"/><text x="${left-10}" y="${y(v)+4}" text-anchor="end" font-size="10" fill="#8a94aa">${num(v,metric===1?1:0)}</text>`;}
  for(const v of [0,Math.round(maxX/2),maxX])svg+=`<text x="${x(v)}" y="${height-20}" text-anchor="middle" font-size="10" fill="#8a94aa">${v}</text>`;
  for(const trace of traces){const path=trace.points.map((p,i)=>`${i?'L':'M'}${x(p[0])},${y(p[1])}`).join(' ');svg+=`<path d="${path}" fill="none" stroke="${COLORS[trace.method]||'#64748b'}" stroke-width="2.2"/>`;for(const p of [trace.points[0],trace.points.at(-1)])svg+=`<circle cx="${x(p[0])}" cy="${y(p[1])}" r="3" fill="${COLORS[trace.method]||'#64748b'}"/>`;}
  svg+=`<text x="${width/2}" y="${height-3}" text-anchor="middle" font-size="9" fill="#8a94aa">จำนวนครั้งประเมินคำตอบ</text></svg>`;$('convergence-chart').innerHTML=svg;$('chart-legend').innerHTML=traces.map(t=>`<span><i class="color-dot" style="background:${COLORS[t.method]||'#64748b'}"></i>${esc(LABELS[t.method]||t.method)}</span>`).join('');
}
function scheduleRows(run){
  if(!run?.solution)return[];const classes=new Map(state.dataset.classes.map(c=>[c.id,c])),sessions=new Map(state.dataset.recurring_sessions.map(s=>[s.id,s])),rooms=new Map(state.dataset.rooms.map(r=>[r.id,r])),meetings=new Map();
  for(const c of classes.values()){const option=c.time_options.find(o=>o.id===run.solution.class_time_options?.[c.id]);for(const m of option?.meetings||[])meetings.set(m.session_id,m);}
  return (run.solution.weekly_room_assignments||[]).flatMap(row=>{const s=sessions.get(row.session_id),m=meetings.get(row.session_id),room=rooms.get(row.room_id);if(!s||!m||!room)return[];return[{...row,day:m.day,start:m.start_minute,end:m.start_minute+m.duration_minutes,duration:m.duration_minutes,class_id:s.class_id,course_id:classes.get(s.class_id)?.course_id,room_kind:room.kind,needs_lab:s.lab_weeks.includes(row.week)}];});
}
const clock=minute=>`${String(Math.floor(minute/60)).padStart(2,'0')}:${String(minute%60).padStart(2,'0')}`;
function renderSchedule(){const run=state.batch?.results?.[Number($('schedule-run').value)],week=Number($('schedule-week').value);if(!run)return;const all=scheduleRows(run),rows=all.filter(r=>r.week===week).sort((a,b)=>a.day-b.day||a.start-b.start||a.session_id.localeCompare(b.session_id));$('schedule-description').textContent=run.valid?'ตารางตรวจผ่านข้อห้าม · คาบที่ขาดแสดงแยกด้านล่าง':'คำตอบนี้ไม่ผ่านหรือไม่มีตาราง ห้ามใช้สรุปว่าอัลกอริทึมดีกว่า';$('schedule-body').innerHTML=rows.map(r=>`<tr><td>${DAYS[r.day]}</td><td class="mono">${clock(r.start)}–${clock(r.end)}</td><td>${esc(r.class_id)}<br><span class="micro mono">${esc(r.session_id)}</span></td><td>${esc(r.room_id)}<br><span class="micro">${r.room_kind==='computer_lab'?'Computer lab':'ห้องบรรยาย'}</span></td><td>${r.needs_lab?'จำเป็น':'ไม่จำเป็น'}</td></tr>`).join('')||'<tr><td colspan="5">ไม่มีคาบที่จัดได้ในสัปดาห์นี้</td></tr>';const assigned=new Set(rows.map(r=>r.session_id)),missing=state.dataset.recurring_sessions.filter(s=>s.active_weeks.includes(week)&&!assigned.has(s.id));$('unassigned-title').textContent=`คาบที่ยังจัดไม่ได้ในสัปดาห์ ${week}: ${missing.length} คาบ`;$('unassigned-list').innerHTML=missing.map(s=>`<span>${esc(s.id)}</span>`).join('');$('validation-details').textContent=JSON.stringify({status:run.status,validation:run.validation,error:run.error,logs:run.logs},null,2);}
for(const id of ['chart-seed','chart-metric'])$(id).addEventListener('change',renderChart);for(const id of ['schedule-run','schedule-week'])$(id).addEventListener('change',renderSchedule);
$('export-csv').addEventListener('click',()=>{const b=state.batch;const headers=['experiment_id','dataset_id','dataset_sha256','algorithm','seed','status','valid','unassigned_weekly_sessions','unnecessary_lab_minutes','unnecessary_lab_hours','room_changes','hard_violations','evaluations','attempted_evaluations','budget','search_seconds','validation_seconds','time_limit_seconds','code_sha256','engine_version','parameters_json'];const rows=b.results.map(r=>[b.id,r.dataset_id,r.dataset_sha256,r.algorithm,r.seed,r.status,r.valid,r.metrics?.unassigned_weekly_sessions,r.metrics?.unnecessary_lab_minutes,r.metrics?.unnecessary_lab_hours,r.metrics?.room_changes,r.validation?.violation_count,r.evaluations,r.attempted_evaluations,r.budget,r.search_seconds,r.validation_seconds,r.time_limit_seconds,r.code_sha256,r.engine_version,JSON.stringify(r.parameters)]);download(`results-${b.id}.csv`,csv([headers,...rows]),'text/csv;charset=utf-8');});
$('export-json').addEventListener('click',()=>{const payload={format:'timetable-lab-experiment/v1',exported_at:new Date().toISOString(),batch:state.batch,dataset_text:state.datasetText};download(`experiment-${state.batch.id}.json`,JSON.stringify(payload,null,2));});
$('export-schedule').addEventListener('click',()=>{const run=state.batch?.results?.[Number($('schedule-run').value)];if(!run?.solution)return;const headers=['algorithm','seed','week','day','start','end','class_id','course_id','session_id','room_id','room_kind','requires_lab'];const rows=scheduleRows(run).sort((a,b)=>a.week-b.week||a.day-b.day||a.start-b.start).map(r=>[run.algorithm,run.seed,r.week,DAYS[r.day],clock(r.start),clock(r.end),r.class_id,r.course_id,r.session_id,r.room_id,r.room_kind,r.needs_lab]);download(`schedule-${run.algorithm}-${run.seed}.csv`,csv([headers,...rows]),'text/csv;charset=utf-8');});

async function renderHistory(){try{const batches=(await storage.loadExperiments()).sort((a,b)=>b.created_at.localeCompare(a.created_at));$('history-list').innerHTML=batches.map(b=>`<article class="panel history-card"><div><h2>${esc(b.name)}</h2><p>${esc(b.dataset_id)} · ${b.results.length} รัน · ${new Intl.DateTimeFormat('th-TH',{dateStyle:'medium',timeStyle:'short',timeZone:'Asia/Bangkok'}).format(new Date(b.created_at))}</p><span class="tag">${esc(b.status)}${b.imported?' · นำเข้า':''}</span></div><button class="button secondary history-open" data-id="${esc(b.id)}" ${state.running?'disabled':''}>เปิดผลการทดลอง ↗</button></article>`).join('')||'<div class="empty panel"><h2>ยังไม่มีประวัติการทดลอง</h2><p>ผลจะถูกบันทึกหลังแต่ละรันโดยอัตโนมัติ</p></div>';$('history-list').querySelectorAll('.history-open').forEach(button=>button.addEventListener('click',async()=>{try{const batch=batches.find(b=>b.id===button.dataset.id),dataset=await storage.loadDataset(batch.dataset_hash);if(!dataset)throw new Error('ไม่พบข้อมูลประกอบ กรุณานำเข้าชุดผล JSON ที่ส่งออกไว้');await setDataset(dataset.text,dataset.label,{keepBatch:true});state.batch=batch;view('results');}catch(error){banner(error.message);}}));}catch(error){storageWarning(error);$('history-list').textContent='ไม่สามารถเปิดฐานข้อมูลประวัติในเบราว์เซอร์นี้ได้';}}
$('import-results').addEventListener('change',async event=>{try{const file=event.target.files[0];if(!file)return;if(state.running)throw new Error('รอให้การทดลองปัจจุบันจบก่อนนำเข้าผล');if(file.size>60*1024*1024)throw new Error('ชุดผลใหญ่เกิน 60 MB');const payload=JSON.parse(await file.text());if(payload.format!=='timetable-lab-experiment/v1'||typeof payload.dataset_text!=='string'||!Array.isArray(payload.batch?.results)||payload.batch.results.length>1000)throw new Error('รูปแบบชุดผลไม่ถูกต้อง');const b=payload.batch;
if(typeof b.name!=='string'||typeof b.dataset_hash!=='string'||!Number.isFinite(Date.parse(b.created_at))||!Number.isInteger(b.config?.budget)||b.config.budget<1||b.config.budget>100000||!Array.isArray(b.config.methods)||!b.results.every(r=>r&&typeof r.algorithm==='string'&&Number.isInteger(r.seed)&&typeof r.status==='string'&&typeof r.valid==='boolean'&&Array.isArray(r.trace)&&(!r.valid||(r.metrics&&['unassigned_weekly_sessions','unnecessary_lab_minutes','unnecessary_lab_hours','room_changes'].every(k=>Number.isFinite(r.metrics[k])&&r.metrics[k]>=0)))&&(!r.solution||(typeof r.solution==='object'&&Array.isArray(r.solution.weekly_room_assignments)))))throw new Error('ข้อมูลตั้งค่าหรือผลรายรันในชุดผลไม่ครบ');
if(await sha(payload.dataset_text)!==payload.batch.dataset_hash)throw new Error('Hash ของชุดข้อมูลไม่ตรงกับผลที่นำเข้า');await setDataset(payload.dataset_text,payload.batch.dataset_label||'Imported dataset',{keepBatch:true});state.batch={...payload.batch,id:crypto.randomUUID(),imported:true,imported_from:payload.batch.id};await persist();view('results');banner('นำเข้าชุดผลแล้ว โดยไม่ได้รันอัลกอริทึมใหม่',true);}catch(error){banner(error.message);}finally{event.target.value='';}});

const CUSTOM_TEMPLATE=`# Example: random search using the shared decoder and evaluation budget.\n# context.initial has already used evaluation 1.\n\ndef solve(problem, context, parameters):\n    while True:\n        context.check()\n        genome = problem.random_genome(context.rng)\n        context.evaluate(genome)\n\n    # The runner returns context.best when the budget/time limit is reached.\n`;
try{$('custom-code').value=localStorage.getItem('timetable-lab-custom-code')||CUSTOM_TEMPLATE;}catch{$('custom-code').value=CUSTOM_TEMPLATE;}
$('save-code').addEventListener('click',()=>{try{if(!$('custom-code').value.trim())throw new Error('ยังไม่มีโค้ด');JSON.parse($('custom-parameters').value);localStorage.setItem('timetable-lab-custom-code',$('custom-code').value);$('include-custom').checked=true;queueSummary();$('code-status').textContent='เลือก Custom Python ไว้ในการทดลองแล้ว';}catch(error){banner(error.message);}});
$('code-upload').addEventListener('change',async event=>{try{const file=event.target.files[0];if(!file)return;if(file.size>200000)throw new Error('ไฟล์โค้ดใหญ่เกิน 200 KB');$('custom-code').value=await file.text();$('code-status').textContent='เปิดไฟล์แล้ว กดใช้โค้ดนี้เพื่อเลือกในการทดลอง';}catch(error){banner(error.message);}finally{event.target.value='';}});
$('download-code').addEventListener('click',()=>download('custom_algorithm.py',$('custom-code').value,'text/x-python'));
queueSummary();defaultDataset().catch(error=>{banner(error.message);$('dataset-name').textContent='โหลดข้อมูลไม่สำเร็จ';$('run-status').textContent='กรุณาลองโหลด Fall CS อีกครั้ง';});

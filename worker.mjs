// Python runs off the UI thread. This version is pinned for reproducible runs.
const PYODIDE_VERSION = '314.0.7';
const PYODIDE_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
let runtime;
let preparedHash;
const sourceSnapshot={};

async function initialize() {
  if (runtime) return runtime;
  self.postMessage({type:'phase',message:'กำลังโหลด Python runtime…'});
  const {loadPyodide} = await import(`${PYODIDE_URL}pyodide.mjs`);
  const py = await loadPyodide({indexURL:PYODIDE_URL});
  let stdoutCount = 0;
  py.setStdout({batched:line => {
    if (++stdoutCount <= 100) self.postMessage({type:'stdout',line:String(line).slice(0,1000)});
  }});
  py.setStderr({batched:line => self.postMessage({type:'stderr',line:String(line).slice(0,2000)})});
  const names = ['input_validation.py','solution_validator.py','lab_core.py','algorithms.py','runner.py'];
  for (const name of names) {
    const response = await fetch(new URL(`./python/${name}`,import.meta.url),{cache:'no-cache'});
    if (!response.ok) throw new Error(`โหลด ${name} ไม่สำเร็จ (${response.status})`);
    sourceSnapshot[name]=await response.text();
    py.FS.writeFile(`/home/pyodide/${name}`,sourceSnapshot[name],{encoding:'utf8'});
  }
  py.runPython('import sys\nsys.path.insert(0, "/home/pyodide")\nimport runner');
  runtime = py;
  return py;
}

self.onmessage = async ({data:request}) => {
  const {id,type}=request;
  try {
    const py = await initialize();
    if (type==='prepare') {
      self.postMessage({type:'phase',message:'ตรวจข้อมูลและเตรียมข้อจำกัดร่วมกัน…'});
      py.globals.set('_lab_dataset_text',request.datasetText);
      py.runPython('_lab_problem, _lab_meta = runner.prepare(_lab_dataset_text)');
      const meta = JSON.parse(py.runPython('runner.json.dumps(_lab_meta)'));
      if (meta.dataset_sha256!==request.datasetHash) throw new Error('Dataset hash ไม่ตรงกับข้อมูลที่ส่งเข้า runtime');
      preparedHash=request.datasetHash;
      self.postMessage({id,result:{...meta,pyodide_version:PYODIDE_VERSION,code_snapshot:sourceSnapshot}});
    } else if (type==='run') {
      if (preparedHash!==request.datasetHash) throw new Error('ยังไม่ได้เตรียมชุดข้อมูลนี้');
      py.globals.set('_lab_config',JSON.stringify(request.config));
      py.globals.set('_lab_method',request.algorithm);
      py.globals.set('_lab_seed',request.seed);
      py.globals.set('_lab_custom',request.customCode||'');
      py.globals.set('_lab_on_progress',text => self.postMessage({type:'progress',payload:JSON.parse(text)}));
      const value=await py.runPythonAsync('runner.run_one_json(_lab_problem, _lab_config, _lab_method, _lab_seed, runner.json.dumps(_lab_meta), _lab_custom, _lab_on_progress)');
      self.postMessage({id,result:JSON.parse(value)});
    } else throw new Error('Unknown worker message');
  } catch(error) {
    self.postMessage({id,error:String(error?.stack||error)});
  }
};

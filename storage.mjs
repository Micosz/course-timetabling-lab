const DB_NAME='timetable-lab-v1';
let promise;
export function database() {
  if(!promise) promise=new Promise((resolve,reject)=>{
    const request=indexedDB.open(DB_NAME,1);
    request.onupgradeneeded=()=>{
      request.result.createObjectStore('datasets',{keyPath:'hash'});
      request.result.createObjectStore('experiments',{keyPath:'id'});
    };
    request.onsuccess=()=>resolve(request.result);
    request.onerror=()=>reject(request.error);
    request.onblocked=()=>reject(new Error('ฐานข้อมูลถูกใช้งานโดยหน้าเว็บรุ่นเก่า กรุณาปิดแท็บเก่าแล้วลองใหม่'));
  });
  return promise;
}
async function transaction(store,mode,action) {
  const db=await database();
  return new Promise((resolve,reject)=>{
    const tx=db.transaction(store,mode);
    const request=action(tx.objectStore(store));
    let value;
    request.onsuccess=()=>{value=request.result;};
    tx.oncomplete=()=>resolve(value);
    tx.onerror=()=>reject(tx.error||request.error);
    tx.onabort=()=>reject(tx.error||new Error('การบันทึกถูกยกเลิก'));
  });
}
export const saveDataset=value=>transaction('datasets','readwrite',store=>store.put(value));
export const loadDataset=hash=>transaction('datasets','readonly',store=>store.get(hash));
export const saveExperiment=value=>transaction('experiments','readwrite',store=>store.put(value));
export const loadExperiments=()=>transaction('experiments','readonly',store=>store.getAll());

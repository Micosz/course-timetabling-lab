# Timetable Lab · ห้องทดลองจัดตารางเรียน

เว็บทดลอง **Greedy, random-restart Hill Climbing, Simulated Annealing และ Genetic Algorithm** บน Fall CS ที่ดัดแปลงให้มีความต้องการ Computer Lab รายสัปดาห์ มีตัวตรวจคำตอบร่วมกัน เก็บผลรายรันและตารางเรียนจริง พร้อมส่งออกหลักฐานสำหรับรายงาน

**เปิดใช้งาน:** https://micosz.github.io/course-timetabling-lab/

## เริ่มใช้เว็บ

1. เปิดเว็บ รอชื่อ **Fall CS · Weekly Labs v1** พร้อม 174 คลาส / 3,345 คาบรายสัปดาห์
2. เลือกวิธีที่ต้องการเปรียบเทียบ ตั้งชื่อการทดลอง งบประเมินคำตอบ เวลาสูงสุด seed เริ่มต้น และจำนวนรัน
3. กด **เริ่มการทดลอง** การเปิดครั้งแรกต้องดาวน์โหลด Python runtime จาก jsDelivr ใช้เวลาเพิ่มตามเครือข่าย
4. ดูผลเปรียบเทียบ ผลทุกรัน กราฟ best-so-far ตารางแต่ละสัปดาห์ และรายการคาบที่ยังจัดไม่ได้
5. ดาวน์โหลด **CSV** สำหรับวิเคราะห์ และ **ชุดผล JSON** สำหรับสำรอง/ย้ายเครื่อง/นำเข้ากลับเว็บ JSON รวมข้อมูล โค้ดที่ใช้จริง พารามิเตอร์ trace คำตอบ และผลตรวจ

ค่าเริ่มต้น 50 evaluations × 3 seeds เป็นค่าเริ่มใช้งาน ไม่ใช่งบสุดท้ายที่ผ่านการปรับแต่งแล้ว เมื่อต้องการเก็บผลจริง ให้กำหนดงบและพารามิเตอร์ก่อน แล้วใช้ repeated seeds ชุดเดียวกันทุกวิธี เช่น 30 seeds หากเครื่องและเวลารองรับ ไม่ควรสรุปผู้ชนะจากรันเดียวหรือจากผลตรวจระบบ

ผลบันทึกอัตโนมัติใน **IndexedDB ของเบราว์เซอร์และ origin ปัจจุบัน** หลังแต่ละรัน เปิดย้อนหลังในแท็บประวัติได้ การล้างข้อมูลเว็บ เปลี่ยนเบราว์เซอร์ ใช้โหมดส่วนตัว หรือเปลี่ยนจาก localhost เป็น GitHub Pages จะไม่ใช้ประวัติชุดเดียวกัน จึงควรดาวน์โหลด JSON ทุกชุดที่สำคัญ ผลไม่ได้อัปโหลดขึ้น GitHub อัตโนมัติ เว็บไม่ใส่ผลทดลองตัวอย่างปลอมไว้ล่วงหน้า

## ข้อมูลและขอบเขต

- แหล่งต้นฉบับ: [UniTime university course timetabling datasets](https://www.unitime.org/uct_datasets.php), Purdue Fall 2007 CS (`pu-fal07-cs`)
- ข้อมูลที่ใช้เป็น **adapted synthetic benchmark** ไม่ใช่ข้อมูลจริงของมหาวิทยาลัยไทย และใช้คะแนนคนละแบบกับ benchmark ต้นฉบับ
- 174 คลาส, 223 recurring sessions, 15 สัปดาห์ รวม 3,345 weekly sessions
- ห้องบรรยาย 13 ห้อง + Computer Lab จำลอง 4 ห้อง (61, 36, 30, 26 ที่นั่ง)
- 134 recurring sessions กำหนดให้ใช้ Lab คนละ 4 สัปดาห์ รวม 536 weekly lab sessions / 804 ชั่วโมง
- Seed สร้างข้อมูล `20261027` แยกจาก seed ค้นหาคำตอบ
- ผู้สอนที่ไม่มีในต้นฉบับ 143 คลาสใช้ synthetic instructor แยกคลาส เป็นสมมติฐาน ไม่ได้อนุมานว่าผู้สอนจริงไม่ซ้ำกัน
- ล็อก background classes 810 คลาสเพื่อรักษาการใช้ห้อง ผู้สอน และ explicit distribution rules
- กรณีหลักใช้ student non-overlap ระหว่าง target CS classes ส่วนความชนกับนักศึกษาของ background ไม่ถือเป็นข้อห้ามทั่วไป (`external_student_overlap_is_hard=false`); explicit source non-overlap rules ยังคงบังคับ
- ใช้เฉพาะกรณีหลัก ยังไม่เพิ่มกรณีห้อง Lab ขาดแคลน
- ไม่คิดเวลาเดินระหว่างห้อง ไม่ตีความ source room preferences เป็น hard constraint เพิ่มเอง และไม่ใช้คะแนน preference ดั้งเดิมเป็นคะแนนโครงงาน

รายละเอียดใน [assumptions.json](data/assumptions.json), [FORMAT.txt](data/FORMAT.txt), [START_HERE.txt](data/START_HERE.txt), [conversion_audit.json](data/conversion_audit.json) และ [provenance.json](data/provenance.json)

Dataset JSON SHA-256: `c92918faeb82b4d5c9f702e0629fe5e8d48bcc1a1286c0b21d514a9021973968`

## วิธีแทนคำตอบและวิธีค้นหา

ทั้งสี่วิธีใช้ **indirect encoding และ constructive decoder เดียวกัน**: คำตอบค้นหาเป็นลำดับความสำคัญของคลาสและ preferred source time option ของแต่ละคลาส Decoder ทดลองตัวเลือกวัน/เวลาที่ต้นฉบับอนุญาต เลือก recurring day/time/duration ชุดเดียวตลอดภาค แต่เปลี่ยนห้องได้ตามสัปดาห์

Decoder รักษาข้อห้ามระหว่างจัด หากไม่มีตำแหน่งที่ผ่าน จะเว้น weekly session นั้นและคิดเป็น unassigned คำตอบจึงอาจเป็น **feasible partial timetable**: ไม่มีข้อห้ามที่ละเมิด แต่ยังมีคาบตกค้าง ไม่ควรเรียกว่าจัดได้ครบจนกว่า unassigned=0

- **Greedy:** เริ่มจากคลาสที่มี static placements และ time options น้อยก่อน แล้วใช้ conflict degree เป็นตัวตัดสินร่วม ประเมินครั้งเดียวแล้วจบ เป็น deterministic baseline
- **HC:** สลับลำดับคลาสและเปลี่ยน preferred time option ยอมรับเฉพาะคำตอบที่ดีขึ้น เริ่มใหม่แบบสุ่มเมื่อไม่ดีขึ้นครบ patience คำตอบสุดท้ายเป็น best-so-far
- **SA:** ใช้เพื่อนบ้านแบบเดียวกับ HC แต่ยอมรับคำตอบแย่ลงด้วยความน่าจะเป็นตามอุณหภูมิ ใช้ calibration ไม่เกิน 8 evaluations เพื่อประมาณ initial temperature จาก uphill delta แล้วค่อยลดอุณหภูมิ
- **GA:** ประชากรของ priority/time-preference genomes, tournament selection, ordered crossover ของ permutation, ผสม time preference รายคลาส, mutation แบบเดียวกับ HC และ elitism ใช้ decoder ร่วมซ่อมข้อจำกัดเชิงการจัดห้อง

ค่าเริ่มต้น: HC patience=20; SA initial acceptance=.8, cooling=.97; GA population=12, tournament=3, elites=1, crossover=.9, mutation=.3

นี่คือการเปรียบเทียบวิธีค้นหาบน representation และ decoder นี้ ไม่ใช่การพิสูจน์ว่า implementation นี้แทนทุกวิธีแก้ course timetabling หรือค้นหาตารางทุกแบบได้ Neighborhood เปลี่ยน priority/time preference ไม่ได้ย้ายห้องรายสัปดาห์โดยตรง จึงมีข้อจำกัดของ search space

## ข้อห้ามและเป้าหมายร่วม

`solution_validator.py` ตรวจจากข้อมูลดิบอิสระจาก bitmask/cache ของตัวค้นหา:

- อ้างอิงคลาส/คาบ/ห้อง/สัปดาห์และ source time option ถูกต้อง ไม่ซ้ำ session-week
- วันเวลาและระยะเวลาของ recurring session คงที่ตาม option ที่เลือก
- ห้องใน domain ที่อนุญาต ความจุพอ ประเภท Lab ถูกต้อง และเปิดให้ใช้เต็มช่วงเวลา
- ห้อง ผู้สอน นักศึกษา และ explicit non-overlap groups ไม่ชนกัน รวม background ตาม policy ของข้อมูล
- SAME_TIME ใช้การครอบช่วงเวลาของคาบสั้นในคาบยาวตามข้อมูล ไม่ได้แปลว่าต้องเริ่มเวลาเดียวกันเสมอ

Source constraint ID บางรายการซ้ำกัน (ID 90 ของ SAME_STUDENTS หลายกลุ่ม) จึงใช้แต่ละ array entry เป็น constraint คนละตัว ไม่รวมเป็นกลุ่มใหญ่ตาม ID

เป้าหมายเทียบแบบ **lexicographic** ตามลำดับ:

1. `unassigned_weekly_sessions` น้อยที่สุด
2. เมื่อข้อแรกเท่ากัน ลด `unnecessary_lab_minutes` (สัปดาห์ที่ไม่ต้องใช้ Lab แต่ไปใช้ห้อง Lab)
3. เมื่อสองข้อแรกเท่ากัน ลด `room_changes` ระหว่างสัปดาห์ที่จัดได้ของ recurring session เดียวกัน (ข้ามสัปดาห์ที่ยังจัดไม่ได้)

SA ใช้ scalar energy ที่รักษาลำดับนี้อย่างเคร่งครัด: `Wc=1`, `Wm=Cmax+1`, `Wu=(Mmax+1)*Wm`; `Cmax` คือเพดาน room changes และ `Mmax` คือเวลารวมทุก weekly session ทั้งคู่คำนวณจาก dataset ปัจจุบัน ไม่ใช่น้ำหนักสุ่มที่ปรับเพื่อให้วิธีใดชนะ

## ความเท่าเทียมและการอ่านผล

- ทุกวิธีได้ initial genome เดียวกัน งบเดียวกัน ข้อมูล/ข้อจำกัด/คะแนน/validator เดียวกัน
- นับหนึ่ง evaluation เมื่อ decode และคิดคะแนน candidate เต็มชุดสำเร็จ รวม initialization, SA calibration และ GA initial population; บันทึก attempted evaluations แยกเมื่อถูกตัดกลางทาง
- Greedy ใช้เพียงหนึ่ง evaluation เพราะไม่มี search loop การรันหลาย seed ให้ผลเดิม ไม่ควรตีความเป็น independent stochastic samples
- หยุดเมื่อครบงบหรือเวลาก่อน คำตอบแรกอนุญาตให้ decode จบเพื่อให้มี baseline แม้เกิน cap เล็กน้อย หลังจากนั้นตรวจ deadline ระหว่างคลาส มี worker watchdog อีกชั้นสำหรับโค้ดที่ไม่คืนการควบคุม
- preprocessing/โหลด runtime แยกจาก search time; final independent validation time บันทึกแยก Runtime ขึ้นกับเครื่อง เบราว์เซอร์ tab throttling และ runtime ไม่ใช้เทียบข้ามเครื่องตรง ๆ
- หาก time limit ตัดก่อนงบเท่ากัน ต้องรายงาน evaluations ที่ใช้จริง ควรเพิ่ม cap เมื่อต้องการเทียบด้วย fixed evaluation budget
- วิธีถูกรันเรียงตาม seed แล้วตามวิธี ไม่สลับลำดับแบบสุ่ม จึงอาจมีผลของ warm-up/สภาวะเครื่องต่อเวลา
- มีสถานะ completed / evaluation_budget / time_limit / invalid_solution / error / worker_timeout / cancelled เก็บแถวที่ล้มเหลวด้วย ไม่แทนผลที่ไม่มีด้วยศูนย์
- เฉพาะคำตอบที่ตรวจผ่านและไม่ error จึงเข้าตารางสรุปแยกตามวิธี Summary เรียง median unassigned → median lab minutes → median room changes เป็น descriptive summary ไม่ใช่ statistical test หรือคำตอบจริงหนึ่งตาราง ค่า Lab แสดง mean ± sample SD
- กราฟแสดง best-so-far ตาม lexicographic comparator; ค่า Lab หรือ room changes อาจเพิ่มเมื่อ unassigned ลดลงได้
- เว็บยังไม่ได้ทำ significance tests, parameter tuning อัตโนมัติ หรือแบ่ง held-out test ให้อัตโนมัติ หากปรับพารามิเตอร์จาก seed ใดแล้ว อย่าใช้ชุดเดียวกันสรุป final test โดยไม่ระบุ

## เพิ่มโค้ด Python

แท็บโค้ด Python รับไฟล์ `.py` หรือตัวแก้ไข แล้วกำหนด:

```python
def solve(problem, context, parameters):
    while True:
        context.check()
        context.evaluate(problem.random_genome(context.rng))
```

`context.initial` ใช้งบไปหนึ่งครั้งแล้ว ใช้ `context.rng` เพื่อทำซ้ำตาม seed และเรียก `context.evaluate(genome)` เพื่อให้ทุก candidate นับงบ เมื่อ budget/time exception เกิด runner คืน best-so-far หากคืนค่าเอง ให้คืน `Candidate` หรือ solution object ตาม schema ใน `solution_validator.py`

ใช้โค้ดที่ไว้ใจได้ โค้ดรันใน Python worker ของหน้าเว็บ ซึ่งไม่ใช่กลไกแยกสิทธิ์สำหรับโปรแกรมที่เป็นอันตราย Custom code สามารถใช้สิทธิ์เครือข่าย/worker ของเว็บหรือหลีกเลี่ยงวิธีนับงบได้ ผู้ทดลองต้องตรวจโค้ดก่อนใช้เป็นหลักฐานเปรียบเทียบ Final audit ใช้ snapshot ของ input ก่อนส่งให้ custom code แต่ไม่ได้ป้องกัน custom code แก้ runtime ทั้งระบบ

## รันบนเครื่องและทดสอบ

ไม่มี frontend build และไม่มี backend:

```sh
python3 -m http.server 8766 --bind 127.0.0.1
```

เปิด `http://127.0.0.1:8766` จากโฟลเดอร์โครงการ อย่าเปิด `index.html` แบบ file:// เพราะ worker/fetch ต้องใช้ HTTP(S) ต้องใช้อินเทอร์เน็ตโหลด [Pyodide 314.0.7](https://pyodide.org/en/stable/usage/webworker.html) ผ่าน jsDelivr; ไม่มี service worker หรือการรับประกัน offline

Native Python 3.9+ ใช้ engine เดียวกัน ไม่ต้องลง package เพิ่ม:

```sh
python3 python/cli.py --budget 50 --seconds 60 --seed 42 --repeats 3 --output results
python3 -m unittest discover -s tests -v
```

CLI เก็บ JSON หลังทุกรันและ CSV ตอนจบ JSON นำเข้ากลับเว็บได้ Seed เดียวกันจะทำซ้ำได้เมื่อใช้ dataset/code/parameters/runtime เดียวกันและไม่ถูกตัดด้วยเวลาระหว่างทาง การเปลี่ยน Python เวอร์ชันอาจทำให้ลำดับสุ่มต่างกัน

## สร้าง adapted dataset ซ้ำ

มี converter และ config เดิมใน `dataset_tools/` สร้างลงโฟลเดอร์ใหม่และตรวจ SHA-256 ให้ตรงกับไฟล์ที่เว็บใช้:

```sh
python3 dataset_tools/rebuild.py --output results/rebuilt-dataset
```

คำสั่งนี้ดาวน์โหลด source ZIP จาก UniTime ตาม URL ที่ตรึงไว้ หากมี XML อยู่แล้วใช้ `--source-xml /path/to/pu-fal07-cs.xml` ได้ ไม่แก้ XML ต้นฉบับและไม่เขียนทับ output ที่มีอยู่ `data/START_HERE.txt` เป็นบันทึกจากแพ็กเกจ conversion เดิม คำสั่งในเอกสารนั้นอ้างถึงโครงสร้างแพ็กเกจเดิม ให้ใช้คำสั่งข้างบนใน repo นี้

## โครงสร้างและการเผยแพร่

- `index.html`, `styles.css`, `app.mjs`: UI, plots, export และ result history
- `storage.mjs`: IndexedDB
- `worker.mjs`: pinned Pyodide loader และ Python bridge
- `python/lab_core.py`, `algorithms.py`: shared decoder/search methods
- `python/input_validation.py`, `solution_validator.py`: input และ output checks คนละหน้าที่
- `python/runner.py`, `cli.py`: reproducible runner และ native command line
- `data/`: compressed adapted input, assumptions และ provenance
- `tests/`: meaningful contract/regression checks รวมตัวอย่าง source ID ซ้ำ

Deploy GitHub Pages จาก `main` ที่ `/ (root)` ได้โดยตรง มี `.nojekyll` ไม่ต้องเปิดเผย credentials หรือใช้ server เว็บเป็น local research workbench ไม่ใช่ระบบจัดตารางใช้งานจริงของสถาบัน

ดู [NOTICE](NOTICE) สำหรับสิทธิ์แยกระหว่างโค้ดกับข้อมูลต้นทาง

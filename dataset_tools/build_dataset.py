"""Convert the pinned Fall CS input into a documented synthetic weekly-lab case.

Python 3.9+, standard library only. Run from any directory:
    python3 build_dataset.py
The raw UniTime XML is read only. Configuration/seed are independent of solver seeds.
"""
import argparse
import copy
import csv
import hashlib
import json
import random
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def numeric_id(element):
    return int(element.get('id'))


def source_element(element):
    return {'tag': element.tag, 'attributes': dict(element.attrib),
            'children': [source_element(child) for child in element]}


def room_availability(room, scheduler, slots_per_day):
    """Return half-open minute windows, interpreting room sharing for the scheduler."""
    sharing = room.find('sharing')
    if sharing is None:
        return [{'day': day, 'start_minute': 0, 'end_minute': 1440} for day in range(7)]
    pattern = sharing.find('pattern')
    unit = int(pattern.get('unit'))
    mask = ''.join(pattern.text.split())
    if len(mask) * unit != 7 * slots_per_day:
        raise ValueError('Unexpected room sharing matrix length: ' + room.get('id'))
    allowed = {sharing.find('freeForAll').get('value')}
    allowed.update(d.get('value') for d in sharing.findall('department') if d.get('id') == scheduler)
    forbidden = sharing.find('notAvailable').get('value')
    windows = []
    for day in range(7):
        start = None
        for slot in range(slots_per_day + 1):
            ok = slot < slots_per_day and mask[(day * slots_per_day + slot) // unit] in allowed
            if slot < slots_per_day and mask[(day * slots_per_day + slot) // unit] == forbidden:
                ok = False
            if ok and start is None:
                start = slot
            if not ok and start is not None:
                windows.append({'day': day, 'start_minute': start * 5, 'end_minute': slot * 5})
                start = None
    return windows


def meetings(time_element):
    return [{'day': day, 'start_minute': int(time_element.get('start')) * 5,
             'duration_minutes': int(time_element.get('length')) * 5}
            for day, flag in enumerate(time_element.get('days')) if flag == '1']


def convert(config, source):
    if not 0 <= config['mixed_session_fraction'] <= 1:
        raise ValueError('mixed_session_fraction must be in [0,1]')
    if not 0 < config['lab_weeks_per_mixed_session'] < config['teaching_weeks']:
        raise ValueError('Mixed sessions need both lab and non-lab weeks')
    if config['external_student_conflict_policy'] != 'record_only_department_scope':
        raise ValueError('Unknown external student policy')
    root = ET.parse(source).getroot()
    if root.get('term') != '2007Fal' or root.get('version') != '2.4':
        raise ValueError('Expected Fall 2007 v2.4 source')
    if int(root.get('slotsPerDay')) != 288 or int(root.get('nrDays')) != 7:
        raise ValueError('Expected seven days and five-minute source slots')
    raw_classes = sorted(root.find('classes'), key=numeric_id)
    raw_class_map = {c.get('id'): c for c in raw_classes}

    def inherited_field(c, field):
        seen = set()
        while c is not None:
            if c.get('id') in seen:
                raise ValueError('Cyclic source parent chain')
            seen.add(c.get('id'))
            if c.get(field) is not None:
                return c.get(field)
            c = raw_class_map.get(c.get('parent'))
        raise ValueError('Cannot resolve source ' + field + ' from parent chain')
    targets = [c for c in raw_classes if c.get('committed', 'false') != 'true']
    external = [c for c in raw_classes if c.get('committed', 'false') == 'true']
    if len(targets) != 174:
        raise ValueError('Pinned Fall CS source should contain 174 target classes')
    if {c.get('scheduler') for c in targets} != {'24'}:
        raise ValueError('This adapter expects the Fall CS scheduler 24')
    all_class_ids = {'C' + c.get('id') for c in raw_classes}
    target_ids = {'C' + c.get('id') for c in targets}
    eligible_source_rooms = {r.get('id') for c in targets for r in c.findall('room')}
    weeks = list(range(1, config['teaching_weeks'] + 1))
    source_hash = digest(source)
    if config.get('expected_source_sha256') and source_hash != config['expected_source_sha256']:
        raise ValueError('Source hash differs from pinned configuration')
    raw_rooms = {r.get('id'): r for r in root.find('rooms')}
    rooms = []
    for room in sorted(raw_rooms.values(), key=numeric_id):
        rid = room.get('id')
        schedulable = rid in eligible_source_rooms
        if schedulable and room.get('constraint', 'true') != 'true':
            raise ValueError('Room sharing exceptions need a separate adapter')
        rooms.append({
            'id': 'R' + rid, 'source_room_id': rid,
            'kind': 'lecture' if schedulable else 'background_only',
            'schedulable': schedulable, 'capacity': int(room.get('capacity')),
            'availability': room_availability(room, '24', 288),
            'capacity_origin': 'source', 'kind_origin': 'assumption_A03' if schedulable else 'adapter_role',
            'source_attributes': dict(room.attrib),
        })
    for number, capacity in enumerate(config['synthetic_lab_capacities'], 1):
        rooms.append({
            'id': f'SIM-LAB-{number:02}', 'source_room_id': None,
            'kind': 'computer_lab', 'schedulable': True, 'capacity': capacity,
            'availability': [{'day': day, 'start_minute': 0, 'end_minute': 1440} for day in range(5)],
            'capacity_origin': 'assumption_A04', 'kind_origin': 'assumption_A04',
            'source_attributes': {},
        })
    room_map = {r['id']: r for r in rooms}

    # Preserve assigned rosters, grouping only students whose complete modeled rosters match.
    roster_members = defaultdict(list)
    observed = Counter()
    outside_references = set()
    for student in sorted(root.find('students'), key=numeric_id):
        roster = {'C' + c.get('id') for c in student.findall('class')}
        outside_references.update(roster - all_class_ids)
        modeled = tuple(sorted(roster & all_class_ids, key=lambda s: int(s[1:])))
        observed.update(modeled)
        if set(modeled) & target_ids:
            roster_members[modeled].append(student.get('id'))
    groups = []
    class_groups = defaultdict(list)
    for number, (roster, members) in enumerate(sorted(roster_members.items()), 1):
        gid = f'G{number:04}'
        groups.append({'id': gid, 'source_student_ids': members,
                       'known_student_count': len(members), 'class_ids': list(roster),
                       'origin': 'source_assigned_roster_equivalence_group'})
        for cid in roster:
            class_groups[cid].append(gid)
    all_instructors = {'T' + i.get('id') for c in raw_classes for i in c.findall('instructor')}
    instructors = [{'id': tid, 'source_instructor_id': tid[1:], 'origin': 'source'}
                   for tid in sorted(all_instructors, key=lambda s: int(s[1:]))]
    classes, sessions, time_selection = [], [], []
    missing_teachers = []
    for c in targets:
        sid, cid = c.get('id'), 'C' + c.get('id')
        times = c.findall('time')
        shapes = Counter((len(meetings(t)), int(t.get('length')) * 5) for t in times)
        shape = sorted(shapes, key=lambda s: (-shapes[s], s[0], s[1]))[0]
        weekly_minutes = {n * duration for n, duration in shapes}
        if len(weekly_minutes) != 1:
            raise ValueError('Alternative patterns have unequal weekly contact time: ' + cid)
        kept_indices = [i for i, t in enumerate(times)
                        if (len(meetings(t)), int(t.get('length')) * 5) == shape]
        session_ids = [f'{cid}-M{i+1}' for i in range(shape[0])]
        instructors_for_class = ['T' + i.get('id') for i in c.findall('instructor')]
        if not instructors_for_class:
            teacher = 'SIM-T-' + sid
            instructors_for_class = [teacher]
            instructors.append({'id': teacher, 'source_instructor_id': None,
                                'origin': 'assumption_A05', 'for_class_id': cid})
            missing_teachers.append(cid)
        source_room_ids = ['R' + r.get('id') for r in c.findall('room')]
        demand = int(c.get('classLimit'))
        lecture_rooms = [rid for rid in source_room_ids if room_map[rid]['capacity'] >= demand]
        lab_rooms = [r['id'] for r in rooms if r['kind'] == 'computer_lab' and r['capacity'] >= demand]
        options = []
        for i in kept_indices:
            ms = meetings(times[i])
            for m, session_id in zip(ms, session_ids):
                m['session_id'] = session_id
            options.append({'id': f'{cid}-T{i:03}', 'source_time_index': i, 'meetings': ms})
        classes.append({
            'id': cid, 'course_id': 'O' + inherited_field(c, 'offering'),
            'source_class_id': sid, 'source_offering_id': c.get('offering'),
            'resolved_source_offering_id': inherited_field(c, 'offering'),
            'course_id_origin': 'source_offering' if c.get('offering') else 'source_parent_offering',
            'source_config_id': c.get('config'), 'source_subpart_id': c.get('subpart'),
            'source_parent_class_id': c.get('parent'),
            'scheduler_id': '24', 'student_count': demand,
            'student_count_origin': 'source_classLimit_used_as_seat_demand_A06',
            'known_enrolled_student_count': observed[cid],
            'instructor_ids': instructors_for_class, 'student_group_ids': class_groups[cid],
            'lecture_room_ids': lecture_rooms, 'lab_room_ids': lab_rooms,
            'source_allowed_room_ids': source_room_ids,
            'session_ids': session_ids, 'time_options': options,
            'source_dates_mask': c.get('dates'),
        })
        for ordinal, session_id in enumerate(session_ids, 1):
            sessions.append({'id': session_id, 'class_id': cid, 'ordinal': ordinal,
                             'duration_minutes': shape[1], 'active_weeks': weeks[:],
                             'lab_weeks': [], 'lab_requirement_origin': 'synthetic_A10'})
        time_selection.append({
            'class_id': cid, 'source_time_options': len(times), 'kept_time_indices': kept_indices,
            'dropped_time_indices': [i for i in range(len(times)) if i not in kept_indices],
            'selected_shape': {'meetings_per_week': shape[0], 'duration_minutes': shape[1]},
            'weekly_contact_minutes_preserved': next(iter(weekly_minutes)),
        })
    # Exactly rounded fraction, deterministic for the same source/configuration.
    session_order = sorted(s['id'] for s in sessions)
    rng = random.Random(config['seed'])
    rng.shuffle(session_order)
    mixed_count = int(len(sessions) * config['mixed_session_fraction'] + 0.5)
    mixed_ids = set(session_order[:mixed_count])
    for session in sessions:
        if session['id'] in mixed_ids:
            session['lab_weeks'] = sorted(rng.sample(weeks, config['lab_weeks_per_mixed_session']))

    external_classes = []
    for c in external:
        cid = 'C' + c.get('id')
        selected_times = [t for t in c.findall('time') if t.get('solution') == 'true']
        selected_rooms = [r for r in c.findall('room') if r.get('solution') == 'true']
        if len(selected_times) != 1:
            raise ValueError('Committed class should have one fixed pattern: ' + cid)
        external_classes.append({
            'id': cid, 'source_class_id': c.get('id'),
            'room_ids': ['R' + r.get('id') for r in selected_rooms],
            'instructor_ids': ['T' + i.get('id') for i in c.findall('instructor')],
            'student_group_ids': class_groups[cid],
            'meetings': meetings(selected_times[0]), 'active_weeks': weeks[:],
            'source_dates_mask': c.get('dates'), 'calendar_origin': 'synthetic_normalization_A09',
        })

    non_overlap, same_time, source_constraints = [], [], []
    for constraint in sorted(root.find('groupConstraints'), key=numeric_id):
        kind, pref = constraint.get('type'), constraint.get('pref')
        ids = ['C' + c.get('id') for c in constraint.findall('class')]
        mapped = None
        if pref == 'R' and kind in {'DIFF_TIME', 'SAME_STUDENTS'}:
            mapped = 'non_overlap'
            non_overlap.append({'source_constraint_id': constraint.get('id'),
                                'source_type': kind, 'class_ids': ids})
        elif pref == 'R' and kind == 'SAME_TIME':
            mapped = 'same_time_of_day_containment'
            same_time.append({'source_constraint_id': constraint.get('id'), 'class_ids': ids})
        source_constraints.append({'source': source_element(constraint), 'adapted_rule': mapped,
                                   'note': 'travel_distance_component_omitted' if kind == 'SAME_STUDENTS'
                                   else ('archived_not_scored_A08' if mapped is None else 'retained')})
    assumptions = [
        {'id': 'A01', 'field': 'calendar', 'assumption': f"ใช้ปฏิทินจำลอง {config['teaching_weeks']} สัปดาห์ ทุกคลาสเปิดสอนครบทุกสัปดาห์ ไม่มีวันหยุด; ไม่ใช่ปฏิทิน Fall 2007 จริง",
         'source_difference': 'ต้นฉบับมี date masks หลายแบบ รวมถึง 17 target classes ที่มีช่วงสอนสั้นกว่าแบบหลัก'},
        {'id': 'A02', 'field': 'classes.time_options', 'assumption': 'ต่อคลาส เลือกรูปแบบจำนวนคาบ/ความยาวที่มีตัวเลือกต้นฉบับมากที่สุด; ถ้าเสมอเลือกจำนวนคาบน้อยกว่าแล้วความยาวน้อยกว่า',
         'reason': 'ทำให้จำนวน recurring sessions และตัวหารคาบรายสัปดาห์คงที่ระหว่างอัลกอริทึม โดยรักษานาทีเรียนต่อสัปดาห์เดิม',
         'affected_classes': sum(bool(x['dropped_time_indices']) for x in time_selection),
         'dropped_time_options': sum(len(x['dropped_time_indices']) for x in time_selection)},
        {'id': 'A03', 'field': 'rooms.kind', 'assumption': 'กำหนดห้องต้นฉบับ 13 ห้องใน target domains เป็นห้องบรรยายในแบบจำลอง; ไม่ใช่การยืนยันประเภทห้องจริง',
         'preserved': 'รหัสห้อง ความจุ รายการห้องเดิมของแต่ละคลาส และ room-sharing ของ scheduler 24'},
        {'id': 'A04', 'field': 'rooms.SIM-LAB-*', 'assumption': f"เพิ่มห้องคอมพิวเตอร์จำลอง {len(config['synthetic_lab_capacities'])} ห้อง ความจุ {config['synthetic_lab_capacities']} คน เป็นทรัพยากรใหม่แยกจากห้องจริง",
         'availability': 'จันทร์-ศุกร์ 00:00-24:00; แต่คลาสยังเลือกได้เฉพาะเวลาต้นฉบับ; ไม่มีการจองภายนอกของ Lab จำลอง',
         'compatibility': 'ทุก Lab จำลองรองรับกิจกรรมทุกชนิดของกรณีนี้ได้เมื่อความจุพอ',
         'impact': 'เพิ่มทรัพยากรและขยายโดเมนห้องด้วย Lab จำลอง ทำให้ความยากต่างจาก benchmark เดิม'},
        {'id': 'A05', 'field': 'instructors', 'assumption': 'คลาสที่ไม่มีผู้สอนใช้รหัสผู้สอนจำลองหนึ่งคนต่อคลาส ไม่สร้างความสัมพันธ์ร่วมผู้สอนที่ไม่ทราบ',
         'affected_classes': len(missing_teachers), 'impact': 'อาจประเมินความหนาแน่นผู้สอนต่ำกว่าสถานการณ์จริง'},
        {'id': 'A06', 'field': 'classes.student_count', 'assumption': 'ใช้ classLimit เป็นจำนวนที่นั่งที่ต้องรองรับ ไม่ใช่จำนวนผู้ลงทะเบียนจริง; ใช้ roster ที่มีจริงสำหรับความขัดแย้ง',
         'zero_observed_enrollment_classes': sum(observed[c['id']] == 0 for c in classes)},
        {'id': 'A07', 'field': 'student_groups', 'assumption': 'รวมเฉพาะนักศึกษาที่มีรายการคลาสที่ลงไว้เหมือนกันทุกตัวเป็นกลุ่มเชิงเทคนิค และห้ามกลุ่มซ้อนเวลา',
         'department_scope': 'กรณีหลักห้ามกลุ่มนักศึกษาซ้อนกันระหว่าง target classes ใน CS; กับ committed classes ภายนอกให้เก็บ roster ไว้เป็นข้อมูล แต่ไม่ใช้เป็น hard conflict',
         'strict_background_variant': 'ไฟล์ strict-background ยกระดับ student overlap กับ committed classes ภายนอกเป็น hard ด้วย โดยใช้ข้อมูล Lab/เวลา/ห้องเดียวกับกรณีหลัก',
         'impact': 'ต้นฉบับมี student conflicts เป็น soft และอาจแก้ด้วย re-sectioning; การยกระดับเป็น hard ทั้งหมดอาจทำให้กรณีเข้มงวดจัดครบไม่ได้; ไม่ทำ re-sectioning หรือสร้างหลักสูตร/cohort ที่ไม่มีในข้อมูล',
         'outside_xml_class_references_omitted': sorted(outside_references)},
        {'id': 'A08', 'field': 'constraints', 'assumption': 'เก็บ non-overlap จาก DIFF_TIME/R และ SAME_STUDENTS/R รวมทั้ง SAME_TIME/R; เก็บ source constraints ทุกตัวไว้ตรวจย้อนหลัง',
         'omitted': 'SPREAD, soft preferences ของเวลา/ห้อง/กลุ่ม, ระยะเดินทาง, departmental balancing และเกณฑ์ UniTime อื่นที่ไม่อยู่ในเป้าหมายโครงงาน',
         'retained_non_overlap_groups': len(non_overlap), 'retained_same_time_groups': len(same_time),
         'archived_unscored_constraints': sum(x['adapted_rule'] is None for x in source_constraints)},
        {'id': 'A09', 'field': 'external_classes', 'assumption': f"เก็บ committed classes ทั้งหมดเป็นการจองล็อก และใช้รูปแบบสัปดาห์เดิมซ้ำครบ {config['teaching_weeks']} สัปดาห์จำลอง",
         'enforced_in_main': 'ห้อง ผู้สอน และ explicit source distribution rules ที่เก็บไว้; student overlap กับภายนอกขึ้นกับ variant A07',
         'impact': 'อาจจำกัดเวลามากกว่าปฏิทินจริงของคลาสภายนอกบางคลาส; ไม่ใช่ผลพิสูจน์ว่าตารางทั้งหมดจัดครบได้'},
        {'id': 'A10', 'field': 'recurring_sessions.lab_weeks', 'assumption': f"สุ่มเลือก {config['mixed_session_fraction']*100:g}% ของ recurring sessions (ปัดใกล้สุด) ให้ใช้ Lab {config['lab_weeks_per_mixed_session']} จาก {config['teaching_weeks']} สัปดาห์โดยไม่ซ้ำ ส่วนที่เหลือไม่ต้องใช้ Lab",
         'seed': config['seed'], 'mixed_session_count': mixed_count, 'lecture_only_session_count': len(sessions)-mixed_count,
         'impact': 'เป็นสถานการณ์ทดลอง ไม่ใช่พฤติกรรมการใช้ Lab ที่สำรวจจริง; seed นี้เป็น seed สร้างข้อมูล ไม่ใช่ seed ของอัลกอริทึม'},
        {'id': 'A11', 'field': 'names_and_units', 'assumption': 'ใช้รหัส O*/C*/R*/T* แทนชื่อที่ต้นฉบับไม่ระบุ; คลาสลูกที่ไม่มี offering ใช้ offering จาก parent chain ของต้นฉบับ; แปลง source slot ละ 5 นาทีเป็นนาทีหลังเที่ยงคืน; วัน 0=จันทร์ ถึง 6=อาทิตย์; ช่วงเวลาเป็น [start,end)'},
        {'id': 'A12', 'field': 'objectives', 'assumption': 'แต่ละ meeting ใน pattern เป็น recurring session แยก; เลือกหนึ่ง time option ต่อคลาสร่วมกันทุกสัปดาห์ แต่กำหนดห้องแยก session/week ได้',
         'priority': ['unassigned_weekly_sessions', 'unnecessary_lab_minutes', 'room_changes'],
         'room_changes': 'เทียบห้องของ recurring session เดียวกันกับสัปดาห์ก่อนหน้าล่าสุดที่จัดได้ ข้ามสัปดาห์ที่ยังจัดไม่ได้'},
    ]
    data = {
        'schema_version': config['schema_version'], 'dataset_id': config['dataset_id'],
        'benchmark_kind': 'adapted_synthetic_from_unitime_not_original_score',
        'source': {'url': config['source_url'], 'xml_path_relative_to_config': config['source_xml'],
                   'sha256': source_hash, 'root_attributes': dict(root.attrib)},
        'generator': {'version': '1.0', 'seed': config['seed'], 'config': config},
        'calendar': {'week_ids': weeks, 'day_names': ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'],
                     'time_unit': 'minute_after_midnight', 'interval_convention': '[start,end)',
                     'synthetic': True},
        'rooms': rooms, 'instructors': instructors, 'student_groups': groups,
        'classes': classes, 'recurring_sessions': sessions, 'external_classes': external_classes,
        'constraints': {'non_overlap_groups': non_overlap, 'same_time_of_day_groups': same_time,
                        'student_group_overlap_is_hard': True,
                        'external_student_overlap_is_hard': False,
                        'instructor_overlap_is_hard': True, 'room_overlap_is_hard': True,
                        'capacity_is_hard': True, 'lab_requirement_is_hard': True,
                        'one_time_option_per_class_for_all_weeks': True,
                        'non_lab_sessions_may_use_labs': True},
        'objectives': {'comparison': 'lexicographic_minimize',
                       'ordered_metrics': ['unassigned_weekly_sessions','unnecessary_lab_minutes','room_changes'],
                       'lab_hours': 'unnecessary_lab_minutes / 60',
                       'room_change_policy': 'previous_successfully_assigned_week_of_same_recurring_session'},
        'assumption_ids': [a['id'] for a in assumptions],
    }
    audit = {'source_sha256': source_hash, 'source_target_classes': len(targets),
             'source_committed_classes': len(external),
             'course_ids_are_source_offering_ids': True,
             'time_option_selection': time_selection,
             'missing_instructor_class_ids': missing_teachers,
             'all_source_group_constraints': source_constraints}
    return data, assumptions, audit


def export_csvs(data, output):
    classes = {c['id']: c for c in data['classes']}
    with (output/'lab_requirements.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['session_id','source_class_id','course_id','duration_minutes','student_count','active_weeks','lab_weeks','synthetic'])
        writer.writeheader()
        for session in data['recurring_sessions']:
            c = classes[session['class_id']]
            writer.writerow({'session_id': session['id'], 'source_class_id': c['source_class_id'],
                             'course_id': c['course_id'], 'duration_minutes': session['duration_minutes'],
                             'student_count': c['student_count'],
                             'active_weeks': ';'.join(map(str, session['active_weeks'])),
                             'lab_weeks': ';'.join(map(str, session['lab_weeks'])), 'synthetic': True})
    with (output/'rooms.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['room_id','source_room_id','kind','capacity','capacity_origin','kind_origin'])
        writer.writeheader()
        for r in data['rooms']:
            if r['schedulable']:
                writer.writerow({key: r.get(key) for key in writer.fieldnames if key != 'room_id'} | {'room_id':r['id']})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=HERE/'config.json')
    parser.add_argument('--output', type=Path, default=HERE)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8'))
    source = (args.config.resolve().parent/config['source_xml']).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    before = digest(source)
    data, assumptions, audit = convert(config, source)
    args.output.mkdir(parents=True, exist_ok=True)
    write_json(args.output/'dataset.json', data)
    write_json(args.output/'assumptions.json', assumptions)
    write_json(args.output/'conversion_audit.json', audit)
    write_json(args.output/'solution_template.json', {
        'dataset_id': data['dataset_id'],
        'class_time_options': {c['id']: None for c in data['classes']},
        'weekly_room_assignments': [],
    })
    export_csvs(data, args.output)
    if digest(source) != before:
        raise RuntimeError('Source changed during conversion')
    from validate_dataset import validate
    report = validate(data)
    write_json(args.output/'validation_report.json', report)
    strict = copy.deepcopy(data)
    strict['dataset_id'] += '-strict-background'
    strict['constraints']['external_student_overlap_is_hard'] = True
    strict['generator']['variant'] = 'strict_background_students'
    strict['generator']['overrides'] = {'external_student_overlap_is_hard': True}
    strict_report = validate(strict)
    write_json(args.output/'dataset.strict-background.json', strict)
    write_json(args.output/'validation_report.strict-background.json', strict_report)
    files = ['dataset.json','assumptions.json','conversion_audit.json','lab_requirements.csv','rooms.csv','validation_report.json','solution_template.json']
    files += ['dataset.strict-background.json','validation_report.strict-background.json']
    write_json(args.output/'manifest.json', {'source_sha256': before,
               'code_inputs': {'build_dataset.py':digest(Path(__file__).resolve()),
                               'validate_dataset.py':digest(HERE/'validate_dataset.py'),
                               'config.json':digest(args.config)},
               'generated_files': {name: {'sha256':digest(args.output/name),'bytes':(args.output/name).stat().st_size} for name in files}})
    print(json.dumps(report['summary'], ensure_ascii=False, indent=2))
    print('Validation:', report['status'])
    print('Strict background local impossible weekly sessions:', strict_report['summary'].get('weekly_sessions_without_any_local_placement'))
    if report['errors'] or strict_report['errors']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

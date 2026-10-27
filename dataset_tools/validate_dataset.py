"""Independent checks of the converted input, not a proof of global schedulability.

Run: python3 validate_dataset.py dataset.json
All times are minute values, intervals are half-open, and day 0 is Monday.
"""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def overlap(a, b):
    return (a['day'] == b['day'] and
            a['start_minute'] < b['start_minute'] + b['duration_minutes'] and
            b['start_minute'] < a['start_minute'] + a['duration_minutes'])


def fits_window(meeting, room):
    return any(w['day'] == meeting['day'] and w['start_minute'] <= meeting['start_minute']
               and meeting['start_minute'] + meeting['duration_minutes'] <= w['end_minute']
               for w in room['availability'])


def same_time_of_day(a, b):
    """UniTime SAME_TIME: the shorter meeting's time interval is inside the longer."""
    shorter, longer = sorted([a, b], key=lambda m: m['duration_minutes'])
    return (longer['start_minute'] <= shorter['start_minute'] and
            shorter['start_minute'] + shorter['duration_minutes'] <=
            longer['start_minute'] + longer['duration_minutes'])


def validate(data):
    errors, warnings = [], []

    def require(condition, message):
        if not condition:
            errors.append(message)

    required = ['schema_version','dataset_id','calendar','rooms','instructors','student_groups',
                'classes','recurring_sessions','external_classes','constraints','objectives']
    for key in required:
        require(key in data, 'Missing top-level field: ' + key)
    if errors:
        return {'status':'failed','errors':errors,'warnings':warnings,'summary':{}}
    require(data['schema_version'] == '1.0', 'Unsupported schema version')
    collections = ['rooms','instructors','student_groups','classes','recurring_sessions','external_classes']
    maps = {}
    for key in collections:
        ids = [item['id'] for item in data[key]]
        require(len(ids) == len(set(ids)), 'Duplicate IDs in ' + key)
        maps[key] = {item['id']:item for item in data[key]}
    rooms, teachers, groups = maps['rooms'], maps['instructors'], maps['student_groups']
    classes, sessions, external = maps['classes'], maps['recurring_sessions'], maps['external_classes']
    known_class_ids = set(classes) | set(external)
    require(not (set(classes) & set(external)), 'Target and external class IDs overlap')
    weeks = data['calendar']['week_ids']
    require(weeks == list(range(1, len(weeks)+1)) and bool(weeks), 'Weeks must be contiguous positive IDs')
    for r in rooms.values():
        require(isinstance(r['capacity'], int) and r['capacity'] >= 0, 'Invalid capacity: ' + r['id'])
        require(r['kind'] in {'lecture','computer_lab','background_only'}, 'Unknown room kind: ' + r['id'])
        require(not r['schedulable'] or r['kind'] != 'background_only', 'Background room is schedulable: '+r['id'])
        for w in r['availability']:
            require(0 <= w['day'] <= 6 and 0 <= w['start_minute'] < w['end_minute'] <= 1440,
                    'Invalid availability interval: ' + r['id'])
    for g in groups.values():
        require(set(g['class_ids']) <= known_class_ids, 'Unknown class in group: ' + g['id'])
        require(len(g['source_student_ids']) == len(set(g['source_student_ids'])) == g['known_student_count'],
                'Student group count/IDs disagree: ' + g['id'])
    source_students = [sid for g in groups.values() for sid in g['source_student_ids']]
    require(len(source_students) == len(set(source_students)), 'A student is duplicated across roster groups')
    option_ids = []
    referenced_sessions = []
    for c in classes.values():
        cid = c['id']
        require(set(c['instructor_ids']) <= set(teachers) and bool(c['instructor_ids']), 'Invalid instructor reference: '+cid)
        require(set(c['student_group_ids']) <= set(groups), 'Invalid student group reference: '+cid)
        require(isinstance(c['student_count'],int) and c['student_count']>0, 'Invalid student demand: '+cid)
        require(c['known_enrolled_student_count'] <= c['student_count'], 'Known enrollment exceeds seat demand: '+cid)
        require(sum(groups[g]['known_student_count'] for g in c['student_group_ids'] if g in groups)
                == c['known_enrolled_student_count'], 'Roster count does not reconcile: '+cid)
        for gid in c['student_group_ids']:
            if gid in groups:
                require(cid in groups[gid]['class_ids'], 'Group membership not reciprocal: '+cid)
        require(set(c['source_allowed_room_ids']) <= set(rooms), 'Unknown source room: '+cid)
        require(set(c['lecture_room_ids']) <= set(c['source_allowed_room_ids']), 'Lecture domain expanded without provenance: '+cid)
        for field, kind in [('lecture_room_ids','lecture'),('lab_room_ids','computer_lab')]:
            require(bool(c[field]), 'Empty capacity-compatible '+field+': '+cid)
            for rid in c[field]:
                require(rid in rooms, 'Unknown room '+rid+' in '+cid)
                if rid in rooms:
                    require(rooms[rid]['schedulable'] and rooms[rid]['kind']==kind and
                            rooms[rid]['capacity']>=c['student_count'], 'Invalid room eligibility: '+cid+'/'+rid)
        referenced_sessions.extend(c['session_ids'])
        require(bool(c['time_options']), 'Empty time domain: '+cid)
        for option in c['time_options']:
            option_ids.append(option['id'])
            require([m['session_id'] for m in option['meetings']] == c['session_ids'], 'Option/session mapping differs: '+option['id'])
            for m in option['meetings']:
                require(m['session_id'] in sessions, 'Unknown session in option: '+option['id'])
                require(0 <= m['day'] <= 6 and 0 <= m['start_minute'] < m['start_minute']+m['duration_minutes'] <= 1440,
                        'Invalid meeting bounds: '+option['id'])
                require(m['start_minute']%5==0 and m['duration_minutes']%5==0 and m['duration_minutes']>0,
                        'Invalid source time units: '+option['id'])
                if m['session_id'] in sessions:
                    require(m['duration_minutes']==sessions[m['session_id']]['duration_minutes'], 'Duration not fixed: '+option['id'])
    require(len(option_ids)==len(set(option_ids)), 'Duplicate time option IDs')
    require(len(referenced_sessions)==len(set(referenced_sessions)) and set(referenced_sessions)==set(sessions),
            'Recurring session references are missing or duplicated')
    for s in sessions.values():
        require(s['class_id'] in classes, 'Session references unknown class: '+s['id'])
        require(len(s['active_weeks'])==len(set(s['active_weeks'])) and set(s['active_weeks']) <= set(weeks), 'Invalid active weeks: '+s['id'])
        require(s['lab_weeks']==sorted(set(s['lab_weeks'])) and set(s['lab_weeks']) <= set(s['active_weeks']), 'Invalid lab weeks: '+s['id'])
    for e in external.values():
        require(set(e['room_ids']) <= set(rooms), 'Unknown fixed room: '+e['id'])
        require(set(e['instructor_ids']) <= set(teachers), 'Unknown fixed instructor: '+e['id'])
        require(set(e['student_group_ids']) <= set(groups), 'Unknown fixed student group: '+e['id'])
        require(set(e['active_weeks']) <= set(weeks) and bool(e['meetings']), 'Invalid fixed calendar: '+e['id'])
    for kind in ['non_overlap_groups','same_time_of_day_groups']:
        for constraint in data['constraints'][kind]:
            require(set(constraint['class_ids']) <= known_class_ids, 'Unknown class in '+kind+': '+constraint['source_constraint_id'])
    require(data['objectives']['ordered_metrics']==['unassigned_weekly_sessions','unnecessary_lab_minutes','room_changes'], 'Objective priority changed')
    if errors:
        return {'status':'failed','errors':errors,'warnings':warnings,'summary':{}}

    # Necessary local checks: each target against locked classes, not against other targets.
    ext_by_room, ext_by_teacher, ext_by_group = defaultdict(list), defaultdict(list), defaultdict(list)
    for e in external.values():
        for field, table in [('room_ids',ext_by_room),('instructor_ids',ext_by_teacher),('student_group_ids',ext_by_group)]:
            for rid in e[field]:
                table[rid].append(e)
    extra_conflicts, same_time_links = defaultdict(set), defaultdict(set)
    for constraint in data['constraints']['non_overlap_groups']:
        ids = set(constraint['class_ids'])
        for cid in ids & set(classes):
            extra_conflicts[cid].update(ids & set(external))
    for constraint in data['constraints']['same_time_of_day_groups']:
        ids = set(constraint['class_ids'])
        for cid in ids & set(classes):
            same_time_links[cid].update(ids & set(external))
    local_impossible, incomplete_classes = [], []
    complete_option_count = {}
    for c in classes.values():
        person_external = set(extra_conflicts[c['id']])
        for tid in c['instructor_ids']:
            person_external.update(e['id'] for e in ext_by_teacher[tid])
        if data['constraints']['external_student_overlap_is_hard']:
            for gid in c['student_group_ids']:
                person_external.update(e['id'] for e in ext_by_group[gid])
        possible = set()
        complete_count = 0
        for option in c['time_options']:
            relation_ok = all(same_time_of_day(option['meetings'][0], external[eid]['meetings'][0])
                              for eid in same_time_links[c['id']])
            complete = relation_ok
            for m in option['meetings']:
                session = sessions[m['session_id']]
                for week in session['active_weeks']:
                    people_free = relation_ok and not any(week in external[eid]['active_weeks'] and
                        any(overlap(m, fixed) for fixed in external[eid]['meetings']) for eid in person_external)
                    eligible = c['lab_room_ids'] if week in session['lab_weeks'] else c['lecture_room_ids']+c['lab_room_ids']
                    room_free = people_free and any(fits_window(m, rooms[rid]) and not any(
                        week in fixed['active_weeks'] and any(overlap(m, f) for f in fixed['meetings'])
                        for fixed in ext_by_room[rid]) for rid in eligible)
                    if room_free:
                        possible.add((session['id'],week))
                    else:
                        complete = False
            complete_count += int(complete)
        complete_option_count[c['id']] = complete_count
        if not complete_count:
            incomplete_classes.append(c['id'])
        for sid in c['session_ids']:
            for week in sessions[sid]['active_weeks']:
                if (sid,week) not in possible:
                    local_impossible.append({'session_id':sid,'week':week})
    if local_impossible:
        warnings.append({'code':'LOCAL_INFEASIBILITY','weekly_session_count':len(local_impossible),
                         'meaning':'No local placement against fixed background; global completeness is impossible under this model.'})
    synthetic_teachers = sum(t['origin']=='assumption_A05' for t in teachers.values())
    warnings.extend([
        {'code':'SYNTHETIC_ROOM_TYPES_AND_LABS','meaning':'Source candidate rooms are modeled as lecture rooms; independent synthetic labs are added.'},
        {'code':'MISSING_SOURCE_INSTRUCTORS','classes':synthetic_teachers,'meaning':'Unique synthetic instructors add no unknown shared-teacher conflicts.'},
        {'code':'SYNTHETIC_CALENDAR','meaning':'All target and external classes repeat for the synthetic calendar; source dates masks are provenance only.'},
        {'code':'ADAPTED_STUDENT_RULE','external_student_overlap_is_hard':data['constraints']['external_student_overlap_is_hard'],
         'meaning':'Known student groups cannot overlap among CS targets; external-student conflicts are hard only in the strict variant. Original student-conflict score and re-sectioning are not reproduced.'},
        {'code':'GLOBAL_FEASIBILITY_NOT_PROVEN','meaning':'Local checks do not jointly assign target classes or certify a complete timetable.'},
    ])
    lab_counts = Counter(week for s in sessions.values() for week in s['lab_weeks'])
    summary = {
        'target_classes':len(classes), 'source_course_offerings':len({c['course_id'] for c in classes.values()}),
        'recurring_sessions':len(sessions), 'weeks':len(weeks),
        'weekly_sessions':sum(len(s['active_weeks']) for s in sessions.values()),
        'lab_required_weekly_sessions':sum(len(s['lab_weeks']) for s in sessions.values()),
        'lab_required_minutes':sum(len(s['lab_weeks'])*s['duration_minutes'] for s in sessions.values()),
        'mixed_recurring_sessions':sum(bool(s['lab_weeks']) for s in sessions.values()),
        'lecture_only_recurring_sessions':sum(not s['lab_weeks'] for s in sessions.values()),
        'source_schedulable_lecture_rooms':sum(r['kind']=='lecture' and r['schedulable'] for r in rooms.values()),
        'synthetic_computer_labs':sum(r['kind']=='computer_lab' for r in rooms.values()),
        'background_only_room_records':sum(not r['schedulable'] for r in rooms.values()),
        'committed_classes':len(external), 'synthetic_instructor_classes':synthetic_teachers,
        'student_roster_groups':len(groups), 'known_students_in_target_rosters':len(source_students),
        'classes_without_known_enrollment':sum(c['known_enrolled_student_count']==0 for c in classes.values()),
        'classes_without_locally_complete_time_option':len(incomplete_classes),
        'weekly_sessions_without_any_local_placement':len(local_impossible),
    }
    return {'status':'passed_with_warnings','errors':errors,'warnings':warnings,'summary':summary,
            'lab_required_meetings_per_week':{str(w):lab_counts[w] for w in weeks},
            'local_feasibility':{'scope':'Against external room/instructor reservations, conditional external student rule, room windows, capacity/type and fixed SAME_TIME only; other targets not jointly scheduled.',
                                'complete_time_option_counts':complete_option_count,
                                'classes_without_complete_time_option':incomplete_classes,
                                'weekly_sessions_without_any_placement':local_impossible}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset',type=Path,nargs='?',default=Path(__file__).resolve().parent/'dataset.json')
    args=parser.parse_args()
    report=validate(json.loads(args.dataset.read_text(encoding='utf-8')))
    print(json.dumps(report,ensure_ascii=False,indent=2))
    raise SystemExit(bool(report['errors']))


if __name__=='__main__':
    main()

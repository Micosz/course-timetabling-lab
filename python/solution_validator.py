"""Audit returned schedules from raw input records, independently of search caches."""
from collections import defaultdict
from itertools import combinations


def audit_solution(data, solution):
    violations = []
    seen_errors = set()

    def error(code, detail):
        key = (code, str(detail))
        if key not in seen_errors:
            seen_errors.add(key)
            if len(violations) < 200:
                violations.append({'code': code, 'detail': detail})

    if not isinstance(solution, dict):
        return {'valid': False, 'violation_count': 1,
                'violations': [{'code':'SCHEMA','detail':'Solution must be an object'}], 'metrics': None}
    classes = {c['id']:c for c in data['classes']}
    sessions = {s['id']:s for s in data['recurring_sessions']}
    rooms = {r['id']:r for r in data['rooms']}
    choices = solution.get('class_time_options', {})
    rows = solution.get('weekly_room_assignments', [])
    if solution.get('dataset_id') != data['dataset_id']:
        error('DATASET_ID', 'Solution belongs to a different dataset')
    if not isinstance(choices, dict) or not isinstance(rows, list):
        return {'valid':False,'violation_count':1,'violations':[{'code':'SCHEMA','detail':'Invalid schedule fields'}],'metrics':None}
    for cid in choices:
        if cid not in classes:
            error('UNKNOWN_CLASS', cid)
    selected = {}
    class_meetings = {}
    for cid, c in classes.items():
        value = choices.get(cid)
        if value is None:
            continue
        option = next((o for o in c['time_options'] if o['id'] == value), None)
        if option is None:
            error('TIME_OPTION', cid)
            continue
        selected[cid] = option
        for meeting in option['meetings']:
            class_meetings[meeting['session_id']] = meeting
    events = []
    assigned = {}
    lab_minutes = 0
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            error('SCHEMA', f'Assignment {index} is not an object')
            continue
        sid, week, rid = row.get('session_id'), row.get('week'), row.get('room_id')
        if sid not in sessions or type(week) is not int or rid not in rooms:
            error('ASSIGNMENT_REFERENCE', index)
            continue
        key = (sid, week)
        if key in assigned:
            error('DUPLICATE_SESSION_WEEK', key)
            continue
        s = sessions[sid]
        c = classes[s['class_id']]
        room = rooms[rid]
        if week not in s['active_weeks']:
            error('INACTIVE_WEEK', key)
            continue
        if sid not in class_meetings:
            error('MISSING_TIME', key)
            continue
        meeting = class_meetings[sid]
        assigned[key] = rid
        need_lab = week in s['lab_weeks']
        domain = c['lab_room_ids'] if need_lab else c['lecture_room_ids'] + c['lab_room_ids']
        if rid not in domain or not room['schedulable']:
            error('ROOM_DOMAIN', key)
        if room['capacity'] < c['student_count']:
            error('CAPACITY', key)
        if need_lab and room['kind'] != 'computer_lab':
            error('LAB_REQUIRED', key)
        end = meeting['start_minute'] + meeting['duration_minutes']
        if not any(w['day'] == meeting['day'] and w['start_minute'] <= meeting['start_minute']
                   and end <= w['end_minute'] for w in room['availability']):
            error('ROOM_UNAVAILABLE', key)
        if not need_lab and room['kind'] == 'computer_lab':
            lab_minutes += s['duration_minutes']
        events.append({'event_id':f'{sid}:{week}', 'class_id':c['id'], 'target':True,
                       'week':week,'day':meeting['day'],'start':meeting['start_minute'],'end':end,
                       'rooms':[rid], 'instructors':c['instructor_ids'], 'groups':c['student_group_ids']})
    for e in data['external_classes']:
        for week in e['active_weeks']:
            for number, m in enumerate(e['meetings']):
                events.append({'event_id':f"EXT:{e['id']}:{number}:{week}", 'class_id':e['id'],'target':False,
                               'week':week,'day':m['day'],'start':m['start_minute'],'end':m['start_minute']+m['duration_minutes'],
                               'rooms':e['room_ids'],'instructors':e['instructor_ids'],
                               'groups':e['student_group_ids'] if data['constraints']['external_student_overlap_is_hard'] else []})
    by_class_constraints = defaultdict(list)
    for group_index, g in enumerate(data['constraints']['non_overlap_groups']):
        for cid in g['class_ids']:
            # Source ID 90 is reused for 80 different SAME_STUDENTS groups.
            # Each list entry is a distinct constraint; never merge by source ID.
            by_class_constraints[cid].append(f"{group_index}:{g['source_constraint_id']}")
    buckets = defaultdict(list)
    for event in events:
        resources = [('ROOM', r) for r in event['rooms']]
        resources += [('INSTRUCTOR', t) for t in event['instructors']]
        resources += [('STUDENT_GROUP', g) for g in event['groups']]
        resources += [('DISTRIBUTION', k) for k in by_class_constraints[event['class_id']]]
        for kind, resource in resources:
            buckets[(kind, resource, event['week'], event['day'])].append(event)
    for (kind, resource, week, day), items in buckets.items():
        active = []
        for event in sorted(items, key=lambda e:(e['start'],e['end'],e['event_id'])):
            active = [other for other in active if other['end'] > event['start']]
            for other in active:
                if event['class_id'] == other['class_id'] and kind == 'DISTRIBUTION':
                    continue
                if (event['target'] or other['target']) and event['event_id'] != other['event_id']:
                    pair = sorted((event['event_id'],other['event_id']))
                    error(kind + '_OVERLAP', {'resource':resource,'week':week,'day':day,'events':pair})
            active.append(event)
    external = {e['id']:e for e in data['external_classes']}
    for group in data['constraints']['same_time_of_day_groups']:
        for a, b in combinations(group['class_ids'], 2):
            if a not in classes and b not in classes:
                continue
            def interval(cid):
                if cid in selected:
                    return selected[cid]['meetings'][0]
                if cid in external:
                    return external[cid]['meetings'][0]
                return None
            ma, mb = interval(a), interval(b)
            if ma is None or mb is None:
                continue
            short, long = sorted((ma, mb), key=lambda m:m['duration_minutes'])
            if not (long['start_minute'] <= short['start_minute'] and
                    short['start_minute']+short['duration_minutes'] <= long['start_minute']+long['duration_minutes']):
                error('SAME_TIME', {'constraint':group['source_constraint_id'],'classes':[a,b]})
    changes = 0
    for sid, session in sessions.items():
        previous = None
        for week in sorted(session['active_weeks']):
            room = assigned.get((sid, week))
            if room is None:
                continue
            changes += int(previous is not None and room != previous)
            previous = room
    total = sum(len(s['active_weeks']) for s in sessions.values())
    metrics = {'unassigned_weekly_sessions':total-len(assigned),
               'assigned_weekly_sessions':len(assigned), 'total_weekly_sessions':total,
               'unnecessary_lab_minutes':lab_minutes,'unnecessary_lab_hours':lab_minutes/60,
               'room_changes':changes,'hard_violations':len(seen_errors)}
    return {'valid':not seen_errors,'violation_count':len(seen_errors),'violations':violations,
            'violations_truncated':len(seen_errors)>len(violations),'metrics':metrics}

"""Shared, deterministic decoder and budget accounting for Timetable Lab.

The searched genome is a class priority permutation plus preferred class time
options. Every algorithm uses this same decoder; final solutions are audited
independently in solution_validator.py. Standard library only.
"""
import random
import time
from collections import defaultdict
from dataclasses import dataclass

VERSION = '1.0.0'
SLOTS_PER_WEEK = 7 * 288


def time_mask(meeting, week):
    start = (week - 1) * SLOTS_PER_WEEK + meeting['day'] * 288 + meeting['start_minute'] // 5
    return ((1 << (meeting['duration_minutes'] // 5)) - 1) << start


def contained_time(a, b):
    short, long = sorted((a, b), key=lambda m: m['duration_minutes'])
    return (long['start_minute'] <= short['start_minute'] and
            short['start_minute'] + short['duration_minutes'] <= long['start_minute'] + long['duration_minutes'])


def available(meeting, room):
    end = meeting['start_minute'] + meeting['duration_minutes']
    return any(w['day'] == meeting['day'] and w['start_minute'] <= meeting['start_minute']
               and end <= w['end_minute'] for w in room['availability'])


class SearchStopped(Exception):
    pass


@dataclass
class Candidate:
    genome: dict
    solution: dict
    objectives: tuple
    energy: int


class Problem:
    def __init__(self, data):
        self.data = data
        self.classes = {c['id']: c for c in data['classes']}
        self.class_ids = tuple(self.classes)
        self.sessions = {s['id']: s for s in data['recurring_sessions']}
        self.rooms = {r['id']: r for r in data['rooms']}
        self.external = {e['id']: e for e in data['external_classes']}
        self.conflicts = {cid: set() for cid in self.class_ids}
        self.same_times = {cid: set() for cid in self.class_ids}
        self.fixed_people = {cid: 0 for cid in self.class_ids}
        self.fixed_rooms = defaultdict(int)
        self.options = {}
        self.total_weekly = sum(len(s['active_weeks']) for s in self.sessions.values())
        self.max_lab_minutes = sum(s['duration_minutes'] * len(s['active_weeks']) for s in self.sessions.values())
        self.max_changes = sum(max(0, len(s['active_weeks']) - 1) for s in self.sessions.values())
        self.minute_weight = self.max_changes + 1
        self.unassigned_weight = (self.max_lab_minutes + 1) * self.minute_weight
        self._prepare()
        self.base_order = tuple(sorted(self.class_ids, key=lambda cid: (
            sum(o['static_possible'] for o in self.options[cid]),
            len(self.options[cid]), -len(self.conflicts[cid]), cid)))

    def _prepare(self):
        target_teachers, target_groups = defaultdict(set), defaultdict(set)
        for cid, c in self.classes.items():
            for tid in c['instructor_ids']:
                target_teachers[tid].add(cid)
            for gid in c['student_group_ids']:
                target_groups[gid].add(cid)
        for table in (target_teachers, target_groups):
            for ids in table.values():
                for cid in ids:
                    self.conflicts[cid].update(ids - {cid})
        ext_masks = {}
        for eid, e in self.external.items():
            mask = 0
            for week in e['active_weeks']:
                for m in e['meetings']:
                    mask |= time_mask(m, week)
            ext_masks[eid] = mask
            for rid in e['room_ids']:
                self.fixed_rooms[rid] |= mask
            related = set()
            for tid in e['instructor_ids']:
                related.update(target_teachers[tid])
            if self.data['constraints']['external_student_overlap_is_hard']:
                for gid in e['student_group_ids']:
                    related.update(target_groups[gid])
            for cid in related:
                self.fixed_people[cid] |= mask
        for g in self.data['constraints']['non_overlap_groups']:
            ids = set(g['class_ids'])
            ts = ids & set(self.classes)
            for cid in ts:
                self.conflicts[cid].update(ts - {cid})
                for eid in ids & set(self.external):
                    self.fixed_people[cid] |= ext_masks[eid]
        fixed_same = defaultdict(list)
        for g in self.data['constraints']['same_time_of_day_groups']:
            ids = set(g['class_ids'])
            ts = ids & set(self.classes)
            for cid in ts:
                self.same_times[cid].update(ts - {cid})
                fixed_same[cid].extend(self.external[eid]['meetings'][0] for eid in ids & set(self.external))
        for cid, c in self.classes.items():
            compiled = []
            for option in c['time_options']:
                first = option['meetings'][0]
                relation_ok = all(contained_time(first, other) for other in fixed_same[cid])
                placements = []
                for m in option['meetings']:
                    s = self.sessions[m['session_id']]
                    for week in sorted(s['active_weeks']):
                        mask = time_mask(m, week)
                        need_lab = week in s['lab_weeks']
                        room_ids = c['lab_room_ids'] if need_lab else c['lecture_room_ids'] + c['lab_room_ids']
                        allowed = tuple(rid for rid in room_ids if available(m, self.rooms[rid])
                                        and not (self.fixed_rooms[rid] & mask))
                        people_ok = relation_ok and not (self.fixed_people[cid] & mask)
                        placements.append((s['id'], week, mask, allowed if people_ok else (),
                                           s['duration_minutes'], need_lab))
                compiled.append({'id': option['id'], 'first': first, 'relation_ok': relation_ok,
                                 'placements': tuple(placements),
                                 'static_possible': sum(bool(x[3]) for x in placements)})
            self.options[cid] = tuple(compiled)

    def initial_genome(self):
        return {'order': self.base_order, 'time_preferences': {cid: 0 for cid in self.class_ids}}

    def random_genome(self, rng):
        order = list(self.class_ids)
        rng.shuffle(order)
        return {'order': tuple(order), 'time_preferences': {
            cid: rng.randrange(len(self.options[cid])) for cid in self.class_ids}}

    def mutate(self, genome, rng, rate=1.0):
        order = list(genome['order'])
        preferences = dict(genome['time_preferences'])
        if len(order) > 1 and rng.random() < rate:
            a, b = rng.sample(range(len(order)), 2)
            order[a], order[b] = order[b], order[a]
        if order and rng.random() < rate:
            cid = rng.choice(order)
            preferences[cid] = rng.randrange(len(self.options[cid]))
        return {'order': tuple(order), 'time_preferences': preferences}

    def decode(self, genome, deadline=None):
        order = tuple(genome['order'])
        if len(order) != len(self.class_ids) or set(order) != set(self.class_ids):
            raise ValueError('Genome order must be a permutation of all target class IDs')
        preferences = genome['time_preferences']
        if set(preferences) != set(self.class_ids):
            raise ValueError('time_preferences must contain every target class')
        for cid, value in preferences.items():
            if not isinstance(value, int) or not 0 <= value < len(self.options[cid]):
                raise ValueError('Invalid time preference for ' + cid)
        room_busy = defaultdict(int)
        class_busy = defaultdict(int)
        selected = {}
        assignments = []
        assigned, lab_minutes, changes = 0, 0, 0
        for cid in order:
            if deadline is not None and time.perf_counter() >= deadline:
                raise SearchStopped('time_limit')
            people_busy = 0
            for other in self.conflicts[cid]:
                people_busy |= class_busy[other]
            best_local = None
            options = self.options[cid]
            start = preferences[cid]
            for offset in range(len(options)):
                option = options[(start + offset) % len(options)]
                if not option['relation_ok']:
                    continue
                if any(other in selected and selected[other] is not None and
                       not contained_time(option['first'], selected[other]['first']) for other in self.same_times[cid]):
                    continue
                records = []
                used_mask = 0
                local_lab = 0
                local_changes = 0
                previous = {}
                for sid, week, mask, allowed, duration, need_lab in option['placements']:
                    if people_busy & mask:
                        continue
                    choices = [rid for rid in allowed if not (room_busy[rid] & mask)]
                    if not choices:
                        continue
                    rid = min(choices, key=lambda r: (
                        int(not need_lab and self.rooms[r]['kind'] == 'computer_lab'),
                        int(sid in previous and previous[sid] != r),
                        self.rooms[r]['capacity'], r))
                    local_lab += duration * int(not need_lab and self.rooms[rid]['kind'] == 'computer_lab')
                    local_changes += int(sid in previous and previous[sid] != rid)
                    previous[sid] = rid
                    records.append((sid, week, rid, mask))
                    used_mask |= mask
                key = (-len(records), local_lab, local_changes)
                if best_local is None or key < best_local[0]:
                    best_local = (key, option, records, used_mask)
            if best_local is None or not best_local[2]:
                selected[cid] = None
                continue
            key, option, records, used_mask = best_local
            selected[cid] = option
            class_busy[cid] = used_mask
            for sid, week, rid, mask in records:
                room_busy[rid] |= mask
                assignments.append({'session_id': sid, 'week': week, 'room_id': rid})
            assigned += len(records)
            lab_minutes += key[1]
            changes += key[2]
        objectives = (self.total_weekly - assigned, lab_minutes, changes)
        energy = objectives[0] * self.unassigned_weight + objectives[1] * self.minute_weight + objectives[2]
        solution = {'dataset_id': self.data['dataset_id'],
                    'class_time_options': {cid: selected[cid]['id'] if selected.get(cid) else None for cid in self.class_ids},
                    'weekly_room_assignments': assignments}
        saved_genome = {'order': tuple(order), 'time_preferences': dict(preferences)}
        return Candidate(saved_genome, solution, objectives, energy)


class SearchContext:
    def __init__(self, problem, seed, budget, seconds, emit=None):
        self.problem = problem
        self.seed = seed
        self.rng = random.Random(seed)
        self.budget = int(budget)
        self.started = time.perf_counter()
        self.deadline = self.started + float(seconds)
        self.emit = emit
        self.evaluations = 0
        self.attempted_evaluations = 0
        self.best = None
        self.trace = []
        self.stop_reason = None
        self.last_progress = 0
        self.initial = None

    def check(self):
        if self.evaluations >= self.budget:
            raise SearchStopped('evaluation_budget')
        if time.perf_counter() >= self.deadline:
            raise SearchStopped('time_limit')

    def evaluate(self, genome):
        self.check()
        self.attempted_evaluations += 1
        candidate = self.problem.decode(genome, self.deadline if self.best is not None else None)
        self.evaluations += 1
        improved = self.best is None or candidate.objectives < self.best.objectives
        if improved:
            self.best = candidate
        elapsed = time.perf_counter() - self.started
        if improved or self.evaluations % 5 == 0 or self.evaluations == self.budget:
            point = {'evaluations': self.evaluations, 'seconds': elapsed,
                     'objectives': list(self.best.objectives), 'current_objectives': list(candidate.objectives)}
            self.trace.append(point)
            if self.emit and (improved or elapsed - self.last_progress >= 0.25):
                self.last_progress = elapsed
                self.emit({'type': 'progress', **point, 'budget': self.budget})
        return candidate

"""Reproducible single-run API shared by the browser worker and native CLI."""
import hashlib
import inspect
import json
import platform
import sys
import time
import traceback
from pathlib import Path

import algorithms
from lab_core import VERSION, Problem, SearchContext, SearchStopped, Candidate
from solution_validator import audit_solution
from input_validation import validate as validate_input


def prepare(dataset_text):
    data = json.loads(dataset_text)
    if len(data.get('classes', [])) > 2000 or len(data.get('recurring_sessions', [])) > 6000:
        raise ValueError('Dataset exceeds the browser workbench size limit')
    report = validate_input(data)
    if report['errors']:
        raise ValueError('Invalid dataset: ' + '; '.join(report['errors'][:8]))
    started = time.perf_counter()
    problem = Problem(data)
    return problem, {'summary':report['summary'],'warnings':report['warnings'],
                     'dataset_sha256':hashlib.sha256(dataset_text.encode()).hexdigest(),
                     'preprocessing_seconds':time.perf_counter()-started,
                     'energy_weights':{'unassigned':problem.unassigned_weight,'lab_minute':problem.minute_weight,'room_change':1}}


def check_configuration(config):
    budget, seconds = config.get('budget',100), config.get('seconds',60)
    if type(budget) is not int or not 1 <= budget <= 100000:
        raise ValueError('Evaluation budget must be an integer from 1 to 100000')
    if not isinstance(seconds,(int,float)) or not 1 <= seconds <= 3600:
        raise ValueError('Time limit must be 1..3600 seconds per run')
    params = config.get('parameters',{})
    hc, sa, ga = params.get('hc',{}), params.get('sa',{}), params.get('ga',{})
    if not 1 <= int(hc.get('restart_patience',20)) <= 10000:
        raise ValueError('HC restart patience must be 1..10000')
    if not 0 < float(sa.get('initial_acceptance',.8)) < 1 or not 0 < float(sa.get('cooling_rate',.97)) < 1:
        raise ValueError('SA acceptance and cooling rate must be strictly between 0 and 1')
    pop = int(ga.get('population_size',12))
    if not 4 <= pop <= 100 or not 1 <= int(ga.get('elites',1)) < pop:
        raise ValueError('GA requires population 4..100 and 1 <= elites < population')
    if not 2 <= int(ga.get('tournament_size',3)) <= pop:
        raise ValueError('GA tournament size must be 2..population size')
    for field, default in [('mutation_rate',.3),('crossover_rate',.9)]:
        if not 0 <= float(ga.get(field,default)) <= 1:
            raise ValueError('GA probabilities must be in [0,1]')


def run_one(problem, config, method, seed, dataset_meta=None, custom_source='', progress=None):
    check_configuration(config)
    if method not in algorithms.METHODS and method != 'custom':
        raise ValueError('Unknown algorithm: ' + method)
    if type(seed) is not int or not 0 <= seed <= 2**32-1:
        raise ValueError('Seed must be an integer in [0, 2^32-1]')
    algorithm_source = custom_source if method=='custom' else Path(algorithms.__file__).read_text()
    code_hash = hashlib.sha256(algorithm_source.encode()).hexdigest()
    # Snapshot before an editable plugin sees the model; its result is audited against this copy.
    protected_data = json.loads(json.dumps(problem.data)) if method=='custom' else problem.data
    context = SearchContext(problem, seed, config.get('budget',100), config.get('seconds',60), progress)
    status, returned, failure = 'completed', None, None
    started = time.perf_counter()
    try:
        context.initial = context.evaluate(problem.initial_genome())
        if method=='custom':
            if not custom_source.strip():
                raise ValueError('Custom Python source is empty')
            namespace = {'__name__':'custom_algorithm'}
            exec(compile(custom_source,'custom_algorithm.py','exec'),namespace)
            solve = namespace.get('solve')
            if not callable(solve):
                raise ValueError('Custom code must define solve(problem, context, parameters)')
            returned = solve(problem, context, config.get('parameters',{}).get('custom',{}))
        else:
            returned = algorithms.METHODS[method](problem,context,config.get('parameters',{}).get(method,{}))
    except SearchStopped as stop:
        status = str(stop)
    except Exception as exc:
        status = 'error'
        failure = {'message':str(exc),'traceback':traceback.format_exc(limit=8)}
    search_seconds = time.perf_counter()-started
    if method=='custom' and returned is not None:
        solution = returned.solution if isinstance(returned,Candidate) else returned
    else:
        solution = context.best.solution if context.best is not None else None
    validation_start = time.perf_counter()
    checked = audit_solution(protected_data,solution)
    validation_seconds = time.perf_counter()-validation_start
    if status!='error' and not checked['valid']:
        status = 'invalid_solution'
    if checked['valid'] and context.best and method!='custom':
        actual = checked['metrics']
        independent = (actual['unassigned_weekly_sessions'],actual['unnecessary_lab_minutes'],actual['room_changes'])
        if independent != context.best.objectives:
            status = 'error'
            failure = {'message':'Search score disagrees with independent solution validator'}
    return {
        'algorithm':method,'seed':seed,'status':status,'valid':checked['valid'] and status!='error',
        'metrics':checked['metrics'],'validation':checked,'solution':solution,
        'evaluations':context.evaluations,'attempted_evaluations':context.attempted_evaluations,
        'budget':context.budget,'time_limit_seconds':config.get('seconds',60),
        'search_seconds':search_seconds,'validation_seconds':validation_seconds,
        'trace':context.trace,'error':failure,'parameters':config.get('parameters',{}).get(method,{}),
        'dataset_id':protected_data['dataset_id'],'dataset_sha256':(dataset_meta or {}).get('dataset_sha256'),
        'original_source_sha256':protected_data.get('source',{}).get('sha256'),
        'code_sha256':code_hash,'engine_version':VERSION,
        'runtime':{'python':sys.version,'platform':platform.system()},
        'energy_weights':{'unassigned':problem.unassigned_weight,'lab_minute':problem.minute_weight,'room_change':1},
    }


def run_one_json(problem, config_json, method, seed, meta_json='{}', custom_source='', on_progress=None):
    progress = (lambda event:on_progress(json.dumps(event))) if on_progress else None
    return json.dumps(run_one(problem,json.loads(config_json),method,int(seed),json.loads(meta_json),custom_source,progress))

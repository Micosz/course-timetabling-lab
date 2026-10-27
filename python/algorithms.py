"""Four methods on the same priority/time-preference genome and shared decoder."""
import math
import statistics


def greedy(problem, context, parameters):
    return context.initial


def hill_climbing(problem, context, parameters):
    current = context.initial
    patience = int(parameters.get('restart_patience', 20))
    idle = 0
    while True:
        context.check()
        if idle >= patience:
            current = context.evaluate(problem.random_genome(context.rng))
            idle = 0
        else:
            proposal = context.evaluate(problem.mutate(current.genome, context.rng))
            if proposal.objectives < current.objectives:
                current, idle = proposal, 0
            else:
                idle += 1


def simulated_annealing(problem, context, parameters):
    current = context.initial
    acceptance = float(parameters.get('initial_acceptance', 0.8))
    cooling = float(parameters.get('cooling_rate', 0.97))
    # Calibration evaluations are charged to the same budget and eligible as best-so-far.
    uphill = []
    for _ in range(min(8, max(0, context.budget - context.evaluations - 1))):
        candidate = context.evaluate(problem.mutate(current.genome, context.rng))
        if candidate.energy > current.energy:
            uphill.append(candidate.energy - current.energy)
    typical = statistics.median(uphill) if uphill else problem.minute_weight * 60
    temperature = max(1.0, -typical / math.log(acceptance))
    while True:
        proposal = context.evaluate(problem.mutate(current.genome, context.rng))
        delta = proposal.energy - current.energy
        if delta <= 0 or context.rng.random() < math.exp(-min(745.0, delta / max(temperature, 1e-12))):
            current = proposal
        temperature *= cooling


def ordered_crossover(a, b, rng):
    n = len(a)
    if n < 2:
        return tuple(a)
    left, right = sorted(rng.sample(range(n), 2))
    right += 1
    child = [None] * n
    child[left:right] = a[left:right]
    used = set(a[left:right])
    rest = [x for x in b[right:] + b[:right] if x not in used]
    positions = list(range(right, n)) + list(range(0, left))
    for i, value in zip(positions, rest):
        child[i] = value
    return tuple(child)


def genetic_algorithm(problem, context, parameters):
    size = int(parameters.get('population_size', 12))
    tournament_size = int(parameters.get('tournament_size', 3))
    mutation_rate = float(parameters.get('mutation_rate', 0.3))
    crossover_rate = float(parameters.get('crossover_rate', 0.9))
    elites = int(parameters.get('elites', 1))
    population = [context.initial]
    while len(population) < size:
        population.append(context.evaluate(problem.random_genome(context.rng)))

    def parent():
        return min((context.rng.choice(population) for _ in range(tournament_size)), key=lambda c: c.objectives)

    while True:
        context.check()
        following = sorted(population, key=lambda c: c.objectives)[:elites]
        while len(following) < size:
            p1, p2 = parent(), parent()
            if context.rng.random() < crossover_rate:
                order = ordered_crossover(p1.genome['order'], p2.genome['order'], context.rng)
                preferences = {cid: (p1 if context.rng.random() < 0.5 else p2).genome['time_preferences'][cid]
                               for cid in problem.class_ids}
                genome = {'order': order, 'time_preferences': preferences}
            else:
                genome = p1.genome
            if context.rng.random() < mutation_rate:
                genome = problem.mutate(genome, context.rng)
            following.append(context.evaluate(genome))
        population = following


METHODS = {'greedy': greedy, 'hc': hill_climbing, 'sa': simulated_annealing, 'ga': genetic_algorithm}

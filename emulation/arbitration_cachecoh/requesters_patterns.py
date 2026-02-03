# patterns.py
import random

def best_case(num_requesters):
    """Exactly one requester active at a time, randomly chosen."""
    requests = [0] * num_requesters
    active_index = random.randint(0, num_requesters - 1)
    requests[active_index] = 1
    return requests

def worst_case(num_requesters):
    """All requesters active every cycle."""
    return [1] * num_requesters

def average_case(num_requesters):
    """Each requester randomly 0 or 1."""
    return [random.randint(0, 1) for _ in range(num_requesters)]

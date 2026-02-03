# main.py
from weighted_round_robin import WeightedRoundRobinArbiter
from patterns import best_case, worst_case, average_case

def run_pattern(name, pattern_fn, arbiter, num_requesters, cycles):
    print(f"=== {name.upper()} CASE ===")
    for cycle in range(cycles):
        requests = pattern_fn(num_requesters)
        grant = arbiter.arbitrate(requests)

        print(
            f"cycle {cycle:02d} | "
            f"requests = {requests} | "
            f"grant = {grant}"
        )
    print("")

def main():
    num_requesters = 2
    cycles = 15

    weights = [1, 5]
    arbiter = WeightedRoundRobinArbiter(num_requesters, weights)

    run_pattern(
        "best",
        best_case,
        arbiter,
        num_requesters,
        cycles
    )

    run_pattern(
        "worst",
        worst_case,
        arbiter,
        num_requesters,
        cycles
    )

    run_pattern(
        "average",
        average_case,
        arbiter,
        num_requesters,
        cycles
    )

if __name__ == "__main__":
    main()

"""Orchestrator loop (Design Document, Chapter 9).

The orchestrator calls every other component, so every message passes one place
where it is checked and logged (Chapter 4). Nothing moves before the checker says
run. Table 10 lists what it does in each case for the open loop and the closed
loop.

The loop itself is not built yet. Two of its rules already work. The step budget
is twice the number of steps of the expected plan, or max_steps from the
capability file for an order without an expected plan (DD14, DD21). After a
provider error or rate limit a run is repeated at most three times and then
marked not run, so free-tier limits do not count as planner failures (DD21).
"""

VARIANTS = ("open loop", "closed loop")

# Repeats after the first attempt, so at most four attempts in total (DD21).
PROVIDER_REPEATS = 3


class ProviderLimit(Exception):
    """A provider error or rate limit. It is logged as a provider limit, not as a model timeout (DD14)."""


def step_budget(capability, expected_plan=None):
    """Return the number of steps after which a run stops safely (DD14, DD21)."""
    if expected_plan:
        return 2 * len(expected_plan)
    return capability["limits"]["max_steps"]


def run_with_provider_repeats(run):
    """Call run(). After a ProviderLimit, repeat it at most PROVIDER_REPEATS times.

    Returns {"status": "done" or "not run", "result": ..., "attempts": n}. A run
    marked not run is done later, as in the model tests (Chapter 9).
    """
    for attempt in range(1, PROVIDER_REPEATS + 2):
        try:
            return {"status": "done", "result": run(), "attempts": attempt}
        except ProviderLimit:
            continue
    return {"status": "not run", "result": None, "attempts": PROVIDER_REPEATS + 1}


def run_order(order, variant):
    """Run one order from planning to the final tray and return the run log."""
    raise NotImplementedError("Orchestrator, see Design Document Chapter 9, Table 10")

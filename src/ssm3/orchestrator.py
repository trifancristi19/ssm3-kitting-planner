"""Orchestrator loop (Design Document, Chapter 9).

The orchestrator calls every other component, so every message passes one place
where it is checked and logged (Chapter 4). Nothing moves before the checker says
run. Table 10 lists what it does in each case for the open loop and the closed
loop.

The loop works with any planner: a function that takes the order text, the cell
state, the capability file and the history of this order, and returns the raw
answer of the model. planner.llm_planner gives the real one, and the tests use a
fake planner with fixed answers, so no test calls a language model.

The rules of the loop:
- A rejected plan, or an answer the parser cannot read (FORMAT), goes back to the
  planner with its reason. After three rejected plans in a row the operator is
  asked once. If the next plan is still rejected, the run stops safely (DD13).
- A question of the planner, or an ask of the checker, goes to the operator, and
  the planner is called again with the answer.
- A refusal stops the run and the operator is told.
- The open loop runs the whole checked plan and stops safely at a failed step
  (DD16). The closed loop runs the first step of every checked plan and then
  calls the planner again with the result and the new state (Table 8). It ends
  when the last step of a checked plan succeeds.
- The step budget is twice the number of steps of the expected plan, or max_steps
  from the capability file for an order without an expected plan (DD14, DD21).
- After a provider error or rate limit a run is repeated at most three times and
  then marked not run, so free-tier limits do not count as planner failures (DD21).

Choices the Design Document does not settle are marked "proposal" below.
"""

import time

from ssm3 import functions
from ssm3.checker import check
from ssm3.planner import ResponseFormatError, parse_response

VARIANTS = ("open loop", "closed loop")

# Repeats after the first attempt, so at most four attempts in total (DD21).
PROVIDER_REPEATS = 3

# Rejected plans in a row before the operator is asked once (DD13).
REJECTS_BEFORE_ASKING = 3


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
    marked not run is done later, as in the model tests (Chapter 9). run must start
    from a fresh cell and a fresh log every time it is called.
    """
    for attempt in range(1, PROVIDER_REPEATS + 2):
        try:
            return {"status": "done", "result": run(), "attempts": attempt}
        except ProviderLimit:
            continue
    return {"status": "not run", "result": None, "attempts": PROVIDER_REPEATS + 1}


class _Run:
    """The state of one run of run_order."""

    def __init__(self, order, variant, planner, cell, operator, log, protected, budget, failures):
        self.order = order
        self.variant = variant
        self.planner = planner
        self.cell = cell
        self.operator = operator
        self.log = log
        self.protected = tuple(protected)
        self.budget = budget
        self.failures = dict(failures or {})
        self.history = []
        self.steps_run = 0
        self.planner_calls = 0
        self.interventions = 0
        self.rejects_in_a_row = 0
        self.asked_after_rejects = False
        self.waiting_for_a_valid_plan = False

    def finish(self, outcome, reason):
        if outcome != "done":
            self.operator.tell(f"Order {self.order.get('order_id')} stopped: {reason}")
        summary = {
            "order_id": self.order.get("order_id"),
            "variant": self.variant,
            "outcome": outcome,
            "reason": reason,
            "steps_run": self.steps_run,
            "planner_calls": self.planner_calls,
            "interventions": self.interventions,
            "final_state": self.cell.state(),
        }
        self.log.event("run_end", **summary)
        return summary

    def ask_operator(self, question, kind, source):
        start = time.perf_counter()
        answer = functions.ask_operator(question, self.operator)
        self.interventions += 1
        self.log.event("intervention", kind=kind, source=source, question=question, answer=answer,
                       wait_seconds=round(time.perf_counter() - start, 3))
        self.history.append({"type": "answer", "question": question, "answer": answer})

    def call_planner(self):
        self.planner_calls += 1
        start = time.perf_counter()
        raw = self.planner(self.order["text"], self.cell.state(), self.cell.capability, list(self.history))
        self.log.event("planner_response", call=self.planner_calls, raw=raw,
                       seconds=round(time.perf_counter() - start, 3))
        return raw

    def reject(self, verdict):
        """Handle a rejected plan. Returns a finished summary when the run stops, else None (DD13)."""
        self.history.append({"type": "reject", "step": verdict["step"], "code": verdict["code"],
                             "reason": verdict["reason"]})
        self.rejects_in_a_row += 1
        if self.waiting_for_a_valid_plan:
            return self.finish("stopped", "the plan after the operator's answer was rejected too")
        if self.rejects_in_a_row >= REJECTS_BEFORE_ASKING:
            if self.asked_after_rejects:
                # The operator is asked only once per run (proposal).
                return self.finish("stopped", f"{self.rejects_in_a_row} plans in a row were rejected")
            self.asked_after_rejects = True
            self.waiting_for_a_valid_plan = True
            question = (f"The last {self.rejects_in_a_row} plans were rejected, the last one with "
                        f"{verdict['code']}: {verdict['reason']}. How should the planner continue?")
            self.ask_operator(question, kind="correction", source="checker")
        return None

    def run_steps(self, plan):
        """Run the checked plan (open loop) or its first step (closed loop). Returns a summary or None."""
        steps = plan if self.variant == "open loop" else plan[:1]
        for step in steps:
            if self.steps_run >= self.budget:
                return self.finish("stopped", f"the step budget of {self.budget} steps is used up")
            self.steps_run += 1
            if self.steps_run in self.failures:
                kind, details = self.failures[self.steps_run]
                self.cell.inject_failure(kind, **details)
                self.log.event("feedback", kind="injected failure", step=self.steps_run, failure=kind, details=details)
            name, args = step["function"], step["args"]
            result = getattr(functions, name)(self.cell, **args)
            self.log.event("step_result", step=self.steps_run, function=name, args=args, status=result.status,
                           message=result.message, state=result.state)
            self.history.append({"type": "step", "step": self.steps_run, "function": name, "args": args,
                                 "status": result.status, "message": result.message})
            # locate only reads the state, so "not found" is information, not a failed step (proposal).
            if result.status != "success" and name != "locate":
                if self.variant == "open loop":
                    return self.finish("stopped", f"step {self.steps_run} {name} returned {result.status}, "
                                                  "not recovered (DD16)")
                self.log.event("feedback", kind="failure sent to the planner", step=self.steps_run,
                               status=result.status, message=result.message)
                return None
        if self.variant == "open loop" or len(plan) == 1:
            return self.finish("done", "the last step of the plan is done")
        return None

    def loop(self):
        while True:
            # A planner that keeps asking or keeps failing must also end: the number of planner
            # calls is limited by the step budget too (proposal).
            if self.planner_calls >= self.budget:
                return self.finish("stopped", f"{self.planner_calls} planner calls without finishing the order")
            raw = self.call_planner()
            try:
                answer = parse_response(raw)
            except ResponseFormatError as error:
                verdict = {"verdict": "reject", "step": None, "code": "FORMAT", "reason": str(error)}
                self.log.event("check_result", **verdict)
                stopped = self.reject(verdict)
                if stopped:
                    return stopped
                continue
            if answer["kind"] == "ask":
                self.ask_operator(answer["value"], kind="clarification", source="planner")
                continue
            if answer["kind"] == "refuse":
                return self.finish("refused", answer["value"])
            plan = answer["value"]
            verdict = check(plan, self.cell.state(), self.cell.capability, self.protected)
            self.log.event("check_result", **verdict)
            if verdict["verdict"] == "reject":
                stopped = self.reject(verdict)
                if stopped:
                    return stopped
                continue
            if verdict["verdict"] == "ask":
                self.ask_operator(verdict["reason"], kind="clarification", source="checker")
                continue
            self.rejects_in_a_row = 0
            self.waiting_for_a_valid_plan = False
            if not plan:
                return self.finish("done", "the planner returned an empty plan, so nothing is left to do")
            finished = self.run_steps(plan)
            if finished:
                return finished


def run_order(order, variant, *, planner, cell, operator, log, protected=(), expected_plan=None, failures=None,
              info=None):
    """Run one order from planning to the final tray and return its summary.

    order is {"order_id": ..., "text": ...}. variant is "open loop" or "closed loop".
    planner returns the raw model answer (see the module docstring), cell is the
    simulated cell, operator a console operator and log a logger.RunLog. protected
    lists the slots the order keeps unchanged (from the task set). expected_plan
    sets the step budget. failures maps a step number to a failure that is injected
    just before that step runs, as (kind, details) for SimulatedCell.inject_failure
    (FR11). info is stored in the run_start record, for the model, its settings and
    the prompt version (Table 11).

    The summary holds the outcome ("done", "refused" or "stopped"), the reason, the
    number of steps, planner calls and interventions, and the final state.
    """
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}, expected one of {VARIANTS}")
    budget = step_budget(cell.capability, expected_plan)
    log.event("run_start", order_id=order.get("order_id"), instruction=order["text"], variant=variant,
              protected=list(protected), step_budget=budget, **(info or {}))
    run = _Run(order, variant, planner, cell, operator, log, protected, budget, failures)
    return run.loop()

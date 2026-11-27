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
  (DD16). The baseline, which plans without a language model (Chapter 11), runs
  its one checked plan in the same way. The closed loop runs the first step of every checked plan and then
  calls the planner again with the result and the new state (Table 8). It ends
  only when the planner answers with an empty plan, which the prompt asks for
  when the order is complete (proposal). So a planner that sends only the next
  step each time still finishes the whole order.
- The step budget is twice the number of steps of the expected plan, or max_steps
  from the capability file for an order without an expected plan (DD14, DD21).
- Failures can be injected before a given step (failures, FR11), or armed for the
  first step they fit (faults, proposal, for chat mode where the plan is not known
  in advance): a pick failure goes off before the next pick, a slip before the next
  move while the gripper holds a part.
- A provider error or rate limit is logged as a provider_limit event and ends the
  attempt (DD14). The run is then repeated at most three times and marked not run
  after that, so free-tier limits do not count as planner failures (DD21).
- A model call over its time limit (60 seconds, DD14) ends the run safely as
  stopped, with a run_end like every other run. It is not repeated, because DD14
  keeps a timeout apart from a provider limit.
- A failure that the cell cannot apply, such as a slip of a part that has no bin in
  the capability file, also ends the run as stopped before the step it was meant
  for (proposal), so the evaluator never gets a run without an outcome.

Choices the Design Document does not settle are marked "proposal" below.
"""

import time

from ssm3 import functions
from ssm3.checker import check

# ProviderLimit lives next to the model client that raises it. It is imported here, so run_with_provider_repeats
# catches exactly the class call_model raises (DD14), and callers can still import it from this module.
from ssm3.planner import ModelTimeout, ProviderLimit, ResponseFormatError, parse_response

__all__ = ["FAULTS", "PROVIDER_REPEATS", "REJECTS_BEFORE_ASKING", "VARIANTS", "ProviderLimit", "run_order",
           "run_with_provider_repeats", "step_budget"]

# The baseline (Chapter 11) plans without a language model and runs its one checked plan like the open loop.
VARIANTS = ("open loop", "closed loop", "baseline")

# The failures that can be armed for the first step they fit (proposal, chat mode).
FAULTS = ("pick_failure", "drop_part")

# Repeats after the first attempt, so at most four attempts in total (DD21).
PROVIDER_REPEATS = 3

# Rejected plans in a row before the operator is asked once (DD13).
REJECTS_BEFORE_ASKING = 3


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

    def __init__(self, order, variant, planner, cell, operator, log, protected, budget, failures, faults):
        self.order = order
        self.variant = variant
        self.planner = planner
        self.cell = cell
        self.operator = operator
        self.log = log
        self.protected = tuple(protected)
        self.budget = budget
        self.failures = dict(failures or {})
        self.faults = list(faults or ())
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
                       wait_seconds=round(time.perf_counter() - start, 6))
        self.history.append({"type": "answer", "question": question, "answer": answer})

    def call_planner(self):
        self.planner_calls += 1
        start = time.perf_counter()
        raw = self.planner(self.order["text"], self.cell.state(), self.cell.capability, list(self.history))
        self.log.event("planner_response", call=self.planner_calls, raw=str(raw) if isinstance(raw, str) else raw,
                       tokens=getattr(raw, "usage", None), seconds=round(time.perf_counter() - start, 6))
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
        steps = plan if self.variant != "closed loop" else plan[:1]
        for step in steps:
            if self.steps_run >= self.budget:
                return self.finish("stopped", f"the step budget of {self.budget} steps is used up")
            number = self.steps_run + 1
            # A scheduled failure goes off first, so an armed fault then sees the state after it.
            if number in self.failures:
                stopped = self.inject(*self.failures[number], before=number)
                if stopped:
                    return stopped
            armed = self.armed_fault(step)
            if armed:
                stopped = self.inject(*armed, before=number)
                if stopped:
                    return stopped
            self.steps_run = number
            name, args = step["function"], step["args"]
            result = getattr(functions, name)(self.cell, **args)
            self.log.event("step_result", step=self.steps_run, function=name, args=args, status=result.status,
                           message=result.message, state=result.state)
            self.history.append({"type": "step", "step": self.steps_run, "function": name, "args": args,
                                 "status": result.status, "message": result.message})
            # locate only reads the state, so "not found" is information, not a failed step (proposal).
            if result.status != "success" and name != "locate":
                if self.variant != "closed loop":
                    return self.finish("stopped", f"step {self.steps_run} {name} returned {result.status}, "
                                                  "not recovered (DD16)")
                self.log.event("feedback", kind="failure sent to the planner", step=self.steps_run,
                               status=result.status, message=result.message)
                return None
        if self.variant != "closed loop":
            return self.finish("done", "the last step of the plan is done")
        # The closed loop always asks the planner again, and ends only on an empty plan (proposal, OD14).
        return None

    def inject(self, kind, details, before):
        """Apply a failure just before step `before`. Returns a stopped summary if the cell cannot apply it."""
        try:
            self.cell.inject_failure(kind, **details)
        except ValueError as error:
            return self.finish("stopped", f"the {kind} failure before step {before} could not be applied: {error}")
        # The state after the change goes into the log, so the replay shows it whatever the kind.
        self.log.event("feedback", kind="injected failure", step=before, failure=kind, details=details,
                       state=self.cell.state())
        return None

    def armed_fault(self, step):
        """The first armed fault that fits this step, as (kind, details), and it is used up. Else None."""
        held = self.cell.state()["gripper"]
        for kind in self.faults:
            if kind == "pick_failure" and step["function"] == "pick":
                self.faults.remove(kind)
                return kind, {}
            if kind == "drop_part" and step["function"] == "move_to" and held is not None:
                self.faults.remove(kind)
                return kind, {"part": held, "destination": self.cell.capability["parts"].get(held)}
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
                return self.finish("done", "the planner returned an empty plan, so the order is complete")
            finished = self.run_steps(plan)
            if finished:
                return finished


def run_order(order, variant, *, planner, cell, operator, log, protected=(), expected_plan=None, failures=None,
              faults=(), info=None):
    """Run one order from planning to the final tray and return its summary.

    order is {"order_id": ..., "text": ...}. variant is "open loop", "closed loop" or "baseline".
    planner returns the raw model answer (see the module docstring), cell is the
    simulated cell, operator a console operator and log a logger.RunLog. protected
    lists the slots the order keeps unchanged (from the task set). expected_plan
    sets the step budget. failures maps a step number to a failure that is injected
    just before that step runs, as (kind, details) for SimulatedCell.inject_failure
    (FR11). faults lists failures from FAULTS that go off at the first step they fit,
    each once (proposal, chat mode). info is stored in the run_start record, for the model, its settings and
    the prompt version (Table 11).

    The summary holds the outcome ("done", "refused" or "stopped"), the reason, the
    number of steps, planner calls and interventions, and the final state. A
    ProviderLimit from the planner is logged as a provider_limit event and raised
    again, so run_with_provider_repeats can repeat the run (DD14, DD21). A
    ModelTimeout ends the run as stopped, with a run_end, and is not repeated (DD14).
    """
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}, expected one of {VARIANTS}")
    unknown = [kind for kind in faults if kind not in FAULTS]
    if unknown:
        raise ValueError(f"unknown faults {unknown!r}, expected some of {FAULTS}")
    budget = step_budget(cell.capability, expected_plan)
    log.event("run_start", order_id=order.get("order_id"), instruction=order["text"], variant=variant,
              protected=list(protected), step_budget=budget, **({"faults": list(faults)} if faults else {}),
              **(info or {}))
    run = _Run(order, variant, planner, cell, operator, log, protected, budget, failures, faults)
    try:
        return run.loop()
    except ProviderLimit as error:
        log.event("provider_limit", reason=str(error), planner_calls=run.planner_calls, steps_run=run.steps_run)
        raise
    except ModelTimeout as error:
        return run.finish("stopped", f"model call {run.planner_calls} timed out: {error} (DD14)")

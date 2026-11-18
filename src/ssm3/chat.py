"""Chat mode for the demo: type an order, watch the real loop carry it out (Design Document, Chapters 9 and 13).

The Design Document does not describe a chat mode, so all of it is a proposal.

The operator types a kit order in plain words. The order goes through the same
code as every other run: the planner (the real model on Groq, or a local model
through Ollama with --local), the checker, the
orchestrator loop, the simulated cell and the run log. The cell keeps its state
from one order to the next, so a second order starts where the first one ended.
A question of the planner or the checker comes back to the chat, and the answer
the operator types goes back to the loop.

This module holds the session. chat_server.py puts a local web page in front of
it. Every order with the model on Groq uses the Groq free-tier limit. The tests give
the session a fake planner, so no test calls a model.
"""

import queue
import threading
from datetime import datetime

from ssm3 import planner as planner_module
from ssm3.cell import SimulatedCell
from ssm3.console import NO_FURTHER_INFORMATION
from ssm3.demo import ROOT, chapter_13_state, demo_capability, paced
from ssm3.logger import RunLog
from ssm3.orchestrator import run_order

VARIANTS = {"open": "open loop", "closed": "closed loop"}

# How long the loop waits for the operator to answer a question in the chat (proposal).
ANSWER_SECONDS = 300


class ChatLog(RunLog):
    """A run log that also hands every record to the chat session the moment it is written."""

    def __init__(self, run_id, folder, session):
        super().__init__(run_id, folder=folder)
        self._session = session

    def event(self, kind, /, **fields):
        record = super().event(kind, **fields)
        self._session.add(dict(record))
        return record


class ChatOperator:
    """The operator in the chat: questions go to the page, answers come back from it."""

    def __init__(self, session):
        self._session = session

    def ask(self, question):
        self._session.add({"event": "operator_question", "question": question})
        try:
            return self._session.answers.get(timeout=self._session.answer_seconds)
        except queue.Empty:
            return NO_FURTHER_INFORMATION

    def tell(self, message):
        self._session.add({"event": "notice", "text": message})


class ChatSession:
    """One simulated cell and the orders typed for it.

    planner is the function the orchestrator calls. By default it is the real model
    (planner.llm_planner), spaced by delay seconds between calls as in the demo.
    """

    def __init__(self, planner=None, settings=None, delay=2.5, log_dir=None, sleep=None,
                 answer_seconds=ANSWER_SECONDS):
        self.capability = demo_capability()
        self.cell = SimulatedCell(self.capability, chapter_13_state(self.capability))
        self.settings = {**planner_module.DEFAULT_SETTINGS, **(settings or {})}
        self.uses_model = planner is None
        self._planner = planner
        self.delay = delay
        self.log_dir = ROOT / "demo_logs" if log_dir is None else log_dir
        self._sleep = sleep
        self.answer_seconds = answer_seconds
        self.answers = queue.Queue()
        self.orders = 0
        self.busy = False
        self._events = []
        self._lock = threading.Lock()
        self._thread = None

    @property
    def model(self):
        return self.settings["model"]

    @property
    def provider(self):
        return planner_module.provider_name(self.settings)

    @property
    def local(self):
        return not self.settings["needs_key"]

    def add(self, event):
        with self._lock:
            event["n"] = len(self._events)
            self._events.append(event)

    def events_since(self, n=0):
        with self._lock:
            return [dict(event) for event in self._events[n:]]

    def state(self):
        return self.cell.state()

    def reset(self):
        """Put the cell back in the Chapter 13 start state. Not while an order runs."""
        if self.busy:
            return False
        self.cell = SimulatedCell(self.capability, chapter_13_state(self.capability))
        self.add({"event": "reset", "state": self.cell.state()})
        return True

    def answer(self, text):
        self.add({"event": "operator_answer", "text": text})
        self.answers.put(text)

    def _make_planner(self):
        if self._planner is not None:
            return self._planner
        import time

        sleep = self._sleep or time.sleep
        return paced(planner_module.llm_planner(self.settings), self.delay,
                     lambda text: self.add({"event": "notice", "text": text.strip()}), sleep)

    def slots(self):
        return list(self.capability["positions"]["slots"])

    def known_slots(self, protected):
        """True when protected is a list of tray slots of this cell."""
        return isinstance(protected, list | tuple) and all(slot in self.slots() for slot in protected)

    def run(self, text, variant="open", protected=()):
        """Run one typed order to the end and return its summary, or None when it could not run.

        protected lists the tray slots the operator ticked as "keep unchanged". The checker
        enforces them (PROTECTED_SLOT, Table 9), whatever the order text says, the same
        way the task set protects slots in the experiment.
        """
        if not self.known_slots(protected):
            raise ValueError(f"protected must list tray slots of the cell, got {protected!r}")
        protected = [slot for slot in self.slots() if slot in protected]
        self.orders += 1
        order = {"order_id": f"C-{self.orders}", "text": text}
        self.add({"event": "user", "order_id": order["order_id"], "text": text, "variant": VARIANTS[variant],
                  "protected": protected})
        if self.uses_model:
            try:
                planner_module.check_access(self.settings)
            except planner_module.ModelAccessError as error:
                self.add({"event": "error", "reason": str(error)})
                return None
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        log = ChatLog(f"chat-{order['order_id']}-{stamp}", self.log_dir, self)
        info = {"planner": "llm" if self.uses_model else "test planner", "initial_state": self.cell.state()}
        if self.uses_model:
            info.update(model=self.model, provider=self.settings["provider"],
                        prompt_version=planner_module.PROMPT_VERSION)
        try:
            return run_order(order, VARIANTS[variant], planner=self._make_planner(), cell=self.cell,
                             operator=ChatOperator(self), log=log, protected=protected, info=info)
        except planner_module.ModelError as error:
            self.add({"event": "error", "reason": f"{type(error).__name__}: {error}"})
            return None

    def submit(self, text, variant="open", protected=()):
        """Start an order in the background.

        Returns False when the text is empty, the variant or a protected slot is unknown, or an order still runs.
        """
        text = (text or "").strip()
        if not text or variant not in VARIANTS or not self.known_slots(protected):
            return False
        with self._lock:
            if self.busy:
                return False
            self.busy = True

        def work():
            try:
                self.run(text, variant, protected)
            except Exception as error:  # the chat must say what went wrong, not stop silently
                self.add({"event": "error", "reason": f"{type(error).__name__}: {error}"})
            finally:
                self.busy = False
                self.add({"event": "idle"})

        self._thread = threading.Thread(target=work, daemon=True)
        self._thread.start()
        return True

    def wait(self, timeout=None):
        """Wait for the order that runs in the background (for tests)."""
        if self._thread is not None:
            self._thread.join(timeout)

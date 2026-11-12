"""Operator console (Design Document, Chapters 4 and 9).

The operator gives orders, answers questions and is told when a run stops. The
operator is asked only under fixed conditions, and the orchestrator logs every
question, answer and waiting time as an intervention (Chapter 9).

In the experiment the answers are scripted in the task set and written before the
final runs, so runs can be repeated. A question the task set did not foresee gets
the fixed reply "no further information" (DD15). In the client demo a team member
answers live in a terminal window (proposal). Both operators have the same two
methods, ask and tell, so the orchestrator does not know which one it talks to.
"""

NO_FURTHER_INFORMATION = "no further information"


class ScriptedOperator:
    """Gives the scripted answers of a task in order, then the fixed reply (DD15).

    Matching answers to questions by their order is a proposal: the task set lists
    the answers in the order the questions are expected.
    """

    def __init__(self, answers=()):
        self._answers = list(answers)
        self.questions = []
        self.messages = []

    def ask(self, question):
        self.questions.append(question)
        return self._answers.pop(0) if self._answers else NO_FURTHER_INFORMATION

    def tell(self, message):
        self.messages.append(message)


class TerminalOperator:
    """A team member answers in a terminal window, as in the client demo (proposal)."""

    def __init__(self, read=input, write=print):
        self._read = read
        self._write = write

    def ask(self, question):
        return self._read(f"Question from the planner: {question}\n> ").strip()

    def tell(self, message):
        self._write(f"Operator notice: {message}")

"""Operator console (Design Document, Chapters 4 and 9).

The operator gives orders, answers questions and approves plans. The operator is
asked only under fixed conditions, and every question, answer and waiting time is
logged as a clarification, approval or correction. For the proof of concept the
console is a terminal window (proposal). Whether experiment runs use scripted
answers or a live team member is open decision OD5.
"""


def ask(question):
    """Show a question to the operator and return the answer."""
    raise NotImplementedError("Operator console, see Design Document Chapter 9")

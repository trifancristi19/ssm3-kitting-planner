"""LLM planner, Task A (Design Document, Chapter 7).

The planner turns an order into exactly one of a plan of allowed function calls,
a question or a refusal (FR3). Fixed code builds the prompt and parses the answer.
It is the only component that uses a language model, and it talks only to the
orchestrator (Chapter 4).

There are two variants with the same prompt builder, functions, cell and checker
(DD6, Table 8). The open loop plans once. The closed loop also gets every step
result and replans after a failed step. Every call uses a fixed model name and
version and temperature 0 (NFR1). The main model is open decision OD8, so no
model is named here. API keys come from environment variables, never from the
repository (NFR4).
"""


def build_prompt(order, state, capability, history=None):
    """Build the prompt in the order of Chapter 7 (proposal).

    The parts are the rules, the functions, the capability file, the cell state,
    the order, the earlier step results in the closed loop (history) and the
    answer format. The order text is treated as data (risk R16).
    """
    raise NotImplementedError("Prompt builder, see Design Document Chapter 7")


def call_model(prompt, settings):
    """Send the prompt to the configured model and return its raw answer."""
    raise NotImplementedError("Model client, see Design Document Chapter 7")


def parse_response(text):
    """Parse the raw answer into a plan, a question or a refusal (response parser, Table 5).

    An answer that is not exactly one of the three is an invalid-format error.
    """
    raise NotImplementedError("Response parser, see Design Document Chapters 4 and 6")

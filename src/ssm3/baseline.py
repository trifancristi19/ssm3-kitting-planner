"""Non-LLM baseline, Task C (Design Document, Chapter 11).

The baseline turns the same orders into the same kind of plan without a language
model, so the comparison isolates the planning step. It makes no model calls,
and its plans pass the same checker (DD4). Chapter 11 gives two forms, a recipe
table and a layout comparison script (proposal). The fields of the structured
order are still open (OD7, OD10).
"""


def plan_from_recipe(kit_id):
    """Look up the fixed layout of a kit and return a plan."""
    raise NotImplementedError("Recipe table, see Design Document Chapter 11")


def plan_from_layout(order):
    """Compare a new part-to-slot mapping with the tray and return a plan.

    For every changed slot that is not protected, the old part goes to the return
    position and the new part comes from its bin (proposal, Chapter 11).
    """
    raise NotImplementedError("Layout comparison, see Design Document Chapter 11")

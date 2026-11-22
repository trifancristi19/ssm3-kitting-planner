"""Order check before planning: AMBIGUOUS (Design Document, Chapter 8 and OD13, proposal).

The ambiguity check runs once, on the order text, before the planner is called, so
the closed loop never asks the same question twice. It stays fixed code outside the
model (DD7).

A mention of a part is a noun with the colour and size words just before it, as in
"the red brick" or "the big red one". The capability file lists the nouns and the
words of every part under "vocabulary" (OD13). A part matches a mention when it has
all the words of the mention. The check looks at the parts in the cell, and at the
slot the order names right after the mention, as in "the red brick in slot 1".

- One matching part: the mention is clear.
- More than one: the order is ambiguous, unless "any" or "either" stands before the
  mention (DD25). A plural ("the red bricks") is a mention too, and it also asks
  when it fits more than one kind of part.
- No matching part, or a word right before the mention that the vocabulary does
  not know ("the green brick"): the check also asks, so it never guesses.
- An order that names a part only by its ID or its slot, or names no part, passes.

The orchestrator asks the operator once for every unclear mention. An answer that
narrows the mention to exactly one part settles it. If it does not, the run stops
(OD13). A capability file without a vocabulary, such as the Chapter 6 example, gets
its words from the part IDs: SPACER_SHORT is a "spacer" that is "short". "One" is a
noun only after a describing word, so "put one red brick" is not read as two parts.
"""

import re
from dataclasses import dataclass

# Words that let several matching parts be fine.
ANY_WORDS = {"any", "either"}

# Words that may stand before a part description without describing it (proposal). Any other word there is
# read as a describing word the vocabulary does not know.
FILLER_WORDS = {
    "a", "an", "the", "one", "two", "both", "all", "any", "either", "that", "this", "these", "those", "each",
    "every", "other", "another", "same", "its", "their", "put", "place", "move", "take", "pick", "get", "fetch",
    "bring", "replace", "swap", "remove", "add", "stack", "use", "with", "and", "or", "then", "on", "onto", "in",
    "into", "from", "to", "for", "by", "of", "at", "top", "base", "is", "are", "be", "it", "them", "but", "not",
}


@dataclass(frozen=True)
class Mention:
    """A part named in the order: its words, where it stands, and how many parts it may mean."""

    index: int
    phrase: str
    said: frozenset
    noun: str
    several: bool
    unknown: str | None


def normalise(text):
    """Lower case, with "2 x 4", "2×4" and "2 by 4" all written as "2x4"."""
    text = text.lower().replace("×", "x")
    return re.sub(r"(\d)\s*(?:x|by)\s*(\d)", r"\1x\2", text)


def words(text):
    return re.findall(r"[a-z0-9]+", normalise(text))


def vocabulary(capability):
    """The nouns of each part and the describing words of each part, as two dicts of sets."""
    listed = capability.get("vocabulary", {})
    nouns, describing = {}, {}
    for part in capability["parts"]:
        if part in listed.get("parts", {}):
            nouns[part] = set(listed.get("nouns", ()))
            describing[part] = {normalise(word) for word in listed["parts"][part]}
        else:
            kind, *rest = words(part.replace("_", " "))
            nouns[part] = {kind}
            describing[part] = set(rest)
    return nouns, describing


def mentions(text, capability):
    """The mentions of parts in the order text, in order."""
    nouns, describing = vocabulary(capability)
    all_nouns = set().union(*nouns.values()) if nouns else set()
    all_words = set().union(*describing.values()) if describing else set()
    text = normalise(text)
    for part in capability["parts"]:
        text = text.replace(part.lower(), " ")  # a part named by its ID is clear
    tokens = words(text)
    found = []
    for index, token in enumerate(tokens):
        plural = token not in all_nouns and token.endswith("s") and token[:-1] in all_nouns
        noun = token[:-1] if plural else token
        if noun not in all_nouns:
            continue
        said = []
        back = index - 1
        while back >= 0 and tokens[back] in all_words and len(said) < 4:
            said.insert(0, tokens[back])
            back -= 1
        if noun == "one" and not said:
            continue  # "one" alone is a number, not a part
        before = tokens[back] if back >= 0 else None
        # Only "any" or "either" makes several matching parts acceptable, not a plural (DD25).
        several = before in ANY_WORDS
        unknown = before if before and before not in FILLER_WORDS and not before.isdigit() else None
        found.append(Mention(index, " ".join([*said, token]), frozenset(said), noun, several, unknown))
    return found, tokens


def _parts_in_cell(state):
    present = set(state["return"])
    for group in ("bins", "slots"):
        for parts in state[group].values():
            present.update(parts)
    if state["gripper"] is not None:
        present.add(state["gripper"])
    return present


def _named_slot(tokens, start, capability):
    """The slot named within a few words after a mention, as in "in slot 2", else None."""
    slots = {name.lower(): name for name in capability["positions"]["slots"]}
    window = tokens[start:start + 5]
    for index, token in enumerate(window):
        if token == "slot" and index + 1 < len(window) and f"slot_{window[index + 1]}" in slots:
            return slots[f"slot_{window[index + 1]}"]
    return None


def _matches(mention, parts, nouns, describing):
    return sorted(part for part in parts if mention.noun in nouns[part] and mention.said <= describing[part])


def _settled_by(answers, options, capability, describing):
    """True when one operator answer narrows the options to exactly one part."""
    all_words = set().union(*describing.values()) if describing else set()
    for answer in answers:
        named = [part for part in options if part.lower() in normalise(answer)]
        if len(named) == 1:
            return True
        said = set(words(answer)) & all_words
        fitting = [part for part in options if said and said <= describing[part]]
        if len(fitting) == 1:
            return True
    return False


def find_ambiguity(text, state, capability, answers=None):
    """Return (mention number, reason) for the first unclear mention in the order, or None when it is clear.

    answers maps a mention number to the operator's answers about that mention, so an answer about one part
    never settles another. The mention number lets the orchestrator ask once per mention.
    """
    answers = answers or {}
    nouns, describing = vocabulary(capability)
    present = _parts_in_cell(state) & set(capability["parts"])
    found, tokens = mentions(text, capability)
    for number, mention in enumerate(found):
        candidates = _matches(mention, present, nouns, describing)
        slot = _named_slot(tokens, mention.index + 1, capability)
        if slot is not None:
            in_slot = [part for part in candidates if part in state["slots"][slot]]
            if len(in_slot) == 1:
                continue
        if mention.unknown:
            reason = f'The word "{mention.unknown}" in "{mention.unknown} {mention.phrase}" is not in the vocabulary.'
        elif not candidates:
            reason = f'No part in the cell fits "{mention.phrase}".'
        elif len(candidates) > 1 and not mention.several:
            reason = f'"{mention.phrase}" fits {", ".join(candidates)}.'
        else:
            continue
        options = candidates if len(candidates) > 1 else sorted(present)
        if _settled_by(answers.get(number, ()), options, capability, describing):
            continue
        return number, reason + " Which part is meant?"
    return None

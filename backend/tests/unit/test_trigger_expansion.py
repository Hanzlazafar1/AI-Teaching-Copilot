"""F66: the 13 new Phase-14 trigger entries must wire into query expansion —
a query containing one of their related_skills phrases must produce the trigger."""
import pytest

from retrieval.search import expand_query_with_triggers

# (new canonical key, a query phrase that must expand to it)
NEW_TRIGGER_PROBES = [
    ("blue-hat-red-hat", "help kids determine the strongest side"),
    ("opinion-words-anchor-chart", "an opinion words anchor chart for persuasive writing"),
    ("zip-it", "teach students to zip it and stick to one strong reason"),
    ("train-engine-caboose", "the train engine and caboose opinion structure"),
    ("hand-over-mouth", "the hand over mouth strategy for holding back weak reasons"),
    ("bigger-topic", "help writers find a bigger topic to have an opinion about"),
    ("shape-book", "use a shape book to draw a topic accurately"),
    ("biography", "draw a biography of a real person"),
    ("basic-people-shapes", "draw people with basic people shapes"),
    ("true-to-life-colors", "add true-to-life colors to an informative drawing"),
    ("setting", "add setting and environment to a drawing"),
    ("adjectives-anchor-chart", "choose the best adjective with an anchor chart"),
    ("sticky-dots", "develop ideas with sticky-dot details"),
]


@pytest.mark.parametrize("key,phrase", NEW_TRIGGER_PROBES)
def test_new_trigger_expands_from_related_skill(key, phrase):
    _, trigger_names = expand_query_with_triggers(phrase, None)
    assert key in trigger_names, f"{phrase!r} did not expand to {key!r}"


# ----------------------------------------------------------------------
# April non-negotiable #7 — NAMING a lesson must find it
# ----------------------------------------------------------------------
# Brady: "If user names/asks about a specific lesson from the book, don't ad
# lib or make it up. Pull on the exact lesson already described in the book."
#
# The matcher above only ever looked at `related_skills` — i.e. it fired when a
# teacher DESCRIBED the skill, and NOT when they NAMED the strategy. That is
# the exact inverse of a rule about naming. Meanwhile every trigger's
# `synonyms` list already holds the spoken forms of its name ("read up write
# down", "road sign") and was used as OUTPUT only — added to the sparse
# expansion, never matched against. Another populated-but-unread field.
#
# Measured cost, live (19 unique-trigger lessons, backend :8060): the named
# lesson's own chunk was absent from the sources entirely in 5/19 — the teacher
# says "read up write down" and the app grounds on "paraphrase".

NAMED_LESSON_PROBES = [
    ("read-up-write-down", "Give me the read up write down lesson for grade 4"),
    ("road-sign", "Can you give me the road sign lesson?"),
    ("pie-foldable", "Give me the pie foldable lesson for grade 4"),
    ("snapple-details", "Give me the Snapple details lesson for 7th grade"),
    ("topic-test", "Give me the topic test lesson for grade 1"),
    ("story-surgery", "I want the story surgery lesson"),
    ("pizza-table", "Is there a pizza-table lesson?"),
]


@pytest.mark.parametrize("key,phrase", NAMED_LESSON_PROBES)
def test_naming_the_lesson_expands_to_its_trigger(key, phrase):
    """The teacher NAMES it — from the query text alone."""
    _, trigger_names = expand_query_with_triggers(phrase, None)
    assert key in trigger_names, f"{phrase!r} names {key!r} and did not expand to it"


@pytest.mark.parametrize("key,phrase", NAMED_LESSON_PROBES)
def test_naming_works_from_qu_terms_too(key, phrase):
    """QU canonicalizes the name into required_triggers -> smekens_terms. It
    must also work when QU's extraction flakes (measured: snapple 1/2 runs
    returned []), which is exactly why the query text alone must suffice."""
    _, trigger_names = expand_query_with_triggers(phrase, [key])
    assert key in trigger_names


def test_hyphen_and_space_forms_are_equivalent():
    for phrase in ("the read-up-write-down lesson", "the read up write down lesson"):
        _, names = expand_query_with_triggers(phrase, None)
        assert "read-up-write-down" in names, phrase


class TestNameMatchingIsWordBounded:
    """A short trigger name must never match INSIDE a word. This is the exact
    bug class that shipped to a teacher in b5dc2d9 — the citation scrubber's
    `(?:on|at|see)` had no left guard and tore "what page 2" into "wh"."""

    def test_pat_does_not_fire_inside_pattern(self):
        _, names = expand_query_with_triggers(
            "my students need a pattern for paragraphs", None)
        assert "pat" not in names

    def test_scr_does_not_fire_inside_a_word(self):
        _, names = expand_query_with_triggers("describe the screen layout", None)
        assert "scr" not in names

    def test_pat_still_fires_when_actually_named(self):
        _, names = expand_query_with_triggers("teach the PAT strategy", None)
        assert "pat" in names

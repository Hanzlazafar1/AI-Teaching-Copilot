"""Fm5 (softer / conditional book citation) — reconcile the B-P05 acceptance
assertion with Brady's OWN preferred form.

Brady's Fm5 ask (feedback-7-july.md ~12:20): a book citation should read
softly + conditionally — "If you have the {book} book, then you'll find this
lesson on p.{N}." — i.e. a "p.N" page token and NO mandatory "digital
resources" reminder.

The B-P05 acceptance helper ``assert_book_citation_present`` previously
hard-required ``page\\s*\\d+`` AND the literal ``"digital resources"``, so
Brady's own softer form FAILED both checks — the test contradicted his
documented preference. Task 3 reconciles the helper toward Brady:

  * accept any page token the scrubber's ``_CITED_PAGE_RE`` accepts
    (``page N`` / ``p. N`` / ``pg. N`` / ``pp. N``) — reusing that exact
    regex so the acceptance assert can never demand a page-form the scrubber
    would strip, and
  * make ``"digital resources"`` OPTIONAL, not required.

These unit tests pin the reconciled behavior. They construct fake
``TurnResponse`` objects and call the helper directly — no server needed, so
they run in the deterministic gate. (The exact softer wording + dropping
"digital resources" as required remain Brady's to confirm/tweak at demo.)
"""
from __future__ import annotations

import pytest

from tests.acceptance.conftest import TurnResponse, assert_book_citation_present


def _resp(text: str, *, chunk_id: str = "lww312-s8-ml05") -> TurnResponse:
    """Build a TurnResponse carrying ``text`` with one Launch-book source so
    the citation branch of the helper is exercised. Pass ``chunk_id=""`` to
    model the no-Launch-source case (no citation required)."""
    sources = [{"chunk_id": chunk_id}] if chunk_id else []
    return TurnResponse(raw={"response": text, "sources": sources}, elapsed=0.0)


class TestBP05SofterCitationReconcile:
    """assert_book_citation_present must accept Brady's softer Fm5 form."""

    def test_brady_softer_form_p_dot_no_digital_resources_passes(self):
        """Brady's verbatim Fm5 shape ("...on p.64", no "digital resources")
        must PASS. It previously failed BOTH the ``page N`` regex (no "page"
        token) AND the required "digital resources" — the core reconciliation."""
        resp = _resp(
            "If you have the Launching the Writers Workshop 3-12 book, "
            "then you'll find this lesson on p.64."
        )
        assert_book_citation_present(resp)  # must not raise

    def test_page_word_form_without_digital_resources_passes(self):
        """The classic "page 64" form must pass even when the response omits
        the "digital resources" reminder — that reminder is now optional."""
        resp = _resp(
            "If you have the Launching the Writers Workshop 3-12 book, "
            "you'll find this lesson on page 64."
        )
        assert_book_citation_present(resp)

    def test_digital_resources_still_accepted_when_present(self):
        """A response that DOES add the organizer-location "digital resources"
        pointer is still fine — optional means allowed, not forbidden."""
        resp = _resp(
            "You'll find this on page 64; the organizer is in the digital resources."
        )
        assert_book_citation_present(resp)

    def test_k2_book_with_p_dot_form_passes(self):
        """The reconciliation is book-agnostic: the K-2 Launch book
        (chunk_id matches ``\\bk2\\b``) with a ``p.N`` token also passes."""
        resp = _resp(
            "If you have the Launching the Writers Workshop K-2 book, "
            "you'll find this on p.14.",
            chunk_id="k2-s3-ml02",
        )
        assert_book_citation_present(resp)

    def test_no_launch_source_requires_no_citation(self):
        """No Launch chunk retrieved → the helper demands no citation."""
        resp = _resp(
            "Here's a coaching answer with no page and no book.", chunk_id=""
        )
        assert_book_citation_present(resp)  # must not raise

    def test_launch_source_but_no_page_still_fails(self):
        """Guard against over-loosening: when a Launch chunk IS cited, a
        recognizable page token is still required — a book pointer with no
        page is not a usable citation."""
        resp = _resp(
            "If you have the Launching the Writers Workshop 3-12 book, "
            "this lesson is in there somewhere."
        )
        with pytest.raises(AssertionError):
            assert_book_citation_present(resp)

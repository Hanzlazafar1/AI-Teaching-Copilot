"""Unit tests for retrieval/metadata_enricher.py — Phase 1 extraction."""

from __future__ import annotations

import pytest

from retrieval.metadata_enricher import (
    derive_is_scripted_lesson,
    derive_priority_rank,
    enrich_chunk,
    extract_book_name,
    extract_chapter_number,
    extract_ml_number,
    extract_skill_title,
    extract_topic_keywords,
    format_book_reference,
    tag_chunk_with_triggers,
)


# ---------------------------------------------------------------------------
# book_name
# ---------------------------------------------------------------------------


class TestExtractBookName:
    def test_3_12_book(self):
        assert extract_book_name("Launching the Writers Workshop 3-12.pdf") == ("Teal", 1.0)

    def test_k2_book(self):
        assert extract_book_name("Launching the Writers Workshop K-2.pdf") == ("K-2", 1.0)

    def test_episode_script(self):
        assert extract_book_name("Ep 5 ELEM Script.pdf") == (None, 0.0)

    def test_empty(self):
        assert extract_book_name("") == (None, 0.0)

    def test_none(self):
        assert extract_book_name(None) == (None, 0.0)


# ---------------------------------------------------------------------------
# chapter_number
# ---------------------------------------------------------------------------


class TestExtractChapterNumber:
    def test_standard_section_8(self):
        sn = "Section 8: Teaching Ideas — ML #7: Add interest with Snapple details"
        assert extract_chapter_number(sn) == (8, 1.0)

    def test_section_13(self):
        sn = "Section 13: Drafting Whole Pieces — Mini-Lesson #14: End narratives"
        assert extract_chapter_number(sn) == (13, 1.0)

    def test_comma_format(self):
        sn = "Section 10: Teaching Voice, Mini-Lesson #1"
        assert extract_chapter_number(sn) == (10, 1.0)

    def test_overview(self):
        assert extract_chapter_number("Overview: How to Use This Book") == (None, 0.0)

    def test_toc(self):
        assert extract_chapter_number("Table of Contents") == (None, 0.0)

    def test_pacing(self):
        assert extract_chapter_number("Pacing Guide: Grades 3-5") == (None, 0.0)

    def test_empty(self):
        assert extract_chapter_number("") == (None, 0.0)

    def test_none(self):
        assert extract_chapter_number(None) == (None, 0.0)


# ---------------------------------------------------------------------------
# ml_number
# ---------------------------------------------------------------------------


class TestExtractMLNumber:
    def test_ml_format(self):
        assert extract_ml_number("Section 9 — ML #12: Create transitions") == (12, 1.0)

    def test_mini_lesson_format(self):
        assert extract_ml_number("Section 8 — Mini-Lesson #7: Snapple") == (7, 1.0)

    def test_part_variant(self):
        assert extract_ml_number("Section 7 — ML #1 Part 1: Build rubric") == (1, 1.0)

    def test_overview_no_ml(self):
        assert extract_ml_number("Overview: How to Use") == (None, 0.0)

    def test_empty(self):
        assert extract_ml_number("") == (None, 0.0)

    def test_from_content_when_section_missing(self):
        """K-2 Section 8 style: section_name has no ML marker but content does."""
        sn = "Section 8: Drawing Pictures"
        content = "Launching the Writer's Workshop: Grades K-2 -- Section 8: Drawing Pictures, Mini-Lesson #9\n\nMINI-LESSON #9: Magnify close-up details\n\nHave children..."
        assert extract_ml_number(sn, content=content) == (9, 0.9)

    def test_from_chunk_id_as_last_resort(self):
        """If section_name and content don't have it, chunk_id pattern matches."""
        sn = "Overview"
        content = "Content without ML marker"
        chunk_id = "k2-s8-ml3-create-self-portraits"
        result = extract_ml_number(sn, content=content, chunk_id=chunk_id)
        assert result == (3, 0.8)


# ---------------------------------------------------------------------------
# skill_title
# ---------------------------------------------------------------------------


class TestExtractSkillTitle:
    def test_standard_em_dash(self):
        sn = "Section 8: Teaching Ideas — ML #7: Add interest with Snapple details"
        title, conf = extract_skill_title(sn)
        assert title == "Add interest with Snapple details"
        assert conf == 1.0

    def test_standard_mini_lesson(self):
        sn = "Section 13: Drafting Whole Pieces — Mini-Lesson #4: Add legs to table-top"
        title, conf = extract_skill_title(sn)
        assert title == "Add legs to table-top"
        assert conf == 1.0

    def test_part_variant(self):
        sn = "Section 7: Building Rubrics — ML #1 Part 1: Build a simple rubric (concept)"
        title, conf = extract_skill_title(sn)
        assert title == "Build a simple rubric (concept)"
        assert conf == 0.7  # medium — non-standard pattern

    def test_alternative_variant(self):
        sn = "Section 9: Teaching Organization — ML #3 Alternative: List & organize ABC Chart details"
        title, conf = extract_skill_title(sn)
        assert title == "List & organize ABC Chart details"
        assert conf == 0.7

    def test_additional_resources(self):
        sn = "Section 9: Teaching Organization — ML #4 Additional Resources: Compare-contrast categories"
        title, conf = extract_skill_title(sn)
        assert title == "Compare-contrast categories"
        assert conf == 0.7

    def test_follow_up_no_title(self):
        sn = "Section 13: Drafting Whole Pieces — Mini-Lesson #16 Follow-Up Lessons"
        title, conf = extract_skill_title(sn)
        assert title is None
        assert conf == 0.5

    def test_comma_format_with_content_fallback(self):
        sn = "Section 10: Teaching Voice, Mini-Lesson #1"
        content = (
            "Launching the Writer's Workshop: Grades 3-12 — Section 10: Teaching Voice, "
            "Mini-Lesson #1: Detect and name the voice\n\nVoice is the writer's attitude..."
        )
        title, conf = extract_skill_title(sn, content=content)
        assert title == "Detect and name the voice"
        assert conf == 0.8

    def test_comma_format_with_strategy_fallback(self):
        sn = "Section 10: Teaching Voice, Mini-Lesson #1"
        title, conf = extract_skill_title(sn, strategy_name="detect-and-name-voice")
        assert title == "Detect And Name Voice"
        assert conf == 0.5

    def test_em_dash_no_ml_marker(self):
        sn = "Section 7: Mini-Lesson #1 — Holistic vs. Analytic Scoring"
        title, conf = extract_skill_title(sn)
        assert title == "Holistic vs. Analytic Scoring"
        assert conf == 0.9  # Em-dash fallback is reliable (verified against real data)

    def test_empty_section_name(self):
        title, conf = extract_skill_title("")
        assert title is None
        assert conf == 0.0

    def test_overview_no_title(self):
        title, conf = extract_skill_title("Overview: How to Use This Book")
        # "How to Use This Book" — matches "— Title" fallback? No, no em-dash
        # Returns None / 0.0
        assert title is None
        assert conf == 0.0

    def test_k2_s8_drawing_pictures_from_content(self):
        """K-2 Section 8: section_name has no ML marker, content does (MINI-LESSON #9:)."""
        sn = "Section 8: Drawing Pictures"
        content = (
            "Launching the Writer's Workshop: Grades K-2 -- Section 8: Drawing Pictures, Mini-Lesson #9\n"
            "\n"
            "MINI-LESSON #9: Magnify close-up details\n"
            "\n"
            "Have children take a walk outside..."
        )
        title, conf = extract_skill_title(sn, content=content)
        assert title == "Magnify close-up details"
        assert conf == 0.9  # Content-header extraction is reliable


# ---------------------------------------------------------------------------
# is_scripted_lesson
# ---------------------------------------------------------------------------


class TestIsScriptedLesson:
    def test_is_scripted_example_true(self):
        assert derive_is_scripted_lesson({"is_scripted_example": True}) == (True, 1.0)

    def test_lesson_script_content_type(self):
        assert derive_is_scripted_lesson({"content_type": "lesson_script"}) == (True, 1.0)

    def test_think_aloud_script(self):
        assert derive_is_scripted_lesson({"content_type": "think_aloud_script"}) == (True, 1.0)

    def test_textbook_lesson_is_not_scripted(self):
        # textbook_lesson chunks are ML content, not scripted templates
        assert derive_is_scripted_lesson({"content_type": "textbook_lesson"}) == (False, 1.0)

    def test_episode_explanation_not_scripted(self):
        chunk = {"content_type": "episode_explanation", "is_scripted_example": False}
        assert derive_is_scripted_lesson(chunk) == (False, 1.0)


# ---------------------------------------------------------------------------
# priority_rank
# ---------------------------------------------------------------------------


class TestPriorityRank:
    def test_launch_3_12(self):
        chunk = {
            "source_document": "Launching the Writers Workshop 3-12.pdf",
            "source_category": "textbook",
        }
        assert derive_priority_rank(chunk) == (1, 1.0)

    def test_launch_k2(self):
        chunk = {
            "source_document": "Launching the Writers Workshop K-2.pdf",
            "source_category": "textbook",
        }
        assert derive_priority_rank(chunk) == (1, 1.0)

    def test_episode_script(self):
        chunk = {
            "source_document": "Ep 3 ELEM Script.pdf",
            "source_category": "episode_script",
        }
        assert derive_priority_rank(chunk) == (4, 1.0)

    def test_core_methodology_is_other(self):
        chunk = {
            "source_document": "Master the 4-step mini-lesson.pdf",
            "source_category": "core_methodology",
        }
        # Phase 1: not Launch book, not episode → 5 (other)
        assert derive_priority_rank(chunk) == (5, 1.0)


# ---------------------------------------------------------------------------
# topic_keywords
# ---------------------------------------------------------------------------


class TestTopicKeywords:
    def test_extracts_significant_words(self):
        keywords, conf = extract_topic_keywords(
            "Section 8: Teaching Ideas — ML #7: Add interest with Snapple details",
            "Add interest with Snapple details by asking students to...",
        )
        # Should include meaningful words, exclude stopwords
        assert "snapple" in keywords
        assert "details" in keywords
        assert "the" not in keywords  # stopword
        assert "and" not in keywords
        assert conf == 0.7

    def test_empty_inputs(self):
        keywords, conf = extract_topic_keywords(None, None)
        assert keywords == []
        assert conf == 0.0

    def test_max_keywords(self):
        long_content = " ".join(["word" + str(i) for i in range(50)])
        keywords, _ = extract_topic_keywords("Section", long_content, max_keywords=5)
        assert len(keywords) <= 5

    def test_dedup(self):
        keywords, _ = extract_topic_keywords(
            "Paragraph paragraph paragraph",
            "paragraph paragraph paragraph",
        )
        # Should appear only once
        assert keywords.count("paragraph") == 1


# ---------------------------------------------------------------------------
# book_reference formatter
# ---------------------------------------------------------------------------


class TestFormatBookReference:
    def test_full_with_page(self):
        ref, conf = format_book_reference("Teal", 8, 5, page_number=64)
        assert ref == "Teal book p. 64 (Section 8, ML #5)"
        assert conf == 1.0

    def test_no_page(self):
        ref, conf = format_book_reference("Teal", 8, 5, page_number=None)
        assert ref == "Teal book, Section 8, ML #5"
        assert conf == 0.8

    def test_no_ml_number(self):
        ref, conf = format_book_reference("K-2", 3, None, page_number=None)
        assert ref == "K-2 book, Section 3"
        assert conf == 0.8

    def test_no_book_name(self):
        ref, conf = format_book_reference(None, 3, 1)
        assert ref is None
        assert conf == 0.0


# ---------------------------------------------------------------------------
# Integration: enrich_chunk
# ---------------------------------------------------------------------------


class TestEnrichChunk:
    def test_launch_ml_chunk(self):
        chunk = {
            "chunk_id": "lww312-s8-ml7-snapple",
            "source_document": "Launching the Writers Workshop 3-12.pdf",
            "section_name": "Section 8: Teaching Ideas — ML #7: Add interest with Snapple details",
            "content_type": "textbook_lesson",
            "content": "Snapple details engage readers...",
            "strategy_name": "snapple-details",
            "source_category": "textbook",
            "is_scripted_example": False,
        }
        enriched, confidences = enrich_chunk(chunk)
        assert enriched["book_name"] == "Teal"
        assert enriched["chapter_number"] == 8
        assert enriched["ml_number"] == 7
        assert enriched["skill_title"] == "Add interest with Snapple details"
        assert enriched["priority_rank"] == 1
        # A Launch-book mini-lesson IS a Smekens scripted ML (the book's
        # textbook_lesson entries are what the ML Library draws from verbatim).
        assert enriched["is_scripted_lesson"] is True
        assert enriched["book_reference"] == "Teal book, Section 8, ML #7"
        # Phase 2/3 fields initialised empty
        assert enriched["pie_tags_by_band"] == {}
        assert enriched["lesson_trigger"] == []
        assert enriched["page_number"] is None
        # Original fields preserved
        assert enriched["chunk_id"] == "lww312-s8-ml7-snapple"
        # Confidences all high
        assert confidences["book_name"] == 1.0
        assert confidences["skill_title"] == 1.0

    def test_overview_chunk(self):
        chunk = {
            "chunk_id": "lww312-overview",
            "source_document": "Launching the Writers Workshop 3-12.pdf",
            "section_name": "Overview: How to Use This Book",
            "content_type": "textbook_overview",
            "content": "This book supports teachers...",
            "strategy_name": "",
            "source_category": "textbook",
            "is_scripted_example": False,
        }
        enriched, confidences = enrich_chunk(chunk)
        assert enriched["book_name"] == "Teal"
        assert enriched["chapter_number"] is None  # overview has no chapter
        assert enriched["ml_number"] is None
        # skill_title may extract "How to Use This Book" via em-dash fallback? No, no em-dash
        # Should be None
        assert enriched["skill_title"] is None
        assert enriched["priority_rank"] == 1  # still Launch book

    def test_episode_chunk(self):
        chunk = {
            "chunk_id": "ep3-elem-intro",
            "source_document": "Ep 3 ELEM Script.pdf",
            "section_name": "What Is Informative Writing — Overview",
            "content_type": "episode_explanation",
            "content": "Informative writing...",
            "strategy_name": "",
            "source_category": "episode_script",
            "is_scripted_example": False,
        }
        enriched, confidences = enrich_chunk(chunk)
        assert enriched["book_name"] is None
        assert enriched["chapter_number"] is None
        assert enriched["priority_rank"] == 4
        assert enriched["is_scripted_lesson"] is False

    def test_comma_format_content_fallback(self):
        """Chunks with comma-format section_name should extract title from content."""
        chunk = {
            "chunk_id": "lww312-s10-ml1-detect-voice",
            "source_document": "Launching the Writers Workshop 3-12.pdf",
            "section_name": "Section 10: Teaching Voice, Mini-Lesson #1",
            "content_type": "textbook_lesson",
            "content": (
                "Launching the Writer's Workshop: Grades 3-12 — Section 10: Teaching Voice, "
                "Mini-Lesson #1: Detect and name the voice\n\nVoice is the writer's attitude..."
            ),
            "strategy_name": "detect-and-name-voice",
            "source_category": "textbook",
            "is_scripted_example": False,
        }
        enriched, confidences = enrich_chunk(chunk)
        assert enriched["skill_title"] == "Detect and name the voice"
        assert confidences["skill_title"] == 0.8  # content fallback confidence

    def test_idempotent(self):
        """Running enrich_chunk twice produces same result."""
        chunk = {
            "chunk_id": "lww312-s8-ml7",
            "source_document": "Launching the Writers Workshop 3-12.pdf",
            "section_name": "Section 8: Teaching Ideas — ML #7: Snapple details",
            "content_type": "textbook_lesson",
            "content": "Content here...",
            "strategy_name": "snapple-details",
            "source_category": "textbook",
            "is_scripted_example": False,
        }
        e1, _ = enrich_chunk(chunk)
        e2, _ = enrich_chunk(e1)
        assert e1 == e2


# ---------------------------------------------------------------------------
# Flagging threshold
# ---------------------------------------------------------------------------


class TestTagChunkWithTriggers:
    """Verify trigger tagging works with synonyms and word boundaries."""

    TRIGGERS = {
        "pizza-table": {
            "synonyms": ["pizza table", "table-top and legs", "leg sentences"],
            "related_skills": ["paragraph writing"],
        },
        "slinky-test": {
            "synonyms": ["slinky test", "slinky"],
            "related_skills": ["sentence fluency"],
        },
        "pat": {
            "synonyms": ["P.A.T.", "Purpose Audience Task"],
            "related_skills": ["voice"],
        },
    }

    def test_single_trigger_match(self):
        chunk = {"content": "Use the pizza table strategy to organize paragraphs."}
        result = tag_chunk_with_triggers(chunk, self.TRIGGERS)
        assert result["lesson_trigger"] == ["pizza-table"]

    def test_multiple_triggers_match(self):
        chunk = {
            "content": "The slinky test helps sentence fluency. The pizza table helps paragraph structure.",
        }
        result = tag_chunk_with_triggers(chunk, self.TRIGGERS)
        assert sorted(result["lesson_trigger"]) == ["pizza-table", "slinky-test"]

    def test_matches_in_skill_title(self):
        chunk = {
            "content": "",
            "skill_title": "Assess sentence-length variety with the slinky",
        }
        result = tag_chunk_with_triggers(chunk, self.TRIGGERS)
        assert result["lesson_trigger"] == ["slinky-test"]

    def test_no_match(self):
        chunk = {"content": "This is a generic lesson without any Smekens trigger."}
        result = tag_chunk_with_triggers(chunk, self.TRIGGERS)
        # Empty list is expected — stale values must be cleared
        assert result.get("lesson_trigger") == []

    def test_short_acronym_word_boundary(self):
        # 'pat' acronym must NOT match within 'paternal' or 'patience'
        chunk = {"content": "This is a paternal talk about patience, not about writing."}
        result = tag_chunk_with_triggers(chunk, self.TRIGGERS)
        # Should not tag pat
        assert not result.get("lesson_trigger") or "pat" not in result.get("lesson_trigger", [])

    def test_hyphen_flexible_match(self):
        # synonym 'table-top and legs' should also match 'table top and legs'
        chunk = {"content": "We use table top and legs for supporting reasons."}
        result = tag_chunk_with_triggers(chunk, self.TRIGGERS)
        assert "pizza-table" in result.get("lesson_trigger", [])


class TestFlaggingThreshold:
    """Verify confidence scores correctly flag items for review."""

    FLAG_THRESHOLD = 0.9

    def test_high_confidence_not_flagged(self):
        _, conf = extract_skill_title(
            "Section 8: Teaching Ideas — ML #7: Add interest with Snapple details"
        )
        assert conf >= self.FLAG_THRESHOLD

    def test_medium_confidence_flagged(self):
        _, conf = extract_skill_title(
            "Section 9: Teaching Organization — ML #3 Alternative: List details"
        )
        assert conf < self.FLAG_THRESHOLD

    def test_content_fallback_flagged(self):
        _, conf = extract_skill_title(
            "Section 10: Teaching Voice, Mini-Lesson #1",
            content="Section 10: ... Mini-Lesson #1: Detect and name the voice",
        )
        assert conf < self.FLAG_THRESHOLD  # 0.8 — should be reviewed

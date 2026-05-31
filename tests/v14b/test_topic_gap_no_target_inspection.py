from __future__ import annotations

from types import SimpleNamespace

from echelon.v14b.topic_gap_no_target_inspection import inspect_no_target_blocks


def _block(text: str, page_no: int = 1):
    return SimpleNamespace(text=text, page_no=page_no, section_hint="body")


def test_no_target_inspection_detects_target_heading_signal():
    result = inspect_no_target_blocks(
        [
            _block(
                "1 Introduction\ncontext\n"
                "2 Results and Discussion\n"
                "The device is evaluated with enough section text to exceed the extraction threshold. "
                "The remaining paragraph continues with measurement details and limitations of the setup. "
                "This deliberately long section body carries enough characters to count as a repair signal "
                "rather than a short heading fragment."
            )
        ]
    )

    assert result["classification"] == "target_heading_signal_present"
    assert result["target_heading_candidates"][0]["section"] == "discussion"


def test_no_target_inspection_keeps_short_target_fragment_subthreshold():
    result = inspect_no_target_blocks(
        [
            _block("OUTLOOK Robust optical delay lines with topological protection.")
        ]
    )

    assert result["classification"] == "target_heading_signal_subthreshold"
    assert result["target_heading_candidates"][0]["body_chars"] < 160


def test_no_target_inspection_classifies_sectionless_article_format():
    result = inspect_no_target_blocks(
        [
            _block(
                "Abstract\n"
                "We demonstrate a compact device in a short letter format.\n"
                "References"
            )
        ]
    )

    assert result["classification"] == "sectionless_or_non_target_heading_format"
    assert result["non_target_heading_examples"][0]["text"] == "Abstract"


def test_no_target_inspection_handles_parser_empty_text():
    result = inspect_no_target_blocks([])

    assert result["classification"] == "parse_no_text"
    assert result["text_blocks"] == 0

from dataclasses import dataclass

from echelon.v14b.step5s_section_ingest import _arxiv_pdf_url, extract_sections_from_blocks


@dataclass
class _Block:
    text: str
    section_hint: str = "body"


def test_arxiv_pdf_url_from_arxiv_id_and_doi():
    assert _arxiv_pdf_url("2401.12345v2", None) == "https://arxiv.org/pdf/2401.12345.pdf"
    assert _arxiv_pdf_url(None, "10.48550/arXiv.2301.00001v3") == "https://arxiv.org/pdf/2301.00001.pdf"
    assert _arxiv_pdf_url(None, "10.1000/journal.paper") is None


def test_extract_sections_from_blocks_captures_primary_and_secondary_sections():
    long_tail = " This paragraph describes concrete technical constraints and evidence." * 8
    blocks = [
        _Block("1 Discussion\nWe analyze unresolved constraints." + long_tail),
        _Block("2 Future Work\nFuture work requires better noise suppression." + long_tail),
        _Block("3 Error Analysis\nFailure cases remain in low-SNR regime." + long_tail),
        _Block("4 Ablation Study\nAblation indicates coupling instability." + long_tail),
        _Block("5 Conclusion\nThe remaining bottleneck is fabrication tolerance." + long_tail),
    ]
    sections = extract_sections_from_blocks(blocks)
    assert "discussion" in sections
    assert "future_work" in sections
    assert "conclusion" in sections
    assert "error_analysis" in sections
    assert "ablation" in sections
    for text in sections.values():
        assert len(text) >= 160

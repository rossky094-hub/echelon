#!/usr/bin/env python3
"""
Enhanced parse_pdf.py - better raw text section splitting
"""

import re
import json
import os
import logging
from pathlib import Path

import fitz  # pymupdf

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

PDF_DIR = '/home/user/workspace/echelon_mvp0a/scibot/pdfs'
PARSED_DIR = '/home/user/workspace/echelon_mvp0a/scibot/parsed'

LIMITATION_SENTENCE = re.compile(
    r'[^.!?]*\b(?:limitation|however|cannot|can\'t|fail|challenge|difficult|unable|'
    r'prohibit|prevent|restrict|constraint|barrier|bottleneck|drawback|shortcoming|'
    r'inadequate|insufficient|poor performance|does not|did not|not able)\b[^.!?]*[.!?]',
    re.I
)

# Section patterns - more flexible
SECTION_MAP = [
    ('abstract',      re.compile(r'^abstract\s*$', re.I)),
    ('introduction',  re.compile(r'^(?:\d+\.?\s+)?introduction\s*$', re.I)),
    ('related_work',  re.compile(r'^(?:\d+\.?\s+)?related\s+work\s*$', re.I)),
    ('background',    re.compile(r'^(?:\d+\.?\s+)?background\s*$', re.I)),
    ('methods',       re.compile(r'^(?:\d+\.?\s+)?(?:methods?|methodology|approach|'
                                  r'materials?\s+and\s+methods?|experimental\s+(?:setup|methods?)|'
                                  r'experimental\s+section|materials\s+&\s+methods?)\s*$', re.I)),
    ('results',       re.compile(r'^(?:\d+\.?\s+)?(?:results?\s*(?:and\s+)?(?:analysis)?'
                                  r'|experiments?(?:\s+and\s+analysis)?'
                                  r'|evaluation|performance|numerical\s+results?)\s*$', re.I)),
    # Combined results+discussion (common in Nature journals)
    ('discussion',    re.compile(r'^(?:\d+\.?\s+)?(?:discussion|results\s+and\s+discussion'
                                  r'|discussion\s+and\s+conclusions?)\s*$', re.I)),
    ('limitations',   re.compile(r'^(?:\d+\.?\s+)?limitations?\s*(?:and\s+future\s+work)?\s*$', re.I)),
    ('future_work',   re.compile(r'^(?:\d+\.?\s+)?future\s+(?:work|directions?|research)\s*$', re.I)),
    ('conclusion',    re.compile(r'^(?:\d+\.?\s+)?conclusions?\s*(?:and\s+future\s+work)?\s*$', re.I)),
    ('appendix',      re.compile(r'^appendix\s*', re.I)),
    ('references',    re.compile(r'^references?\s*$', re.I)),
    ('acknowledgments', re.compile(r'^acknowledgm?ents?\s*$', re.I)),
]

STOP_SECTIONS = {'references', 'acknowledgments', 'appendix'}


def classify_heading(text: str):
    clean = text.strip()
    for sec, pat in SECTION_MAP:
        if pat.match(clean):
            return sec
    return None


def extract_title_from_pdf(doc, fallback=''):
    meta = doc.metadata
    if meta.get('title') and len(meta.get('title', '')) > 5:
        return meta['title'].strip()
    if len(doc) > 0:
        page = doc[0]
        blocks = page.get_text('dict')['blocks']
        candidates = []
        for block in blocks:
            if block.get('type') != 0:
                continue
            for line in block.get('lines', []):
                for span in line.get('spans', []):
                    txt = span.get('text', '').strip()
                    size = span.get('size', 0)
                    if txt and size >= 11 and len(txt) > 10:
                        candidates.append((size, txt))
        if candidates:
            candidates.sort(key=lambda x: -x[0])
            return candidates[0][1]
    return fallback


def parse_pdf_with_sections(pdf_path: str, paper_id: str = '') -> dict:
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        return {'error': str(e), 'paper_id': paper_id}

    title = extract_title_from_pdf(doc, fallback=os.path.basename(pdf_path))
    page_count = len(doc)

    # Get raw text
    raw_text_parts = []
    for page in doc:
        raw_text_parts.append(page.get_text())
    raw_text = '\n'.join(raw_text_parts)

    # Try block-level structure detection
    sections = extract_sections_block_method(doc, raw_text)

    doc.close()

    # Compute stats
    section_stats = {k: len(v) for k, v in sections.items() if not k.startswith('_')}

    has_limitations = len(sections.get('limitations', '')) > 50
    has_discussion = len(sections.get('discussion', '')) > 50

    return {
        'paper_id': paper_id,
        'title': title,
        'sections': sections,
        'section_stats': section_stats,
        'raw_text': raw_text[:60000],
        'page_count': page_count,
        'has_limitations': has_limitations,
        'has_discussion': has_discussion,
    }


def extract_sections_block_method(doc, raw_text: str) -> dict:
    """Multi-pass section extraction."""
    sections = {k: '' for k, _ in SECTION_MAP}

    # Pass 1: font-based heading detection
    heading_candidates = []
    body_sizes = []
    all_blocks = []

    for page_num, page in enumerate(doc):
        pg_dict = page.get_text('dict', flags=fitz.TEXT_PRESERVE_WHITESPACE)
        for block in pg_dict.get('blocks', []):
            if block.get('type') != 0:
                continue
            lines = block.get('lines', [])
            block_text_parts = []
            is_bold = False
            max_size = 0
            for line in lines:
                for span in line.get('spans', []):
                    t = span.get('text', '')
                    block_text_parts.append(t)
                    if span.get('flags', 0) & 16:
                        is_bold = True
                    if span.get('size', 0) > max_size:
                        max_size = span['size']
                    body_sizes.append(span.get('size', 0))
            block_text = ''.join(block_text_parts).strip()
            if block_text:
                all_blocks.append({
                    'text': block_text,
                    'is_bold': is_bold,
                    'max_size': max_size,
                    'page': page_num + 1,
                })

    # Estimate body font size (mode)
    if body_sizes:
        from collections import Counter
        size_counter = Counter(round(s, 1) for s in body_sizes if s > 0)
        body_size = size_counter.most_common(1)[0][0]
    else:
        body_size = 10.0

    # Pass 2: identify headings and segment
    current_section = 'preamble'
    section_texts = {'preamble': []}

    for block in all_blocks:
        text = block['text']
        is_bold = block['is_bold']
        max_size = block['max_size']

        # A heading candidate: short, bold/large, matches known pattern
        is_heading_like = (
            len(text) < 100 and
            (is_bold and max_size >= body_size * 0.95 or max_size >= body_size * 1.2)
        )

        heading_type = None
        if is_heading_like:
            heading_type = classify_heading(text)
        # Also try raw match even without font signals
        if heading_type is None and len(text) < 60:
            heading_type = classify_heading(text)

        if heading_type:
            current_section = heading_type
            if current_section not in section_texts:
                section_texts[current_section] = []
        else:
            if current_section == 'references':
                continue  # skip reference content
            if current_section not in section_texts:
                section_texts[current_section] = []
            section_texts[current_section].append(text)

    # Merge text
    for sec in sections:
        if sec in section_texts:
            sections[sec] = '\n\n'.join(section_texts[sec]).strip()

    # Pass 3: fallback - raw text line splitting
    non_empty = sum(1 for k, v in sections.items() if len(v) > 100 and not k.startswith('_'))
    if non_empty < 2:
        sections = raw_text_section_split(raw_text)

    # Post-process: extract limitations from discussion if missing
    if len(sections.get('limitations', '')) < 50:
        src = sections.get('discussion', '') + ' ' + sections.get('conclusion', '')
        lim_sentences = LIMITATION_SENTENCE.findall(src)
        if lim_sentences:
            sections['limitations'] = '[Auto-extracted] ' + ' '.join(lim_sentences[:15])

    # Mark method
    sections['_method'] = 'block+raw'
    return sections


def raw_text_section_split(raw_text: str) -> dict:
    sections = {k: '' for k, _ in SECTION_MAP}
    current = 'preamble'
    section_texts = {'preamble': []}

    lines = raw_text.split('\n')
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        heading = classify_heading(stripped) if len(stripped) < 80 else None
        if heading:
            current = heading
            if current not in section_texts:
                section_texts[current] = []
        else:
            if current == 'references':
                continue
            if current not in section_texts:
                section_texts[current] = []
            section_texts[current].append(line)

    for sec in sections:
        if sec in section_texts:
            sections[sec] = '\n'.join(section_texts[sec]).strip()

    # Extract limitations from discussion if needed
    if len(sections.get('limitations', '')) < 50:
        src = sections.get('discussion', '') + ' ' + sections.get('conclusion', '')
        lim_sentences = LIMITATION_SENTENCE.findall(src)
        if lim_sentences:
            sections['limitations'] = '[Auto-extracted] ' + ' '.join(lim_sentences[:15])

    return sections


def parse_all_pdfs():
    pdf_files = list(Path(PDF_DIR).glob('*.pdf'))
    logger.info(f"Found {len(pdf_files)} PDFs to parse")

    seeds_file = '/home/user/workspace/echelon_mvp0a/reports/v5/llm_seeds_with_resources.json'
    with open(seeds_file) as f:
        seeds = json.load(f)
    seeds_map = {s['paper_id']: s for s in seeds}

    results = []
    for pdf_path in pdf_files:
        paper_id = pdf_path.stem
        if paper_id.startswith('_'):
            continue

        seed = seeds_map.get(paper_id, {})
        logger.info(f"Parsing: {paper_id} ({seed.get('title', '?')[:60]})")

        result = parse_pdf_with_sections(str(pdf_path), paper_id=paper_id)
        result['seed_title'] = seed.get('title', result.get('title', ''))
        result['topic_name'] = seed.get('topic_name', '')
        result['doi'] = seed.get('doi', '')

        out_path = os.path.join(PARSED_DIR, f"{paper_id}.json")
        with open(out_path, 'w') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        results.append({
            'paper_id': paper_id,
            'title': result.get('seed_title', result.get('title', ''))[:80],
            'has_limitations': result.get('has_limitations', False),
            'has_discussion': result.get('has_discussion', False),
            'page_count': result.get('page_count', 0),
            'section_stats': result.get('section_stats', {}),
        })

        lim_len = result.get('section_stats', {}).get('limitations', 0)
        disc_len = result.get('section_stats', {}).get('discussion', 0)
        conc_len = result.get('section_stats', {}).get('conclusion', 0)
        logger.info(f"  Pages:{result.get('page_count',0)}, Lim:{lim_len}ch, Disc:{disc_len}ch, Conc:{conc_len}ch")

    n_lim = sum(1 for r in results if r['has_limitations'])
    n_disc = sum(1 for r in results if r['has_discussion'])
    logger.info(f"\n=== PARSE SUMMARY ===")
    logger.info(f"Parsed: {len(results)}")
    logger.info(f"Has limitations: {n_lim}/{len(results)}")
    logger.info(f"Has discussion: {n_disc}/{len(results)}")

    summary_path = os.path.join(PARSED_DIR, '_parse_summary.json')
    with open(summary_path, 'w') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    return results


if __name__ == '__main__':
    parse_all_pdfs()


# ─────────────────────────────────────────────
# V13 Importable interface (不破坏 __main__)
# ─────────────────────────────────────────────

def parse_pdfs_batch(
    paper_ids: list,
    pdf_dir: str = PDF_DIR,
    parsed_dir: str = PARSED_DIR,
) -> dict:
    """
    V13 pilot interface: parse a list of PDFs.

    Args:
        paper_ids:  list of paper_id strings to parse
        pdf_dir:    directory containing PDFs
        parsed_dir: directory for parsed JSON output

    Returns:
        dict with 'parsed', 'skipped', 'failed', 'total'
    """
    import os
    os.makedirs(parsed_dir, exist_ok=True)
    parsed = []
    skipped = []
    failed = []

    for pid in paper_ids:
        pdf_path = os.path.join(pdf_dir, f"{pid}.pdf")
        parsed_path = os.path.join(parsed_dir, f"{pid}.json")

        if os.path.exists(parsed_path):
            skipped.append(pid)
            continue

        if not os.path.exists(pdf_path):
            failed.append({"paper_id": pid, "error": "pdf_not_found"})
            continue

        try:
            result = parse_pdf_with_sections(pdf_path, paper_id=pid)
            with open(parsed_path, "w") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            parsed.append(pid)
            logger.info(f"  Parsed {pid}")
        except Exception as e:
            failed.append({"paper_id": pid, "error": str(e)[:100]})
            logger.warning(f"  Failed {pid}: {e}")

    return {
        "parsed": parsed,
        "skipped": skipped,
        "failed": failed,
        "total": len(parsed) + len(skipped),
    }


def parse_all_pdfs_importable(
    pdf_dir: str = PDF_DIR,
    parsed_dir: str = PARSED_DIR,
) -> dict:
    """
    V13 importable wrapper for parse_all_pdfs().
    Parses all PDFs in pdf_dir not yet in parsed_dir.
    """
    import os
    os.makedirs(parsed_dir, exist_ok=True)
    all_pdf_ids = [f[:-4] for f in os.listdir(pdf_dir) if f.endswith(".pdf")]
    return parse_pdfs_batch(all_pdf_ids, pdf_dir=pdf_dir, parsed_dir=parsed_dir)

#!/usr/bin/env python3
"""
fetch_pdfs.py - Step 1: Download OA PDFs for Sci-Bot RAG pipeline
Downloads from oa_url field in llm_seeds_with_resources.json
"""

import json
import os
import time
import requests
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

SEEDS_FILE = '/home/user/workspace/echelon_mvp0a/reports/v5/llm_seeds_with_resources.json'
PDF_DIR = '/home/user/workspace/echelon_mvp0a/scibot/pdfs'
FAILURES_FILE = os.path.join(PDF_DIR, '_failures.json')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/pdf,*/*',
    'Accept-Language': 'en-US,en;q=0.9',
}

TIMEOUT = 30
MAX_SIZE_MB = 50


def download_pdf(url: str, dest_path: str) -> tuple[bool, str]:
    """Download a PDF from URL to dest_path. Returns (success, message)."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, stream=True, allow_redirects=True)
        resp.raise_for_status()

        content_type = resp.headers.get('content-type', '')
        if 'html' in content_type and 'pdf' not in url.lower():
            return False, f"Got HTML instead of PDF (content-type: {content_type})"

        size = 0
        with open(dest_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    size += len(chunk)
                    if size > MAX_SIZE_MB * 1024 * 1024:
                        f.flush()
                        return False, f"File too large (> {MAX_SIZE_MB}MB)"
                    f.write(chunk)

        # Verify it's actually a PDF
        with open(dest_path, 'rb') as f:
            header = f.read(5)
        if header != b'%PDF-':
            os.remove(dest_path)
            return False, f"Downloaded file is not a PDF (header: {header[:20]})"

        logger.info(f"  Downloaded {size/1024:.1f}KB")
        return True, f"OK ({size/1024:.1f}KB)"

    except requests.exceptions.Timeout:
        return False, "Timeout"
    except requests.exceptions.HTTPError as e:
        return False, f"HTTP {e.response.status_code}"
    except requests.exceptions.ConnectionError as e:
        return False, f"Connection error: {str(e)[:100]}"
    except Exception as e:
        return False, f"Error: {str(e)[:100]}"


def try_doi_fallback(doi: str, dest_path: str) -> tuple[bool, str]:
    """Try to fetch from doi.org redirect."""
    if not doi:
        return False, "No DOI"
    url = f"https://doi.org/{doi}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        final_url = resp.url
        # Check if resolved to a PDF
        if final_url.endswith('.pdf') or 'pdf' in final_url.lower():
            return download_pdf(final_url, dest_path)
        # Try appending /pdf or similar
        for suffix in ['/pdf', '.pdf', '?download=true']:
            pdf_url = final_url.rstrip('/') + suffix
            ok, msg = download_pdf(pdf_url, dest_path)
            if ok:
                return ok, msg
        return False, f"DOI redirected to non-PDF: {final_url[:100]}"
    except Exception as e:
        return False, f"DOI fallback error: {str(e)[:100]}"


def main():
    with open(SEEDS_FILE) as f:
        seeds = json.load(f)

    oa_papers = [(s['paper_id'], s['title'], s.get('oa_url'), s.get('doi'))
                 for s in seeds if s.get('oa_url')]

    logger.info(f"Papers with oa_url: {len(oa_papers)}/71")

    successes = []
    failures = []

    for i, (paper_id, title, oa_url, doi) in enumerate(oa_papers):
        dest_path = os.path.join(PDF_DIR, f"{paper_id}.pdf")

        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 10000:
            logger.info(f"[{i+1}/{len(oa_papers)}] SKIP (exists): {title[:60]}")
            successes.append({'paper_id': paper_id, 'title': title, 'url': oa_url, 'msg': 'cached'})
            continue

        logger.info(f"[{i+1}/{len(oa_papers)}] Fetching: {title[:60]}")
        logger.info(f"  URL: {oa_url[:100]}")

        ok, msg = download_pdf(oa_url, dest_path)

        if not ok and doi:
            logger.info(f"  Primary failed ({msg}), trying DOI fallback...")
            ok, msg = try_doi_fallback(doi, dest_path)
            if ok:
                msg = f"DOI fallback: {msg}"

        if ok:
            successes.append({'paper_id': paper_id, 'title': title, 'url': oa_url, 'msg': msg})
            logger.info(f"  SUCCESS")
        else:
            failures.append({'paper_id': paper_id, 'title': title, 'url': oa_url, 'doi': doi, 'error': msg})
            logger.warning(f"  FAILED: {msg}")

        time.sleep(1.0)  # Polite rate limiting

    logger.info(f"\n=== SUMMARY ===")
    logger.info(f"Success: {len(successes)}/{len(oa_papers)}")
    logger.info(f"Failed:  {len(failures)}/{len(oa_papers)}")

    with open(FAILURES_FILE, 'w') as f:
        json.dump({'failures': failures, 'successes': successes}, f, indent=2, ensure_ascii=False)

    return successes, failures


if __name__ == '__main__':
    main()


# ─────────────────────────────────────────────
# V13 Importable interface (不破坏 __main__)
# ─────────────────────────────────────────────

def fetch_pdfs_for_bottlenecks(
    bottlenecks: list,
    pdf_dir: str = PDF_DIR,
    seeds_file: str = SEEDS_FILE,
) -> dict:
    """
    V13 pilot interface: fetch PDFs for papers in bottleneck clusters.

    Args:
        bottlenecks: list of bottleneck dicts with 'supporting_papers' field
        pdf_dir:     directory to save PDFs
        seeds_file:  optional seeds JSON with oa_url fields

    Returns:
        dict with 'successes', 'failures', 'paper_ids_with_pdfs'
    """
    import os
    os.makedirs(pdf_dir, exist_ok=True)

    # Collect paper_ids from bottlenecks
    paper_ids = []
    for bn in bottlenecks:
        paper_ids.extend(bn.get("supporting_papers", []))
    paper_ids = list(set(paper_ids))

    # Check existing PDFs
    existing = {f[:-4] for f in os.listdir(pdf_dir) if f.endswith(".pdf")}
    new_ids = [pid for pid in paper_ids if pid not in existing]

    logger.info(f"[fetch_pdfs_for_bottlenecks] {len(paper_ids)} papers, {len(existing)} existing, {len(new_ids)} to fetch")

    successes = [pid for pid in paper_ids if pid in existing]
    failures = []

    # Try to load OA URLs from seeds file if available
    oa_urls = {}
    if os.path.exists(seeds_file):
        try:
            with open(seeds_file) as f:
                seeds_data = json.load(f)
            for s in seeds_data:
                if s.get("oa_url"):
                    oa_urls[s.get("paper_id", "")] = s.get("oa_url", "")
        except Exception:
            pass

    for pid in new_ids:
        dest_path = os.path.join(pdf_dir, f"{pid}.pdf")
        oa_url = oa_urls.get(pid)
        if oa_url:
            ok, msg = download_pdf(oa_url, dest_path)
            if ok:
                successes.append(pid)
            else:
                failures.append({"paper_id": pid, "error": msg})
        else:
            failures.append({"paper_id": pid, "error": "no_oa_url"})

    return {
        "total": len(paper_ids),
        "successes": successes,
        "failures": failures,
        "paper_ids_with_pdfs": successes,
    }


def fetch_pdfs_batch(paper_urls: list) -> dict:
    """
    Generic batch PDF fetch.

    Args:
        paper_urls: list of {'paper_id': ..., 'oa_url': ..., 'doi': ...}

    Returns:
        dict with 'successes', 'failures'
    """
    import os
    os.makedirs(PDF_DIR, exist_ok=True)
    successes = []
    failures = []

    for item in paper_urls:
        pid = item.get("paper_id", "")
        oa_url = item.get("oa_url", "")
        doi = item.get("doi", "")
        dest_path = os.path.join(PDF_DIR, f"{pid}.pdf")

        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 10000:
            successes.append(pid)
            continue

        if oa_url:
            ok, msg = download_pdf(oa_url, dest_path)
            if ok:
                successes.append(pid)
                continue
        if doi:
            ok, msg = try_doi_fallback(doi, dest_path)
            if ok:
                successes.append(pid)
                continue

        failures.append({"paper_id": pid, "error": "all_methods_failed"})

    return {"successes": successes, "failures": failures}

#!/usr/bin/env python3
"""
fetch_pdfs_v125.py - Step 2: Download OA PDFs for V12.5 pipeline
Downloads from oa_url, fallback to arxiv search, then doi.org
"""

import json
import os
import time
import requests
import logging
import re

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

SEEDS_FILE = '/home/user/workspace/echelon_mvp0a/reports/v5/llm_seeds_with_resources_v12_5.json'
PDF_DIR = '/home/user/workspace/echelon_mvp0a/scibot/pdfs'
FAILURES_FILE = os.path.join(PDF_DIR, '_failures_v125.json')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; ResearchBot/1.0; +https://research.example.com)',
    'Accept': 'application/pdf,*/*',
    'Accept-Language': 'en-US,en;q=0.9',
}

TIMEOUT = 45
MAX_SIZE_MB = 30

os.makedirs(PDF_DIR, exist_ok=True)


def download_pdf(url: str, dest_path: str) -> tuple:
    """Download a PDF from URL to dest_path. Returns (success, message)."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, stream=True, allow_redirects=True)
        resp.raise_for_status()

        content_type = resp.headers.get('content-type', '').lower()
        # Accept if content-type is PDF or URL contains pdf
        if 'html' in content_type and 'pdf' not in url.lower() and 'pdf' not in content_type:
            # Check if response body starts with PDF magic
            first_chunk = b''
            for chunk in resp.iter_content(chunk_size=256):
                first_chunk = chunk
                break
            if not first_chunk.startswith(b'%PDF-'):
                return False, f"Got HTML instead of PDF (content-type: {content_type})"

        size = 0
        with open(dest_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    size += len(chunk)
                    if size > MAX_SIZE_MB * 1024 * 1024:
                        f.flush()
                        os.remove(dest_path)
                        return False, f"File too large (> {MAX_SIZE_MB}MB)"
                    f.write(chunk)

        if size < 1000:
            os.remove(dest_path)
            return False, f"File too small ({size} bytes)"

        # Verify it's actually a PDF
        with open(dest_path, 'rb') as f:
            header = f.read(5)
        if header != b'%PDF-':
            os.remove(dest_path)
            return False, f"Not a PDF (header: {header})"

        return True, f"OK ({size/1024:.1f}KB)"

    except requests.exceptions.Timeout:
        return False, "Timeout"
    except requests.exceptions.HTTPError as e:
        return False, f"HTTP {e.response.status_code}"
    except requests.exceptions.ConnectionError as e:
        return False, f"Connection error: {str(e)[:80]}"
    except Exception as e:
        return False, f"Error: {str(e)[:80]}"


def try_unpaywall(doi: str, dest_path: str) -> tuple:
    """Try Unpaywall API for open-access PDF."""
    if not doi:
        return False, "No DOI"
    try:
        url = f"https://api.unpaywall.org/v2/{doi}?email=research@example.com"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        
        if data.get('is_oa'):
            # Try best OA location first
            best = data.get('best_oa_location')
            if best and best.get('url_for_pdf'):
                ok, msg = download_pdf(best['url_for_pdf'], dest_path)
                if ok:
                    return ok, f"Unpaywall: {msg}"
            
            # Try all OA locations
            for loc in data.get('oa_locations', []):
                pdf_url = loc.get('url_for_pdf', '')
                if pdf_url:
                    ok, msg = download_pdf(pdf_url, dest_path)
                    if ok:
                        return ok, f"Unpaywall loc: {msg}"
        
        return False, "Unpaywall: no OA PDF"
    except Exception as e:
        return False, f"Unpaywall error: {str(e)[:60]}"


def try_semantic_scholar(doi: str, dest_path: str) -> tuple:
    """Try Semantic Scholar for open PDF."""
    if not doi:
        return False, "No DOI"
    try:
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=openAccessPdf"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        pdf_info = data.get('openAccessPdf', {})
        if pdf_info and pdf_info.get('url'):
            ok, msg = download_pdf(pdf_info['url'], dest_path)
            if ok:
                return ok, f"SemanticScholar: {msg}"
        return False, "SemanticScholar: no OA PDF"
    except Exception as e:
        return False, f"SemanticScholar error: {str(e)[:60]}"


def main():
    with open(SEEDS_FILE) as f:
        seeds = json.load(f)

    logger.info(f"Total papers: {len(seeds)}")
    
    results = []
    failures = []
    success_count = 0
    
    for i, paper in enumerate(seeds):
        pid = paper['paper_id']
        title = paper['title'][:60]
        oa_url = paper.get('oa_url', '')
        doi = paper.get('doi', '')
        
        dest_path = os.path.join(PDF_DIR, f"{pid}.pdf")
        
        # Skip if already downloaded
        if os.path.exists(dest_path):
            logger.info(f"[{i+1}/{len(seeds)}] SKIP (exists): {title}")
            success_count += 1
            results.append({'paper_id': pid, 'status': 'exists', 'title': title})
            continue
        
        logger.info(f"[{i+1}/{len(seeds)}] Trying: {title}")
        
        ok = False
        msg = ""
        method = ""
        
        # Method 1: oa_url
        if oa_url:
            ok, msg = download_pdf(oa_url, dest_path)
            method = "oa_url"
            if ok:
                logger.info(f"  SUCCESS via oa_url: {msg}")
        
        # Method 2: Unpaywall
        if not ok and doi:
            ok, msg = try_unpaywall(doi, dest_path)
            method = "unpaywall"
            if ok:
                logger.info(f"  SUCCESS via Unpaywall: {msg}")
            time.sleep(0.5)
        
        # Method 3: Semantic Scholar
        if not ok and doi:
            ok, msg = try_semantic_scholar(doi, dest_path)
            method = "semantic_scholar"
            if ok:
                logger.info(f"  SUCCESS via SemanticScholar: {msg}")
            time.sleep(0.5)
        
        if ok:
            success_count += 1
            results.append({'paper_id': pid, 'status': 'downloaded', 'method': method, 'title': title})
        else:
            logger.warning(f"  FAILED: {msg}")
            failures.append({'paper_id': pid, 'title': title, 'oa_url': oa_url, 'doi': doi, 'reason': msg})
            results.append({'paper_id': pid, 'status': 'failed', 'reason': msg, 'title': title})
        
        time.sleep(1.0)  # Rate limiting
    
    logger.info(f"\n=== RESULTS ===")
    logger.info(f"Success: {success_count}/{len(seeds)}")
    logger.info(f"Failed: {len(failures)}")
    
    with open(FAILURES_FILE, 'w') as f:
        json.dump(failures, f, indent=2, ensure_ascii=False)
    
    summary = {
        'total': len(seeds),
        'success': success_count,
        'failed': len(failures),
        'results': results
    }
    with open(os.path.join(PDF_DIR, '_summary_v125.json'), 'w') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    
    return success_count, len(failures)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Step 2: CrossRef batch search and scoring.

For each reference, search CrossRef by title and score candidates on 4 dimensions
(title overlap, year, first author, journal). Classify as OK / WARN / FAIL.

Usage:
  python step2_crossref_search.py --input references_extracted.json --output-dir ./output/
  python step2_crossref_search.py --input references_extracted.json --output-dir ./output/ --mailto you@example.com
"""
import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import quote

import requests

CROSSREF_BASE = "https://api.crossref.org/works"
DEFAULT_MAILTO = "reference-verifier@example.com"

STATUS_OK = "OK"
STATUS_WARN = "WARN"
STATUS_FAIL = "FAIL"

# Preprint server DOI patterns (case-insensitive regex)
PREPRINT_DOI_PATTERNS = [
    re.compile(r'^10\.1101/', re.IGNORECASE),     # bioRxiv, medRxiv
    re.compile(r'^10\.21203/', re.IGNORECASE),    # Research Square
    re.compile(r'^10\.31224/', re.IGNORECASE),    # EcoEvoRxiv, etc.
]

def is_preprint_doi(doi):
    """Check if DOI matches known preprint server patterns."""
    if not doi:
        return False
    for pattern in PREPRINT_DOI_PATTERNS:
        if pattern.match(doi):
            return True
    return False


def build_headers(mailto):
    return {
        "User-Agent": f"ReferenceVerifier/1.0 (mailto:{mailto})"
    }


def fix_first_author(ref):
    """Extract family name from 'FirstAuthor AB' format (strip trailing initials)."""
    first_author = ref.get("first_author_full", "")
    if not first_author:
        return ref
    parts = first_author.split()
    if len(parts) == 1:
        ref["first_author_family"] = parts[0]
        return ref
    initials_start = len(parts)
    for i in range(len(parts) - 1, -1, -1):
        if re.match(r'^[A-Z]+$', parts[i]):
            initials_start = i
        else:
            break
    if initials_start > 0:
        ref["first_author_family"] = " ".join(parts[:initials_start])
    return ref


def search_crossref(title, headers):
    query = title.replace(":", " ").replace("/", " ")
    if len(query) > 300:
        query = query[:300]
    url = f"{CROSSREF_BASE}?query={quote(query)}&rows=5&select=DOI,title,author,container-title,issued,type"

    for attempt in range(3):
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("message", {}).get("items", [])
            elif resp.status_code == 429:
                time.sleep(3)
                continue
            else:
                time.sleep(1)
                continue
        except Exception:
            time.sleep(2)
            continue
    return []


def match_reference(items, ref):
    """Score CrossRef candidates against the reference. Returns (status, doi, reason)."""
    title_ref = ref.get("title", "").lower().strip()
    year_ref = ref.get("year")
    author_ref = ref.get("first_author_family", "").lower().strip()
    journal_ref = ref.get("journal", "").lower().strip()

    if not items:
        return STATUS_FAIL, None, "No CrossRef results"

    best_item = None
    best_score = 0
    best_reason = ""

    for item in items:
        score = 0
        reasons = []

        # --- Title overlap (max 40) ---
        item_title = ""
        if isinstance(item.get("title"), list) and item["title"]:
            item_title = item["title"][0]
        item_title = item_title.lower().strip() if item_title else ""

        if title_ref and item_title:
            title_words = set(title_ref.split())
            item_words = set(item_title.split())
            common = title_words & item_words
            if common:
                overlap_ratio = len(common) / max(len(title_words), 1)
                if overlap_ratio > 0.5:
                    score += overlap_ratio * 40
                    reasons.append("title_{:.0f}pct".format(overlap_ratio * 100))

        # --- Year (max 20) ---
        item_year = None
        issued = item.get("issued", {})
        if "date-parts" in issued and issued["date-parts"]:
            item_year = issued["date-parts"][0][0]

        if year_ref and item_year and year_ref == item_year:
            score += 20
            reasons.append("year({})".format(year_ref))
        elif year_ref and item_year and abs(year_ref - item_year) <= 1:
            score += 10
            reasons.append("year~{}".format(item_year))

        # --- First author (max 15) ---
        item_authors = item.get("author", [])
        if item_authors and author_ref:
            for author in item_authors:
                family = author.get("family", "").lower().strip()
                if family == author_ref:
                    score += 15
                    reasons.append("author({})".format(family))
                    break

        # --- Journal (max 10) ---
        container = item.get("container-title", [])
        if container and journal_ref:
            item_journal = container[0].lower().strip() if isinstance(container, list) else str(container).lower()
            jwords = set(journal_ref.replace(".", "").split())
            iwords = set(item_journal.split())
            jcommon = jwords & iwords
            if len(jcommon) >= 2:
                score += 10
                reasons.append("journal")

        if score > best_score:
            best_score = score
            best_item = item
            best_reason = "; ".join(reasons)

    doi = best_item.get("DOI") if best_item else None

    if best_item and best_score >= 40:
        return STATUS_OK, doi, "HIGH({}pts): {}".format(best_score, best_reason)
    elif best_item and best_score >= 20:
        return STATUS_WARN, doi, "MED({}pts): {}".format(best_score, best_reason)
    elif best_item and best_score > 0:
        return STATUS_WARN, doi, "LOW({}pts): {}".format(best_score, best_reason)
    else:
        return STATUS_FAIL, None, "No match found"


def main():
    parser = argparse.ArgumentParser(
        description="Step 2: CrossRef batch search and scoring for extracted references."
    )
    parser.add_argument("--input", "-i", required=True,
                        help="Input JSON from Step 1 (references_extracted.json)")
    parser.add_argument("--output-dir", "-o", default=".",
                        help="Output directory for results (default: current dir)")
    parser.add_argument("--mailto", "-m", default=DEFAULT_MAILTO,
                        help="Email for CrossRef Polite Pool (default: reference-verifier@example.com)")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    headers = build_headers(args.mailto)

    output_json = output_dir / "references_verified.json"
    dois_txt = output_dir / "found_dois.txt"
    flagged_txt = output_dir / "flagged_suspicious.txt"

    with open(input_path, "r", encoding="utf-8") as f:
        references = json.load(f)

    for ref in references:
        fix_first_author(ref)

    verified = []
    found_dois = []
    flagged = []
    total = len(references)

    print("Starting verification of {} references...".format(total), flush=True)

    for idx, ref in enumerate(references):
        num = ref["num"]
        title = ref.get("title", "")
        first_author = ref.get("first_author_family", "")
        year = ref.get("year")

        # --- Fast path: DOI already extracted from source ---
        if ref.get("doi"):
            if is_preprint_doi(ref["doi"]):
                # Preprint DOI detected — skip and mark as excluded
                ref["status"] = STATUS_FAIL
                ref["match_reason"] = "Preprint DOI excluded (fast-path)"
                ref["crossref_items_count"] = 0
                ref["is_preprint"] = True
                verified.append(ref)
                found_dois.append(ref["doi"])
                print("[{}/{}] Ref#{}: EXCLUDED | Preprint DOI: {}".format(
                    idx + 1, total, num, ref["doi"]), flush=True)
                continue
            else:
                ref["status"] = STATUS_OK
                ref["match_reason"] = "DOI from source document"
                ref["crossref_items_count"] = 0
                ref["is_preprint"] = False
                verified.append(ref)
                found_dois.append(ref["doi"])
                print("[{}/{}] Ref#{}: OK | DOI from source: {}".format(
                    idx + 1, total, num, ref["doi"]), flush=True)
                continue

        if not title:
            ref["status"] = STATUS_FAIL
            ref["doi"] = None
            ref["match_reason"] = "No title (parse failed)"
            verified.append(ref)
            flagged.append(ref)
            print("[{}/{}] Ref#{}: FAIL - No title".format(idx + 1, total, num), flush=True)
            continue

        items = search_crossref(title, headers)
        status, doi, reason = match_reference(items, ref)

        ref["status"] = status
        ref["doi"] = doi
        ref["match_reason"] = reason
        ref["crossref_items_count"] = len(items)

        # Post-search preprint check: even CrossRef-matched DOIs may be preprints
        if status == STATUS_OK and doi and is_preprint_doi(doi):
            ref["status"] = STATUS_FAIL
            ref["match_reason"] = "Preprint DOI excluded (search-path)"
            ref["is_preprint"] = True

        verified.append(ref)

        if ref["status"] == STATUS_OK and doi:
            found_dois.append(doi)
        elif ref["status"] == STATUS_FAIL:
            flagged.append(ref)

        print("[{}/{}] Ref#{}: {} | {} | {} | {}".format(
            idx + 1, total, num, status, first_author, year or "?", doi or reason[:60]
        ), flush=True)

        time.sleep(0.5)

    # Write outputs
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(verified, f, ensure_ascii=False, indent=2)

    with open(dois_txt, "w", encoding="utf-8") as f:
        for doi in found_dois:
            f.write(doi + "\n")

    with open(flagged_txt, "w", encoding="utf-8") as f:
        f.write("Potentially fabricated / AI-hallucinated references:\n")
        f.write("=" * 80 + "\n\n")
        for ref in flagged:
            f.write("[{}] {} - {}\n".format(
                ref["num"],
                ref.get("first_author_full", "?"),
                ref.get("title", "?")
            ))
            f.write("    Reason: {}\n".format(ref.get("match_reason", "?")))
            f.write("    Raw: {}\n\n".format(ref.get("raw", "")))

    confirmed = sum(1 for r in verified if r["status"] == STATUS_OK)
    uncertain = sum(1 for r in verified if r["status"] == STATUS_WARN)
    failed = sum(1 for r in verified if r["status"] == STATUS_FAIL)

    print("\n" + "=" * 60, flush=True)
    print("  [OK]   Confirmed:  {}".format(confirmed), flush=True)
    print("  [WARN] Uncertain:  {}".format(uncertain), flush=True)
    print("  [FAIL] Suspected:  {}".format(failed), flush=True)
    print("  DOIs found: {}".format(len(found_dois)), flush=True)
    print("  Output: {}".format(output_json), flush=True)


if __name__ == "__main__":
    main()

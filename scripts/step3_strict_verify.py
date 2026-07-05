#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Step 3: DOI title strict verification.

For each reference with a DOI from Step 2, fetch the real title from CrossRef
and compute similarity. Classify as PASS / WARN / FAIL.

Usage:
  python step3_strict_verify.py --input references_verified.json --output-dir ./output/
  python step3_strict_verify.py --input references_verified.json --output-dir ./output/ --mailto you@example.com
"""
import argparse
import json
import re
import time
from difflib import SequenceMatcher
from pathlib import Path

import requests

DEFAULT_MAILTO = "reference-verifier@example.com"


def build_headers(mailto):
    return {
        "User-Agent": f"ReferenceVerifier/1.0 (mailto:{mailto})"
    }


def normalize_title(t):
    """Normalize title for comparison."""
    t = t.lower()
    t = re.sub(r'[^a-z0-9\s]', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def title_similarity(t1, t2):
    """Calculate weighted title similarity score (0.0 - 1.0)."""
    t1 = normalize_title(t1)
    t2 = normalize_title(t2)

    if not t1 or not t2:
        return 0.0

    # 1. SequenceMatcher (char-level)
    seq_ratio = SequenceMatcher(None, t1, t2).ratio()

    # 2. Word overlap
    w1 = set(t1.split())
    w2 = set(t2.split())
    common = w1 & w2
    w_overlap = len(common) / max(len(w1), 1)

    # 3. First-N-words exact match
    n = min(5, len(t1.split()), len(t2.split()))
    start1 = " ".join(t1.split()[:n])
    start2 = " ".join(t2.split()[:n])
    start_match = 1.0 if start1 == start2 else 0.0

    return seq_ratio * 0.5 + w_overlap * 0.3 + start_match * 0.2


def fetch_doi_info(doi, headers):
    """Fetch real metadata from CrossRef by DOI."""
    url = f"https://api.crossref.org/works/{doi}"
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                msg = resp.json().get("message", {})
                title = msg.get("title", [""])[0] if msg.get("title") else ""
                authors = msg.get("author", [])
                first_author = authors[0].get("family", "") if authors else ""
                container = msg.get("container-title", [""])[0] if msg.get("container-title") else ""
                issued = msg.get("issued", {})
                year = issued.get("date-parts", [[None]])[0][0] if issued.get("date-parts") else None
                item_type = msg.get("type", "")
                return {
                    "title": title,
                    "first_author": first_author,
                    "journal": container,
                    "year": year,
                    "type": item_type,
                }
            elif resp.status_code == 429:
                time.sleep(3)
                continue
            else:
                time.sleep(1)
                continue
        except Exception:
            time.sleep(2)
            continue
    return None


def classify_quality(similarity):
    """Classification based on similarity score."""
    if similarity >= 0.85:
        return "PASS", "Exact or near-exact match"
    elif similarity >= 0.70:
        return "PASS", "Good match (minor diff)"
    elif similarity >= 0.50:
        return "WARN", "Partial match - verify manually"
    elif similarity >= 0.30:
        return "FAIL", "Low similarity - likely wrong paper"
    else:
        return "FAIL", "Different paper"


def main():
    parser = argparse.ArgumentParser(
        description="Step 3: DOI title strict verification via CrossRef."
    )
    parser.add_argument("--input", "-i", required=True,
                        help="Input JSON from Step 2 (references_verified.json)")
    parser.add_argument("--output-dir", "-o", default=".",
                        help="Output directory for results (default: current dir)")
    parser.add_argument("--mailto", "-m", default=DEFAULT_MAILTO,
                        help="Email for CrossRef Polite Pool (default: reference-verifier@example.com)")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    headers = build_headers(args.mailto)

    output_json = output_dir / "references_strict_verified.json"
    dois_txt = output_dir / "found_dois_strict.txt"
    bad_dois_txt = output_dir / "dois_mismatch.txt"

    with open(input_path, "r", encoding="utf-8") as f:
        refs = json.load(f)

    results = []
    pass_count = 0
    warn_count = 0
    fail_count = 0
    no_doi_count = 0
    mismatch_dois = []
    valid_dois = []
    total = len(refs)

    print("Step 3: DOI-title strict verification ({} references)".format(total), flush=True)
    print("=" * 90, flush=True)
    print("{:<5} {:<6} {:<6} {:<48} | {}".format(
        "#", "Result", "Sim", "Ref title (truncated)", "Real title (truncated)"
    ), flush=True)
    print("-" * 90, flush=True)

    for idx, ref in enumerate(refs):
        num = ref["num"]
        doi = ref.get("doi", "")

        if not doi:
            ref["pass2_status"] = "NO_DOI"
            ref["pass2_similarity"] = 0
            ref["pass2_real_title"] = ""
            ref["pass2_real_author"] = ""
            ref["pass2_real_year"] = None
            ref["pass2_note"] = "No DOI from Step 2"
            results.append(ref)
            no_doi_count += 1
            print("[{:<3}] NO_DOI  -     {}".format(
                num, ref.get("title", "?")[:50]
            ), flush=True)
            continue

        info = fetch_doi_info(doi, headers)

        if not info:
            ref["pass2_status"] = "FETCH_ERR"
            ref["pass2_similarity"] = 0
            ref["pass2_real_title"] = ""
            ref["pass2_real_author"] = ""
            ref["pass2_real_year"] = None
            ref["pass2_note"] = "Could not fetch DOI info"
            results.append(ref)
            fail_count += 1
            print("[{:<3}] ERR     -     {}".format(
                num, ref.get("title", "?")[:50]
            ), flush=True)
            continue

        # Compare titles
        ref_title = ref.get("title", "")
        real_title = info["title"]
        sim = title_similarity(ref_title, real_title)
        ref["pass2_similarity"] = round(sim, 3)

        # Check author match
        ref_author = ref.get("first_author_family", "").lower()
        real_author = info["first_author"].lower()
        author_match = ref_author == real_author if ref_author and real_author else False

        # Check journal match
        ref_journal = ref.get("journal", "").lower().replace(".", "")
        real_journal = info["journal"].lower()
        j_common = set(ref_journal.split()) & set(real_journal.split())
        journal_match = len(j_common) >= 2 if ref_journal and real_journal else False

        # Classify
        status, note = classify_quality(sim)

        # Downgrade PASS → WARN if authors don't match
        if status == "PASS" and not author_match:
            status = "WARN"
            note += "; author mismatch ({}/{})".format(ref_author, real_author)

        ref["pass2_status"] = status
        ref["pass2_real_title"] = real_title
        ref["pass2_real_author"] = info["first_author"]
        ref["pass2_real_year"] = info["year"]
        ref["pass2_real_journal"] = info["journal"]
        ref["pass2_real_type"] = info["type"]
        ref["pass2_author_match"] = author_match
        ref["pass2_journal_match"] = journal_match
        ref["pass2_note"] = note

        if status == "PASS":
            pass_count += 1
            valid_dois.append(doi)
        elif status == "WARN":
            warn_count += 1
        elif status == "FAIL":
            fail_count += 1
            mismatch_dois.append({
                "num": num, "doi": doi,
                "ref_title": ref_title, "real_title": real_title,
                "similarity": sim,
            })

        ref_disp = ref_title[:48] if ref_title else "?"
        real_disp = real_title[:48] if real_title else "?"
        print("[{:<3}] {:<6} {:.03f}  {:<48} | {}".format(
            num, status, sim, ref_disp, real_disp
        ), flush=True)

        time.sleep(0.3)
        if (idx + 1) % 10 == 0:
            print("  ... {}/{} done".format(idx + 1, total), flush=True)

    # Write outputs
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    with open(dois_txt, "w", encoding="utf-8") as f:
        for doi in valid_dois:
            f.write(doi + "\n")

    with open(bad_dois_txt, "w", encoding="utf-8") as f:
        f.write("MISMATCHED DOIs (DOI points to different paper):\n")
        f.write("=" * 80 + "\n\n")
        for item in mismatch_dois:
            f.write("[Ref #{}] DOI: {}\n".format(item["num"], item["doi"]))
            f.write("  Reference title: {}\n".format(item["ref_title"][:120]))
            f.write("  Real    title:   {}\n".format(item["real_title"][:120]))
            f.write("  Similarity: {:.3f}\n\n".format(item["similarity"]))

    print("\n" + "=" * 90, flush=True)
    print("  PASS (confirmed):    {}".format(pass_count), flush=True)
    print("  WARN (verify):       {}".format(warn_count), flush=True)
    print("  FAIL (mismatched):   {}".format(fail_count), flush=True)
    print("  NO_DOI (no DOI):     {}".format(no_doi_count), flush=True)
    print("  Valid DOIs:          {}".format(len(valid_dois)), flush=True)
    print("  Mismatched DOIs:     {}".format(len(mismatch_dois)), flush=True)
    print("  Output: {}".format(output_json), flush=True)


if __name__ == "__main__":
    main()

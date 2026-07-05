#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Step 4: Generate RIS with full metadata from CrossRef.

Reads Step 3 output, filters references with pass2_status == "PASS",
fetches complete metadata by DOI, and generates an RIS file.
Also produces a verification_summary.txt recording the final fate of
every reference in the original list.

Usage:
  python step4_generate_ris.py --input references_strict_verified.json --output verified_references.ris
  python step4_generate_ris.py --input references_strict_verified.json --output-dir ./output/
  python step4_generate_ris.py --input references_strict_verified.json --output verified_references.ris --exclude bioRxiv meeting-abstract
"""
import argparse
import json
import re
import time
from pathlib import Path

import requests

DEFAULT_MAILTO = "reference-verifier@example.com"
# Default exclusion keywords (case-insensitive, matched against DOI + title + type)
DEFAULT_EXCLUDE = ["biorxiv", "medrxiv", "meeting abstract", "preprint", "posted-content"]

# Preprint server DOI patterns (case-insensitive regex)
PREPRINT_DOI_PATTERNS = [
    re.compile(r'^10\.11010
            verified.append(ref)
            found_dois.append(ref["doi"])
            print("[{}/{}] Ref#{}: OK | DOI from source: {}".format(
                idx + 1, total, num, ref["doi"]), flush=True)
            continue


def build_headers(mailto):
    return {
        "User-Agent": f"ReferenceVerifier/1.0 (mailto:{mailto})"
    }


def find_exclusion_match(info, exclude_keywords):
    """Return the matched keyword if excluded, else None."""
    combined = " ".join([
        info.get("doi", ""),
        info.get("title", ""),
        info.get("journal", ""),
        info.get("type", ""),
    ]).lower()
    for kw in exclude_keywords:
        if kw.lower() in combined:
            return kw
    return None


def fetch_full_info(doi, headers):
    """Fetch complete metadata from CrossRef by DOI."""
    url = f"https://api.crossref.org/works/{doi}"
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                msg = resp.json().get("message", {})

                title = msg.get("title", [""])[0] if msg.get("title") else ""

                authors = msg.get("author", [])
                author_list = []
                for au in authors:
                    family = au.get("family", "")
                    given = au.get("given", "")
                    if family:
                        author_list.append(f"{family}, {given}" if given else family)

                container = msg.get("container-title", [""])[0] if msg.get("container-title") else ""
                volume = msg.get("volume", "")
                issue = msg.get("issue", "")
                page = msg.get("page", "")

                issued = msg.get("issued", {})
                year = None
                if "date-parts" in issued and issued["date-parts"]:
                    year = issued["date-parts"][0][0]

                publisher = msg.get("publisher", "")
                issn_list = msg.get("ISSN", [])
                issn = issn_list[0] if issn_list else ""
                abstract = msg.get("abstract", "")
                item_type = msg.get("type", "")

                return {
                    "title": title,
                    "authors": author_list,
                    "journal": container,
                    "volume": volume,
                    "issue": issue,
                    "pages": page,
                    "year": year,
                    "doi": doi,
                    "publisher": publisher,
                    "issn": issn,
                    "abstract": abstract[:500] if abstract else "",
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


def gen_ris(info, ref_num):
    """Generate RIS entry from full metadata."""
    lines = []
    lines.append("TY  - JOUR")
    lines.append("TI  - " + info["title"])

    for author in info["authors"]:
        lines.append("AU  - " + author)

    if info["year"]:
        lines.append("PY  - " + str(info["year"]))

    if info["journal"]:
        lines.append("JF  - " + info["journal"])
        lines.append("JO  - " + info["journal"])

    if info["volume"]:
        lines.append("VL  - " + str(info["volume"]))

    if info["issue"]:
        lines.append("IS  - " + str(info["issue"]))

    if info["pages"]:
        pages = str(info["pages"])
        if "-" in pages:
            sp, ep = pages.split("-", 1)
            lines.append("SP  - " + sp.strip())
            lines.append("EP  - " + ep.strip())
        else:
            lines.append("SP  - " + pages)

    lines.append("DO  - " + info["doi"])

    if info["issn"]:
        lines.append("SN  - " + info["issn"])

    if info["publisher"]:
        lines.append("PB  - " + info["publisher"])

    if info["abstract"]:
        lines.append("AB  - " + info["abstract"][:400])

    lines.append("UR  - https://doi.org/" + info["doi"])
    lines.append("N1  - RefVer verified | ref#" + str(ref_num))
    lines.append("ER  - ")
    lines.append("")

    return "\n".join(lines)


def write_summary(output_path, summary_records, counts):
    """Write verification_summary.txt — fate of every reference."""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("Reference Verification Summary\n")
        f.write("=" * 80 + "\n\n")
        f.write("Total references: {}\n".format(counts["total"]))
        f.write("  KEPT (in RIS):      {}\n".format(counts["kept"]))
        f.write("  EXCLUDED (type):    {}\n".format(counts["excluded"]))
        f.write("  WARN (manual check): {}\n".format(counts["warn"]))
        f.write("  FAIL (fabricated):  {}\n".format(counts["fail"]))
        f.write("  NO_DOI:             {}\n".format(counts["no_doi"]))
        f.write("\n" + "-" * 80 + "\n\n")

        for rec in summary_records:
            f.write("[Ref #{:<3}] {:<10}  {}\n".format(
                rec["num"], rec["fate"], rec.get("author", "?")))
            f.write("           Title:  {}\n".format(rec.get("title", "?")[:100]))
            if rec.get("doi"):
                f.write("           DOI:    {}\n".format(rec["doi"]))
            if rec.get("note"):
                f.write("           Note:   {}\n".format(rec["note"]))
            f.write("\n")

    return str(output_path)


def main():
    parser = argparse.ArgumentParser(
        description="Step 4: Generate RIS from verified references with full CrossRef metadata."
    )
    parser.add_argument("--input", "-i", required=True,
                        help="Input JSON from Step 3 (references_strict_verified.json)")
    parser.add_argument("--output", "-o", default=None,
                        help="Output RIS file path (default: verified_references.ris in --output-dir)")
    parser.add_argument("--output-dir", "-d", default=".",
                        help="Output directory (default: current dir)")
    parser.add_argument("--mailto", "-m", default=DEFAULT_MAILTO,
                        help="Email for CrossRef Polite Pool (default: reference-verifier@example.com)")
    parser.add_argument("--exclude", nargs="*", default=DEFAULT_EXCLUDE,
                        help="Keywords to exclude (matched against DOI/title/journal/type). "
                             "Default: biorxiv meeting-abstract preprint")
    parser.add_argument("--include-warn", action="store_true",
                        help="Include WARN references in addition to PASS (default: PASS only)")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = output_dir / "verified_references.ris"

    summary_path = output_dir / "verification_summary.txt"

    headers = build_headers(args.mailto)

    with open(input_path, "r", encoding="utf-8") as f:
        all_refs = json.load(f)

    # Determine which statuses go into the RIS pipeline
    accepted_statuses = {"PASS"}
    if args.include_warn:
        accepted_statuses.add("WARN")

    print("Processing {} references".format(len(all_refs)), flush=True)
    if args.exclude:
        print("Exclusion keywords: {}".format(", ".join(args.exclude)), flush=True)
    print("=" * 60, flush=True)

    entries = []
    summary_records = []
    counts = {"total": len(all_refs), "kept": 0, "excluded": 0,
              "warn": 0, "fail": 0, "no_doi": 0}

    for ref in all_refs:
        num = ref["num"]
        status = ref.get("pass2_status", "")
        doi = ref.get("doi", "")
        author = ref.get("first_author_full", ref.get("first_author_family", "?"))
        title = ref.get("title", "?")
        real_title = ref.get("pass2_real_title", "")
        similarity = ref.get("pass2_similarity", 0)

        # --- Fate determination ---

        # 1. NO_DOI: never got a DOI from earlier steps
        if not doi:
            counts["no_doi"] += 1
            summary_records.append({
                "num": num, "fate": "NO_DOI",
                "author": author, "title": title,
                "note": "No DOI found; could not verify against CrossRef",
            })
            print("[Ref#{}] NO_DOI     | {}".format(num, title[:50]), flush=True)
            continue

        # 2. FAIL: DOI mismatch or very low similarity
        if status == "FAIL":
            counts["fail"] += 1
            note = "DOI title mismatch (similarity: {:.3f})".format(similarity)
            if real_title:
                note += "; real title: {}".format(real_title[:80])
            summary_records.append({
                "num": num, "fate": "FAIL", "doi": doi,
                "author": author, "title": title,
                "note": note,
            })
            print("[Ref#{}] FAIL       | sim={:.3f} | {}".format(
                num, similarity, title[:40]), flush=True)
            continue

        # 3. WARN: partial match, not included unless --include-warn
        if status == "WARN" and not args.include_warn:
            counts["warn"] += 1
            note = ref.get("pass2_note", "Partial match")
            summary_records.append({
                "num": num, "fate": "WARN", "doi": doi,
                "author": author, "title": title,
                "note": note,
            })
            print("[Ref#{}] WARN       | sim={:.3f} | {}".format(
                num, similarity, title[:40]), flush=True)
            continue

        # 4. PASS/WARN candidate: try to fetch CrossRef metadata
        info = fetch_full_info(doi, headers)

        if not info:
            # Fallback: minimal RIS entry
            entries.append(
                "TY  - JOUR\nDO  - {}\nT1  - {}\nA1  - {}\nPY  - {}\nER  - \n".format(
                    doi, title, author, ref.get("year", ""),
                )
            )
            counts["kept"] += 1
            summary_records.append({
                "num": num, "fate": "KEPT", "doi": doi,
                "author": author, "title": title,
                "note": "CrossRef fetch failed; minimal RIS entry with DOI only",
            })
            print("[Ref#{}] KEPT(min)  | {}".format(num, title[:50]), flush=True)
            time.sleep(0.3)
            continue

        # 5. Check exclusion keywords
        matched_kw = find_exclusion_match(info, args.exclude)
        if matched_kw:
            counts["excluded"] += 1
            summary_records.append({
                "num": num, "fate": "EXCLUDED", "doi": doi,
                "author": author, "title": title,
                "note": "Excluded: type='{}', matched keyword '{}'".format(
                    info.get("type", "?"), matched_kw),
            })
            print("[Ref#{}] EXCLUDED   | type={} kw='{}'".format(
                num, info.get("type", "?"), matched_kw), flush=True)
            time.sleep(0.3)
            continue

        # 6. KEPT: full metadata, into RIS
        ris = gen_ris(info, num)
        entries.append(ris)
        counts["kept"] += 1
        summary_records.append({
            "num": num, "fate": "KEPT", "doi": doi,
            "author": author, "title": title,
            "note": "{} authors, V{} I{} P{}".format(
                len(info["authors"]),
                info.get("volume", "?"),
                info.get("issue", "?"),
                info.get("pages", "?"),
            ),
        })
        print("[Ref#{}] KEPT       | {} authors | {}".format(
            num, len(info["authors"]), title[:40]), flush=True)

        time.sleep(0.3)

    # Write RIS
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(entries))

    # Write summary
    write_summary(summary_path, summary_records, counts)

    print("\n" + "=" * 60, flush=True)
    print("  Total:          {}".format(counts["total"]), flush=True)
    print("  KEPT (in RIS):  {}".format(counts["kept"]), flush=True)
    print("  EXCLUDED:       {}".format(counts["excluded"]), flush=True)
    print("  WARN:           {}".format(counts["warn"]), flush=True)
    print("  FAIL:           {}".format(counts["fail"]), flush=True)
    print("  NO_DOI:         {}".format(counts["no_doi"]), flush=True)
    print("  RIS:            {}".format(output_path), flush=True)
    print("  Summary:        {}".format(summary_path), flush=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Cluster the MISSED line numbers of app.py from a coverage term-missing
report into 200-line bands so we can locate the biggest uncovered regions
(fetch/persist/purge blocks + dashboard routes)."""
import re
import sys
from collections import Counter

path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/c65_cov80a.txt"
text = open(path).read()

# Locate the app.py row and CONSUME its continuation lines (the term-missing
# list wraps past the header row) until the next file section header, which
# looks like:  name   stmts  miss  cover%  (4+ columns, cover ends with %).
lines = text.splitlines()
start = next((i for i, ln in enumerate(lines) if ln.split()
              and ln.split()[0] == "app.py"), None)
if start is None:
    print("app.py section not found")
    sys.exit(0)

def _is_section_header(ln):
    toks = ln.split()
    return len(toks) >= 4 and toks[3].endswith("%")

end = start + 1
while end < len(lines) and lines[end].strip() and not _is_section_header(lines[end]):
    end += 1

row = lines[start].split()
stmts, miss, cover = int(row[1]), int(row[2]), row[3]
missed_text = " ".join(tok for ln in lines[start:end] for tok in ln.split()[4:])

# Expand ranges: "3482-3520" means all 39 lines, not just the endpoints.
missed_lines = []
for tok in missed_text.replace(",", " ").split():
    if "-" in tok:
        a, b = tok.split("-")
        try:
            missed_lines.extend(range(int(a), int(b) + 1))
        except ValueError:
            pass
    elif tok.isdigit():
        missed_lines.append(int(tok))

print(f"app.py: {stmts} stmts, {miss} missed, cover {cover}")
print(f"missed lines parsed: {len(missed_lines)}")

# Cluster into 200-line bands.
bands = Counter((ln - 1) // 200 * 200 for ln in missed_lines)
print("\n=== Missed clusters (line band -> count) ===")
for band in sorted(bands):
    bar = "#" * min(40, bands[band])
    print(f"  {band:5d}-{band + 199:<5d} {bands[band]:3d} {bar}")

# Dump the 5 densest bands in full so we can read those regions.
print("\n=== Densest bands (full line lists) ===")
top = sorted(bands, key=bands.get, reverse=True)[:5]
for band in top:
    lines = sorted(ln for ln in missed_lines if band <= ln < band + 200)
    print(f"\n-- band {band}-{band + 199} ({len(lines)} missed) --")
    print(" ".join(str(ln) for ln in lines[:140]))

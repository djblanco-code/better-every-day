#!/usr/bin/env python3
"""Download the open leetcode-problems dataset so Recall can show a problem statement in the session doc.

    python3 scripts/fetch_statements.py

Writes one gitignored file per problem to state/recall-statements/<slug>.json. The dataset is
https://github.com/prathameshakole/leetcode-problems (public GitHub archive, ~1 MB zipped); nothing is
redistributed from this repo. Premium-only problems that are not in the dataset use the short wording in
data/recall-premium-statements.json instead.
"""
import io, json, os, re, sys, urllib.request, zipfile

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(R, 'state', 'recall-statements')
ZIP = 'https://github.com/prathameshakole/leetcode-problems/archive/refs/heads/master.zip'

def main():
    os.makedirs(OUT, exist_ok=True)
    print('downloading', ZIP)
    data = urllib.request.urlopen(urllib.request.Request(ZIP, headers={'User-Agent': 'better-every-day'}), timeout=120).read()
    z = zipfile.ZipFile(io.BytesIO(data)); n = 0
    for name in z.namelist():
        if '/problems/' not in name or not name.endswith('.json'): continue
        try: d = json.loads(z.read(name).decode('utf-8'))
        except Exception: continue
        slug = d.get('problem_slug') or re.sub(r'^\d+-', '', os.path.basename(name)[:-5])
        if not slug: continue
        json.dump(d, open(os.path.join(OUT, slug + '.json'), 'w', encoding='utf-8'))
        n += 1
    print('saved', n, 'statements to', OUT)
    return 0 if n else 1

if __name__ == '__main__': sys.exit(main())

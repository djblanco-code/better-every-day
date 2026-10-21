#!/usr/bin/env python3
"""Pull a company's "last 30 days" LeetCode list into the Recall bank.

    python3 scripts/company_list.py Google
    python3 scripts/company_list.py Google Stripe Citadel

Source: https://github.com/liquidslr/leetcode-company-wise-problems (<Company>/1. Thirty Days.csv).
Problems already in the bank get the company's 30-day frequency and the list tag `company:<Company>`;
problems not in NeetCode 150/250 are added to data/recall-leetcode.json with that tag so they can be
practised. Set "Company focus" in Recall → Settings and the daily LeetCode slot prefers this list.
"""
import csv, io, json, os, sys, urllib.parse, urllib.request

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANK = os.path.join(R, 'data', 'recall-leetcode.json')
RAW = 'https://raw.githubusercontent.com/liquidslr/leetcode-company-wise-problems/main/%s/1.%%20Thirty%%20Days.csv'
# first LeetCode topic tag -> NeetCode roadmap category, so new problems land in the right mastery bucket
TOPIC_MAP = {'Array': 'Arrays & Hashing', 'Hash Table': 'Arrays & Hashing', 'String': 'Arrays & Hashing', 'Sorting': 'Arrays & Hashing',
             'Prefix Sum': 'Arrays & Hashing', 'Matrix': 'Arrays & Hashing', 'Simulation': 'Arrays & Hashing', 'Counting': 'Arrays & Hashing',
             'Two Pointers': 'Two Pointers', 'Sliding Window': 'Sliding Window', 'Stack': 'Stack', 'Monotonic Stack': 'Stack', 'Design': 'Stack',
             'Binary Search': 'Binary Search', 'Linked List': 'Linked List', 'Tree': 'Trees', 'Binary Tree': 'Trees', 'Binary Search Tree': 'Trees',
             'Depth-First Search': 'Trees', 'Breadth-First Search': 'Graphs', 'Heap (Priority Queue)': 'Heap / Priority Queue', 'Backtracking': 'Backtracking',
             'Trie': 'Tries', 'Graph': 'Graphs', 'Union Find': 'Graphs', 'Topological Sort': 'Advanced Graphs', 'Shortest Path': 'Advanced Graphs',
             'Dynamic Programming': '1-D Dynamic Programming', 'Memoization': '1-D Dynamic Programming', 'Greedy': 'Greedy', 'Interval': 'Intervals',
             'Line Sweep': 'Intervals', 'Math': 'Math & Geometry', 'Geometry': 'Math & Geometry', 'Bit Manipulation': 'Bit Manipulation'}

def pull(company, d):
    url = RAW % urllib.parse.quote(company)
    txt = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'better-every-day'}), timeout=60).read().decode('utf-8')
    rows = list(csv.DictReader(io.StringIO(txt)))
    by_slug = {p['slug']: p for p in d['problems']}
    order, added, tagged = [], 0, 0
    tag = 'company:' + company
    for r in rows:
        slug = r['Link'].rstrip('/').split('/')[-1]
        if not slug: continue
        try: freq = float(r.get('Frequency') or 0)
        except ValueError: freq = 0
        topics = [t.strip() for t in (r.get('Topics') or '').split(',') if t.strip()]
        p = by_slug.get(slug)
        if not p:
            cat = next((TOPIC_MAP[t] for t in topics if t in TOPIC_MAP), '')
            p = {'slug': slug, 'title': r['Title'], 'difficulty': (r.get('Difficulty') or '').title(), 'topics': topics,
                 'url': 'https://leetcode.com/problems/%s/' % slug, 'lists': [], 'category': cat, 'companies': {}}
            d['problems'].append(p); by_slug[slug] = p; added += 1
        if tag not in p.setdefault('lists', []): p['lists'].append(tag); tagged += 1
        p.setdefault('companies', {}).setdefault(company, {})['30d'] = freq
        order.append(slug)
    d.setdefault('company_lists', {})[company] = order
    if company not in d.setdefault('companies', []): d['companies'].append(company); d['companies'].sort()
    return len(rows), added, tagged

def main(names):
    if not names: print(__doc__); return 2
    d = json.load(open(BANK, encoding='utf-8'))
    for c in names:
        n, added, tagged = pull(c, d)
        print('%s: %d problems in the 30-day list, %d new in the bank, %d tagged' % (c, n, added, tagged))
    tmp = BANK + '.tmp'; json.dump(d, open(tmp, 'w', encoding='utf-8'), indent=0); os.replace(tmp, BANK)
    return 0

if __name__ == '__main__': sys.exit(main(sys.argv[1:]))

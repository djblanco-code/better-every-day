#!/usr/bin/env python3
"""Lead pool: every job lead scripts/collect.py finds lives in state/pool.json until it is applied to,
routed to the user, skipped, or closed. A run that dies (usage limit, crash) loses nothing: the leads it did
not reach are still here for the next run. The agent never searches; it takes leads from here.

    python3 scripts/pool.py take                         # CLAIM the next lead (marks it working): use this to get work
    python3 scripts/pool.py next [N]                     # preview only; never claims
    python3 scripts/pool.py show <id>                    # one lead in full (description trimmed)
    python3 scripts/pool.py mark <id> <status> [note]    # applied | closed | skipped | needs_human | ready
    python3 scripts/pool.py stats                        # counts by status

Ready leads already passed the gate in collect.py (title, level, location, years, pay floor, skip list,
duplicates, known-blocked Greenhouse questions). The agent still verifies the posting is live, runs
./scripts/dupe_check.sh, and reads the posting before filling anything.
"""
import json, os, re, sys, time, datetime, contextlib

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POOL = os.path.join(R, 'state', 'pool.json')
TRACKER = os.path.join(R, 'logs', 'job-tracker.md')
UTC = datetime.timezone.utc
STATUSES = ('new', 'ready', 'working', 'applied', 'blocked', 'needs_human', 'skipped', 'closed', 'stale')
WORKING_MINUTES = 60   # a lead taken but never marked goes back to ready after this (crashed run)
LOCKDIR = os.path.join(R, 'state', '.pool.lock')

def now(): return datetime.datetime.now(UTC)
def today(): return datetime.datetime.now().strftime('%Y-%m-%d')  # local date, as the tracker uses

def settings():
    with open(os.path.join(R, 'config', 'settings.json'), encoding='utf-8') as f: return json.load(f)

def load():
    try:
        with open(POOL, encoding='utf-8') as f: return json.load(f)
    except (OSError, ValueError): return {}

@contextlib.contextmanager
def locked(timeout=60):
    """Cross-process lock for read-modify-write of the pool (hourly run + interactive session + collector)."""
    t0 = time.time()
    while True:
        try: os.makedirs(LOCKDIR); break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(LOCKDIR) > 120: os.rmdir(LOCKDIR); continue  # stale
            except OSError: pass
            if time.time() - t0 > timeout: raise SystemExit('pool is locked by another process')
            time.sleep(0.2)
    try: yield
    finally:
        try: os.rmdir(LOCKDIR)
        except OSError: pass

def save(pool):
    os.makedirs(os.path.dirname(POOL), exist_ok=True)
    tmp = POOL + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f: json.dump(pool, f, ensure_ascii=False, indent=0)
    os.replace(tmp, POOL)  # atomic: a crash mid-write never corrupts the pool

def norm(c): return re.sub(r'[^a-z0-9]', '', (c or '').lower())

def same_company(a, b):
    a, b = norm(a), norm(b)
    if not a or not b: return False
    short = min(a, b, key=len)
    return a == b or (len(short) >= 4 and (a.startswith(b) or b.startswith(a)))

# ---- what has already been sent: logs/job-tracker.md is the user's single list ----------------------------
def tracker_rows():
    """Yields (section, cells) for every data row of the two tracker tables."""
    try: text = open(TRACKER, encoding='utf-8').read()
    except OSError: return
    section = None
    for line in text.splitlines():
        if line.startswith('## Applied by the agent'): section = 'agent'
        elif line.startswith('## Apply yourself'): section = 'you'
        elif line.startswith('## '): section = None
        elif section and line.startswith('|') and not line.startswith('|---'):
            cells = [c.strip() for c in line.strip().strip('|').split('|')]
            if cells and not cells[0].lower().startswith('date'): yield section, cells

def applications():
    """[(company, date, url)] for every real application: agent submits plus rows marked 'Applied by me'."""
    out = []
    for section, c in tracker_rows():
        if section == 'agent' and len(c) >= 6:
            out.append((c[1], c[0], c[5]))
        elif section == 'you' and len(c) >= 9 and c[-1].lower().startswith('applied by me'):
            m = re.search(r'\d{4}-\d\d-\d\d', c[-1])
            out.append((c[1], m.group(0) if m else c[0], c[5]))
    return out

def tracker_urls():
    """URLs already applied to (agent submits + rows the user marked 'Applied by me'). Open 'Apply yourself'
    rows are NOT here: a lead whose blocker has since been removed must be able to become ready again."""
    out = set()
    for sec, c in tracker_rows():
        if len(c) < 6: continue
        if sec == 'agent' or (sec == 'you' and c[-1].lower().startswith('applied by me')): out.add(c[5])
    return out

def company_counts(apps=None):
    apps = applications() if apps is None else apps
    def count(company): return sum(1 for a in apps if same_company(a[0], company))
    def today_hit(company): return any(same_company(a[0], company) and a[1] == today() for a in apps)
    return count, today_hit

# ---- commands --------------------------------------------------------------------------------------------
def sort_key(l):
    """Higher sorts first (callers use reverse=True): postings under 3 days old, then under 8, then older; within a
    bucket the best fit first. Fresh beats fit; fit beats mere recency inside the same bucket."""
    d = (l.get('posted') or l.get('found') or '')[:10]
    try: age = (now().date() - datetime.date.fromisoformat(d)).days
    except ValueError: age = 99
    bucket = 0 if age < 3 else 1 if age < 8 else 2
    return (-bucket, l.get('fit', 50), d)

def line(l):
    bits = [l['id'], l.get('company', '?'), l.get('title', '?'), l.get('location', '') or '?',
            l.get('band') or 'pay not posted', 'posted ' + (l.get('posted') or '?')[:10], f"fit {l.get('fit', '?')}"]
    if l.get('years_min') is not None: bits.append(f"{l['years_min']}+ yrs")
    if l.get('note'): bits.append(l['note'])
    bits.append(l.get('url', ''))
    return ' | '.join(str(b) for b in bits)

def fresh(l):
    """True while a working claim is recent enough to be a live run."""
    try: return (now() - datetime.datetime.fromisoformat(l.get('updated', '') + ':00+00:00')).total_seconds() < WORKING_MINUTES * 60
    except ValueError: return False

def cmd_take():
    """Atomically claim the next ready lead so a second session or the hourly run never takes the same one."""
    s = settings(); cap = s.get('run', {}).get('max_applications_per_company_lifetime', 2)
    freeze = s.get('run', {}).get('same_day_company_freeze', True)
    with locked():
        pool = load(); count, today_hit = company_counts()
        busy = [l.get('company', '') for l in pool.values() if l.get('status') == 'working' and fresh(l)]
        for l in sorted((l for l in pool.values() if l.get('status') == 'ready' or (l.get('status') == 'working' and not fresh(l))),
                        key=sort_key, reverse=True):
            co = l.get('company', '')
            if any(same_company(co, x) for x in busy): continue
            if count(co) >= cap or (freeze and today_hit(co)): continue
            l['status'] = 'working'; l['updated'] = now().isoformat()[:16]
            save(pool); print('CLAIMED ' + line(l)); return
    print('NO READY LEADS right now. If you have not run the collector in the last 20 minutes, run `python3 scripts/collect.py` once (foreground, Bash timeout 1500000), then `take` again. If it still says NO READY LEADS, you are done for now.')

def cmd_next(n):
    s = settings(); cap = s.get('run', {}).get('max_applications_per_company_lifetime', 2)
    freeze = s.get('run', {}).get('same_day_company_freeze', True)
    pool = load(); count, today_hit = company_counts()
    shown, seen = [], [l.get('company', '') for l in pool.values() if l.get('status') == 'working' and fresh(l)]
    for l in sorted((l for l in pool.values() if l.get('status') == 'ready' or (l.get('status') == 'working' and not fresh(l))), key=sort_key, reverse=True):
        co = l.get('company', '')
        if any(same_company(co, x) for x in seen): continue
        if count(co) >= cap or (freeze and today_hit(co)): continue
        seen.append(co); shown.append(l)
        if len(shown) >= n: break
    ready = sum(1 for l in pool.values() if l.get('status') == 'ready')
    print(f'{ready} ready leads in the pool; next {len(shown)} (newest first, one per company, caps applied):')
    for l in shown: print(line(l))

def cmd_show(i):
    l = load().get(i)
    if not l: sys.exit(f'no lead {i}')
    d = dict(l); d['desc'] = (d.get('desc') or '')[:3000]
    print(json.dumps(d, indent=1, ensure_ascii=False))

def cmd_mark(i, status, note=''):
    if status not in STATUSES: sys.exit(f'status must be one of {STATUSES}')
    with locked():
        pool = load()
        if i not in pool: sys.exit(f'no lead {i}')
        l = pool[i]; l['status'] = status; l['updated'] = now().isoformat()[:16]
        if note: l['note'] = note
        if status == 'applied': l['applied'] = today()
        save(pool)
    print(f'{i} -> {status}')

def cmd_stats():
    pool = load(); c = {}
    for l in pool.values(): c[l.get('status', '?')] = c.get(l.get('status', '?'), 0) + 1
    print(f'{len(pool)} leads: ' + ', '.join(f'{k} {v}' for k, v in sorted(c.items(), key=lambda x: -x[1])))

if __name__ == '__main__':
    a = sys.argv[1:]
    if not a or a[0] == 'stats': cmd_stats()
    elif a[0] == 'take': cmd_take()
    elif a[0] == 'next': cmd_next(int(a[1]) if len(a) > 1 else 10)
    elif a[0] == 'show' and len(a) > 1: cmd_show(a[1])
    elif a[0] == 'mark' and len(a) > 2: cmd_mark(a[1], a[2], ' '.join(a[3:]))
    else: print(__doc__)

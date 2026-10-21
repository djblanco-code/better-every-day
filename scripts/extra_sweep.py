#!/usr/bin/env python3
"""Extra sweep: sources the other sweeps do not read. No login, no Claude usage.

    python3 scripts/extra_sweep.py                 # since state/last_extra_sweep.txt (default: 10 days), then advance it
    python3 scripts/extra_sweep.py --since 2026-10-01T00:00Z
    python3 scripts/extra_sweep.py --dry           # do not advance the cutoff or write slugs

1. Getro VC/accelerator boards (Accel, General Catalyst, Khosla, Insight, Greycroft, Menlo, Thrive, Lux, ...)
   through api.getro.com. The network id is read from each board's own /jobs page.
2. Hacker News "Who is hiring?" (latest thread): every posting that names a target city or remote and an
   engineering role becomes a lead; every ATS link feeds the slug lists below.
3. ATS boards the older sweeps do not read natively: Gem, Workable, Breezy, Rippling, SmartRecruiters.
   Slugs come from data/extra-slugs.json, which grows from every URL the pool, the HN thread and Getro have seen.
Output: state/sweep/extra_cands.json, rows [source, company, posted, title, location, band, url, desc].
collect.py gates them (title, location, years, pay) exactly like every other lead.
"""
import json, os, re, sys, time, ssl, datetime, html, urllib.request, urllib.parse, concurrent.futures as cf

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(R, 'state', 'sweep', 'extra_cands.json')
STAMP = os.path.join(R, 'state', 'last_extra_sweep.txt')
SLUGFILE = os.path.join(R, 'data', 'extra-slugs.json')
CAND = os.path.join(R, 'data', 'slug-candidates.txt')
UTC = datetime.timezone.utc
START = datetime.datetime.now(UTC)
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36'
CTX = ssl.create_default_context()
DRY = '--dry' in sys.argv

def arg(name):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None

def parse_ts(s):
    try: return datetime.datetime.fromisoformat(s.replace('Z', '+00:00')).astimezone(UTC)
    except Exception: return None

if arg('--since'): CUT = parse_ts(arg('--since'))
else:
    try: CUT = parse_ts(open(STAMP).read().strip())
    except Exception: CUT = None
if not CUT: CUT = START - datetime.timedelta(days=10)

S = json.load(open(os.path.join(R, 'config', 'settings.json')))
LOCS = [l.lower() for l in S['targets'].get('locations', [])]
CITY = re.compile(r'new york|\bnyc\b|brooklyn|manhattan|chicago|remote|united states|\busa?\b|anywhere|north america', re.I)
ROLE = re.compile(r'engineer|developer|\bsre\b|devops|software|programmer|full.?stack|backend|back-end|infrastructure|platform', re.I)
SKIP = re.compile(r'senior|\bsr\b|staff|principal|\blead\b|manager|director|head of|vice president|intern\b|sales|recruit|marketing|designer|counsel|account exec|support', re.I)

def req(url, data=None, headers=None, timeout=25):
    h = {'User-Agent': UA, **(headers or {})}
    body = None
    if data is not None:
        body = json.dumps(data).encode(); h.setdefault('Content-Type', 'application/json')
    r = urllib.request.Request(url, data=body, headers=h)
    with urllib.request.urlopen(r, timeout=timeout, context=CTX) as x:
        return x.read().decode('utf-8', 'replace')

def jget(url, data=None, headers=None):
    try: return json.loads(req(url, data, headers))
    except Exception: return None

rows = []
def add(source, company, posted, title, loc, band, url, desc=''):
    if not title or not url or not ROLE.search(title) or SKIP.search(title): return
    rows.append([source, company or '', (posted or '')[:10], title.strip(), (loc or '')[:90], band or '', url.split('#')[0], (desc or '')[:6000]])

# ---------------------------------------------------------------- slug store
try: STORE = json.load(open(SLUGFILE))
except Exception: STORE = {}
for k in ('gem', 'workable', 'breezy', 'rippling', 'smartrecruiters'): STORE.setdefault(k, [])
URLPAT = {
    'gem': re.compile(r'jobs\.gem\.com/([A-Za-z0-9._-]+)'),
    'workable': re.compile(r'apply\.workable\.com/(?!j/)([A-Za-z0-9._-]+)'),
    'breezy': re.compile(r'https?://([A-Za-z0-9-]+)\.breezy\.hr'),
    'rippling': re.compile(r'ats\.rippling\.com/([A-Za-z0-9._-]+)'),
    'smartrecruiters': re.compile(r'(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9._-]+)'),
}
GH_ASH_LEVER = re.compile(r'(?:job-boards|boards)(?:\.eu)?\.greenhouse\.io/([A-Za-z0-9_-]+)|jobs\.ashbyhq\.com/([A-Za-z0-9._-]+)|jobs\.lever\.co/([A-Za-z0-9._-]+)')
new_core = set()
def harvest(url):
    for k, p in URLPAT.items():
        m = p.search(url or '')
        if m and m.group(1).lower() not in ('embed', 'j', 'api'):
            s = m.group(1)
            if s not in STORE[k]: STORE[k].append(s)
    m = GH_ASH_LEVER.search(url or '')
    if m: new_core.add(next(g for g in m.groups() if g))

# 0. the pool's own URLs seed the stores (workable job pages carry only a shortcode, so those are skipped)
try:
    d = json.load(open(os.path.join(R, 'state', 'pool.json'), encoding='utf-8'))
    L = d.get('leads', d); L = L.values() if isinstance(L, dict) else L
    for v in L: harvest(v.get('url', ''))
except Exception: pass

# ---------------------------------------------------------------- 1. Getro boards
GETRO = ['jobs.accel.com', 'jobs.generalcatalyst.com', 'jobs.khoslaventures.com', 'jobs.insightpartners.com',
         'jobs.greycroft.com', 'jobs.menlovc.com', 'jobs.thrivecap.com', 'jobs.luxcapital.com']
GETRO_Q = ['software engineer', 'backend engineer', 'full stack engineer', 'infrastructure engineer',
           'forward deployed engineer', 'site reliability engineer', 'devops engineer', 'platform engineer']
def getro(host):
    n = 0
    try: page = req(f'https://{host}/jobs')
    except Exception: print(f'  ! getro {host}: page failed', file=sys.stderr); return 0
    m = re.search(r'"network_?[iI]d"\s*:\s*"?(\d+)', page)
    if not m: print(f'  ! getro {host}: no network id', file=sys.stderr); return 0
    nid = m.group(1); seen = set()
    hdr = {'Accept': 'application/json', 'Origin': f'https://{host}', 'Referer': f'https://{host}/jobs'}
    for q in GETRO_Q:
        for pg in range(4):
            d = jget(f'https://api.getro.com/api/v2/collections/{nid}/search/jobs',
                     {'hits_per_page': 100, 'page': pg, 'query': q, 'filters': {}}, hdr)
            jobs = ((d or {}).get('results') or {}).get('jobs') or []
            if not jobs: break
            for j in jobs:
                ts = datetime.datetime.fromtimestamp(j.get('created_at', 0), UTC)
                url = j.get('url') or ''
                if ts < CUT or url in seen: continue
                seen.add(url)
                locs = '; '.join(j.get('searchable_locations') or [])
                if j.get('work_mode') == 'remote' and not re.search(r'United States|USA', locs): locs += '; Remote'
                mx, mn = j.get('compensation_amount_max_cents'), j.get('compensation_amount_min_cents')
                band = f'${(mn or 0) // 100000}K-${mx // 100000}K' if mx else ''
                co = (j.get('organization') or {}).get('name', '')
                if not CITY.search(locs): continue
                harvest(url); add('getro:' + host.split('.')[1], co, ts.isoformat(), j.get('title'), locs, band, url); n += 1
            time.sleep(0.3)
    return n

# ---------------------------------------------------------------- 2. Hacker News
def hn():
    d = jget('https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&hitsPerPage=3&query=hiring')
    th = next((h for h in (d or {}).get('hits', []) if 'who is hiring' in (h.get('title') or '').lower()), None)
    if not th: print('  ! hn: no thread', file=sys.stderr); return 0
    t = jget(f"https://hn.algolia.com/api/v1/items/{th['objectID']}") or {}
    n = 0
    for c in t.get('children', []):
        raw = c.get('text') or ''
        txt = html.unescape(re.sub(r'<[^>]+>', ' ', re.sub(r'<p>', '\n', raw))).strip()
        urls = re.findall(r'https?://[^\s"<>)]+', html.unescape(raw))
        for u in urls: harvest(u)
        head = txt.split('\n')[0][:200]
        if not (ROLE.search(txt) and CITY.search(head + ' ' + txt[:400])) or re.search(r'\bonsite only\b|\bno remote\b', txt[:300], re.I): continue
        if not re.search(r'new york|\bnyc\b|chicago|remote|\bus\b|united states', txt[:600], re.I): continue
        apply = next((u for u in urls if re.search(r'greenhouse|ashby|lever|workable|gem\.com|breezy|rippling|smartrecruiters|careers|jobs', u, re.I)), urls[0] if urls else '')
        if not apply: continue
        co = re.split(r'\s*[|–—-]\s*', head)[0].strip()[:60]
        title = next((p.strip() for p in re.split(r'\s*\|\s*', head) if ROLE.search(p)), 'Software Engineer')[:90]
        add('hn', co, datetime.datetime.fromtimestamp(c.get('created_at_i', 0), UTC).isoformat(), title, head, '', apply, txt); n += 1
    return n

# ---------------------------------------------------------------- 3. ATS boards
def band_of(lo, hi):
    return f'${int(lo) // 1000}K-${int(hi) // 1000}K' if lo and hi else ''

def gem(slug):
    d = jget(f'https://api.gem.com/job_board/v0/{slug}/job_posts/') or []
    out = []
    for j in d:
        ts = parse_ts(j.get('first_published_at') or j.get('updated_at') or '') or START
        if ts < CUT: continue
        loc = (j.get('location') or {}).get('name', '') if isinstance(j.get('location'), dict) else str(j.get('location') or '')
        remote = j.get('location_type') == 'remote' or 'remote' in loc.lower()
        out.append(('gem', slug, ts.isoformat(), j.get('title'), loc + ('; Remote (US)' if remote and 'remote' not in loc.lower() else ''), '', j.get('absolute_url'),
                    re.sub(r'<[^>]+>', ' ', html.unescape(j.get('content') or ''))))
    return out

def workable(slug):
    out, token = [], None
    for _ in range(4):
        d = jget(f'https://apply.workable.com/api/v3/accounts/{slug}/jobs', {'query': '', 'location': [], 'department': [], 'worktype': [], 'remote': [], **({'token': token} if token else {})})
        if not d: break
        for j in d.get('results', []):
            ts = parse_ts(j.get('published') or '') or START
            if ts < CUT: continue
            l = j.get('location') or {}
            loc = ', '.join(x for x in (l.get('city'), l.get('region'), l.get('country')) if x) + ('; Remote (US)' if j.get('remote') and l.get('countryCode') == 'US' else '')
            out.append(('workable', slug, ts.isoformat(), j.get('title'), loc, '', f"https://apply.workable.com/j/{j['shortcode']}", ''))
        token = d.get('nextPage')
        if not token: break
    return out

def breezy(slug):
    out = []
    for j in jget(f'https://{slug}.breezy.hr/json') or []:
        ts = parse_ts(j.get('published_date') or '') or START
        if ts < CUT: continue
        l = j.get('location') or {}
        loc = l.get('name') or ', '.join(x for x in (l.get('city'), (l.get('state') or {}).get('name')) if x)
        if l.get('is_remote'): loc += '; Remote (US)' if (l.get('country') or {}).get('id') in ('US', None) else '; Remote'
        sal = j.get('salary') or ''
        out.append(('breezy', j.get('company', {}).get('name') or slug, ts.isoformat(), j.get('name'), loc, sal if isinstance(sal, str) else '', j.get('url'), ''))
    return out

def rippling(slug):
    out = []
    for pg in range(5):
        d = jget(f'https://ats.rippling.com/api/v2/board/{slug}/jobs?page={pg}&pageSize=50')
        items = (d or {}).get('items') or []
        if not items: break
        for j in items:
            locs = '; '.join(x.get('name', '') for x in (j.get('locations') or []))
            out.append(('rippling', slug, '', j.get('name'), locs, '', j.get('url'), ''))
        if len(items) < 50: break
    return out

def smartrec(slug):
    out = []
    for off in range(0, 300, 100):
        d = jget(f'https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset={off}')
        items = (d or {}).get('content') or []
        if not items: break
        for j in items:
            ts = parse_ts(j.get('releasedDate') or '') or START
            if ts < CUT: continue
            l = j.get('location') or {}
            loc = ', '.join(x for x in (l.get('city'), l.get('region'), (l.get('country') or '').upper()) if x) + ('; Remote (US)' if l.get('remote') else '')
            out.append(('smartrecruiters', (j.get('company') or {}).get('name') or slug, ts.isoformat(), j.get('name'), loc, '', f"https://jobs.smartrecruiters.com/{slug}/{j.get('id')}", ''))
        if len(items) < 100: break
    return out

FETCH = {'gem': gem, 'workable': workable, 'breezy': breezy, 'rippling': rippling, 'smartrecruiters': smartrec}

def main():
    t0 = time.time(); counts = {}
    with cf.ThreadPoolExecutor(4) as ex:
        for host, n in zip(GETRO, ex.map(getro, GETRO)): counts['getro:' + host] = n
    counts['hn'] = hn()
    jobs = [(k, s) for k in FETCH for s in sorted(set(STORE[k]))]
    def run(ks):
        k, s = ks
        try: return k, FETCH[k](s)
        except Exception: return k, []
    with cf.ThreadPoolExecutor(8) as ex:
        for k, res in ex.map(run, jobs):
            for r in res:
                if CITY.search(r[4] or 'remote') or not r[4]:
                    add(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]); counts[k] = counts.get(k, 0) + 1
    seen, uniq = set(), []
    for r in sorted(rows, key=lambda r: r[2], reverse=True):
        key = r[6].split('?')[0].rstrip('/').lower()
        if key in seen: continue
        seen.add(key); uniq.append(r)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(uniq, open(OUT, 'w'))
    known = set()
    try: known = set(re.findall(r'[A-Za-z0-9._-]+', open(CAND).read()))
    except Exception: pass
    fresh = sorted(s for s in new_core if s not in known)
    print(f'extra sweep: cutoff {CUT.isoformat()[:16]}Z  candidates {len(uniq)}  boards polled {len(jobs)}  new GH/Ashby/Lever slugs {len(fresh)}  {time.time()-t0:.0f}s')
    print('  by source:', json.dumps(counts))
    if not DRY:
        if fresh:
            with open(CAND, 'a') as f: f.write('\n'.join(fresh) + '\n')
        json.dump(STORE, open(SLUGFILE, 'w'), indent=0)
        open(STAMP, 'w').write(START.isoformat(timespec='minutes').replace('+00:00', 'Z') + '\n')

main()

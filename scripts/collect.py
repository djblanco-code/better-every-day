#!/usr/bin/env python3
"""Collector: find, vet and save every job lead WITHOUT using Claude. run.sh runs it before each session, so
the agent spends its usage on filling forms only.

    python3 scripts/collect.py                 # sweeps since their last cutoffs + JobDataLake, then vet
    python3 scripts/collect.py --backfill 21   # one-off: look back 21 days on every source
    python3 scripts/collect.py --vet-only      # no searching; re-vet what is already in the pool

What it does, in order:
 1. Runs delta_sweep.py (company ATS boards), list_sweep.py (VC portfolio boards) and portal_sweep.py
    (big-company career sites), and queries JobDataLake over HTTP. GrepJob needs the user's login, so it
    stays inside Claude sessions.
 2. Saves every lead to state/pool.json FIRST. A sweep's cutoff only matters for what it prints next time;
    nothing it printed is lost, because the pool keeps it until it is applied to or ruled out.
 3. Vets new leads from public APIs: full description (years required, pay band), liveness, and for
    Greenhouse the form's required questions. Leads behind an account wall, a required demographic
    self-ID section, or a required question with no fact on file go straight to logs/job-tracker.md
    under "Apply yourself" without ever opening a browser.
 4. Gates the rest on config/settings.json (title, level, location, years, pay floor, skip list) and
    marks them ready. The agent takes them with `python3 scripts/pool.py next`.
Output: a short summary on stdout; details in logs/collector.log.
"""
import html, json, os, re, ssl, subprocess, sys, time, datetime, urllib.error, urllib.parse, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pool as P
import fit as FIT

R, UTC = P.R, P.UTC
LOG = os.path.join(R, 'logs', 'collector.log')
LOCK = os.path.join(R, 'state', '.collect.lock')
ARGS = sys.argv[1:]
BACKFILL = int(ARGS[ARGS.index('--backfill') + 1]) if '--backfill' in ARGS else 0
VET_ONLY = '--vet-only' in ARGS
START = P.now()

S = P.settings()
T, RUN = S.get('targets', {}), S.get('run', {})
C = S.get('collector', {})
FLOOR = T.get('min_annual_comp_usd', 0) or 0
MAX_YEARS = T.get('max_years_experience_required', 99)
SEN = [x.lower() for x in T.get('seniority', [])]
SKIP_COS = T.get('skip_companies', [])
SIGNED = set(S.get('channels', {}).get('signed_in_portals', []))

def log(*a):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f: f.write(' '.join(str(x) for x in a) + '\n')

# ---- gate pieces -------------------------------------------------------------------------------------------
TIT = re.compile(r'engineer|developer|technical staff|\bmts\b|\bswe\b|programmer|\bsde\b', re.I)
BAD = re.compile(r'senior|\bsr\b|\bsr\.|principal|\blead\b|manager|director|head of|\bvp\b|architect|recruit|sales'
                 r'|account exec|designer|marketing|counsel|legal|finance|\bstaff\b|\biii\b|\biv\b|\bv\b'
                 r'|solutions engineer|support engineer|customer success', re.I)
WANT_NEWGRAD, WANT_INTERN = 'new-grad' in SEN, 'internship' in SEN
NOT_WANTED = re.compile('|'.join(([] if WANT_INTERN else [r'\bintern', r'co-?op\b']) +
                                 ([] if WANT_NEWGRAD else [r'new ?grad', r'new college', r'university', r'campus',
                                                           r'graduate\b'])) or r'(?!x)x', re.I)
SOFT_TITLE = re.compile(r'software|developer|\bswe\b|\bsde\b|back.?end|front.?end|full.?stack|platform|infrastructure|\bsre\b|devops|reliability'
                        r'|data engineer|machine learning|\bml\b|\bai\b|forward.?deployed|technical staff|\bmts\b|systems|cloud|security engineer'
                        r'|product engineer|in test|\bsdet\b|distributed|programmer|\bapi\b|web|application engineer', re.I)
NON_SOFTWARE = re.compile(r'equipment|process engineer|manufactur|chemical|civil|structural|mechatronic|field (service )?engineer|\bworkday\b|netsuite|servicenow|salesforce (admin|developer)|\bsap\b', re.I)
TITLE_EXCLUDE = re.compile(C.get('title_exclude') or r'(?!x)x', re.I)
# Google's "Software Engineer III" is its ~2-year level; let the years check decide those.
III_OK = re.compile(r'google', re.I)

LOC_PAT = {'New York': r'new york|\bnyc\b|brooklyn|manhattan|\bNY\b', 'Chicago': r'chicago|\bIL\b',
           'Seattle': r'seattle|bellevue|redmond|kirkland', 'Remote (US)': r'remote|anywhere|distributed|virtual',
           'San Francisco Bay Area': r'san francisco|\bsf\b|bay area|palo alto|mountain view|sunnyvale|san jose|oakland'}
LOC = re.compile('|'.join(LOC_PAT[l] for l in T.get('locations', []) if l in LOC_PAT) or r'.', re.I)
FOREIGN = re.compile(r'london|toronto|canada|india|bangalore|bengaluru|berlin|paris|singapore|sydney|tokyo|europe'
                     r'|emea|apac|mexico|brazil|israel|dublin|amsterdam|zurich|poland|hong kong|\buk\b|germany'
                     r'|portugal|lisbon|spain|madrid|barcelona|france|netherlands|ireland|italy|sweden|norway|denmark|finland'
                     r'|romania|ukraine|czech|hungary|bulgaria|serbia|lithuania|estonia|latvia|greece|turkey|argentina|colombia'
                     r'|chile|peru|latam|latin america|philippines|japan|korea|china|australia|new zealand|south africa|nigeria'
                     r'|kenya|egypt|dubai|\buae\b|vietnam|thailand|indonesia|pakistan|bangladesh|\beu\b|belgium|austria|switzerland', re.I)
US = re.compile(r'united states|\bus\b|\busa\b|u\.s\.|new york|chicago|seattle|san francisco|\bnyc\b', re.I)

def loc_ok(loc):
    if not loc or re.search(r'see |^\d+ locations$|^united states$', loc, re.I): return True  # unknown: agent checks
    if FOREIGN.search(loc) and not US.search(loc): return False
    return bool(LOC.search(loc))

YRS = re.compile(r'(?<![\d$.])(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|–|to)\s*\d{1,2}\s*\+?\s*)?(?:years?|yrs?)\b'
                 r'(?:\s+of)?[^.\n;]{0,70}?(?:experience|industry|professional|engineering|software|building|working|developing)', re.I)
def years_min(text):
    vals = [int(m.group(1)) for m in YRS.finditer(text or '') if 0 < int(m.group(1)) <= 15]
    return min(vals) if vals else None

MONEY = re.compile(r'\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{2,3}(?:\.\d+)?\s?[kK]\b)')
def amounts(text):
    out = []
    for m in MONEY.finditer(text or ''):
        s = m.group(1).replace(',', '').replace(' ', '')
        v = float(s[:-1]) * 1000 if s[-1] in 'kK' else float(s)
        if 40_000 <= v <= 1_500_000: out.append(v)
    return out
def band_from(text):
    v = amounts(text)
    return (min(v), max(v)) if v else (None, None)

def strip_html(s):
    s = html.unescape(html.unescape(s or ''))
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', s)).strip()

# ---- identity --------------------------------------------------------------------------------------------
GH = re.compile(r'greenhouse\.io/(?:embed/job_app\?for=([^&/]+)&token=(\d+)|([^/?&#]+)/jobs/(\d+))', re.I)
GHJID = re.compile(r'[?&]gh_jid=(\d+)')
ASH = re.compile(r'jobs\.ashbyhq\.com/([^/?#]+)/([0-9a-f]{8}-[0-9a-f-]{27})', re.I)
LV = re.compile(r'jobs\.lever\.co/([^/?#]+)/([0-9a-f]{8}-[0-9a-f-]{27})', re.I)
ACCOUNT_HOST = re.compile(r'amazon\.jobs|google\.com/about/careers|myworkdayjobs\.com|careers\.microsoft\.com|'
                          r'jobs\.apple\.com|metacareers|icims\.com|taleo\.net|successfactors|avature\.net|'
                          r'careers\.qualcomm|careers\.amd', re.I)
try:
    OPEN_PORTALS = set(re.findall(r"'([^']+)'", re.search(r'OPEN_PORTALS = \{([^}]*)\}',
                       open(os.path.join(R, 'scripts', 'portal_sweep.py'), encoding='utf-8').read()).group(1)))
except Exception: OPEN_PORTALS = set()

def ident(url):
    url = re.sub(r'(?<!:)//+', '/', url or '').strip()
    m = GH.search(url)
    if m: return 'gh', (m.group(1) or m.group(3)), (m.group(2) or m.group(4)), url
    m = GHJID.search(url)
    if m: return 'gh', None, m.group(1), url
    m = ASH.search(url)
    if m: return 'ash', m.group(1), m.group(2).lower(), url
    m = LV.search(url)
    if m: return 'lv', m.group(1), m.group(2).lower(), url
    key = re.sub(r'[?#].*$', '', url).rstrip('/').lower()
    key = re.sub(r'^https?://(www\.)?', '', key)
    return 'url', None, key, url

def host_of(url):
    m = re.match(r'https?://([^/]+)', url or '')
    return m.group(1).lower() if m else ''

# ---- add leads -------------------------------------------------------------------------------------------
POOL = P.load()
LOADED = {k: v.get('updated') for k, v in POOL.items()}
NEW = []

def save_pool():
    """Merge, never clobber: any lead a session marked since we loaded keeps the session's version."""
    with P.locked():
        for k, v in P.load().items():
            if v.get('updated') != LOADED.get(k): POOL[k] = v; LOADED[k] = v.get('updated')
        P.save(POOL)

def add(source, company, title, location, url, posted='', band='', desc='', board=None):
    ats, b, jid, url = ident(url)
    if not jid: return
    lid = f'{ats}:{jid}' if ats != 'url' else 'url:' + jid
    l = POOL.get(lid)
    if l:
        if source not in l['sources']: l['sources'].append(source)
        if desc and not l.get('desc'): l['desc'] = desc[:12000]
        return
    POOL[lid] = l = {'id': lid, 'ats': ats, 'board': b or board, 'jid': jid, 'company': company or (b or board or ''),
                     'title': title, 'location': location or '', 'url': url, 'posted': (posted or '')[:16],
                     'band': band or '', 'desc': (desc or '')[:12000], 'sources': [source],
                     'found': START.isoformat()[:16], 'status': 'new'}
    NEW.append(lid)

# ---- 1. searching ----------------------------------------------------------------------------------------
def run_sweep(name, timeout, extra):
    args = [sys.executable, os.path.join(R, 'scripts', name)] + extra
    t0 = time.time()
    try:
        r = subprocess.run(args, cwd=R, capture_output=True, text=True, timeout=timeout, encoding='utf-8',
                           errors='replace', env={**os.environ, 'PYTHONUTF8': '1'})
        log(f'--- {name} exit {r.returncode} in {time.time()-t0:.0f}s'); log(r.stdout[-4000:]); log(r.stderr[-2000:])
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        log(f'--- {name} TIMED OUT after {timeout}s'); return False

def read_json(rel):
    try:
        with open(os.path.join(R, rel), encoding='utf-8') as f: return json.load(f)
    except (OSError, ValueError): return []

def search():
    since = ['--since', (START - datetime.timedelta(days=BACKFILL)).strftime('%Y-%m-%dT%H:%MZ')] if BACKFILL else []
    ok = {}
    ok['boards'] = run_sweep('delta_sweep.py', 660, since)
    for o in read_json('state/sweep/cands.json'):         # [ats, slug, ts, title, loc, comp, url, desc|gh id]
        add('boards', o[1], o[3], o[4], o[6], o[2], o[5], '' if o[0] == 'gh' else o[7], board=o[1])
    ok['vc_boards'] = run_sweep('list_sweep.py', 400, since)
    for o in read_json('state/sweep/list_cands.json'):    # [source, company, posted, title, loc, spons, band, url]
        add('vc:' + o[0], o[1], o[3], o[4], o[7], o[2], o[6])
    ok['career_sites'] = run_sweep('portal_sweep.py', 400, since)
    for o in read_json('state/sweep/portal_cands.json'):  # [portal, host, posted, title, loc, url]
        add('portal', o[0], o[3], o[4], o[5], '' if o[2] == 'new' else o[2])
    ok['extra'] = extra_sweep(since)
    ok['jobdatalake'] = jobdatalake()
    return ok

def extra_sweep(since):
    """Getro VC boards, HN Who-is-hiring, Gem/Workable/Breezy/Rippling/SmartRecruiters boards. Runs every
    collector.extra_sweep_days (default 3) days, or on --force / --backfill; a lookback (--backfill) widens the window."""
    stamp = os.path.join(R, 'state', 'last_extra_sweep.txt')
    days = C.get('extra_sweep_days', 3)
    try: age = time.time() - os.path.getmtime(stamp)
    except OSError: age = 1e12
    if age < days * 86400 and not (BACKFILL or '--force-extra' in ARGS):
        log(f'extra sweep: last ran {age/86400:.1f} days ago, next after {days} days'); return True
    ok = run_sweep('extra_sweep.py', 900, since)
    for o in read_json('state/sweep/extra_cands.json'):   # [source, company, posted, title, loc, band, url, desc]
        add('extra:' + o[0], o[1], o[3], o[4], o[6], o[2], o[5], o[7])
    return ok

JDL_ENTRY = re.compile(r'^\s*\d+\.\s+\*\*(.+?)\*\*\s+at\s+(.+?)\s*\n\s*(.+?)\s*\n(?:\s*Skills:.*\n)?\s*Apply:\s*(\S+)', re.M)
def jobdatalake_rest():
    """REST API with the user's key: 1 credit per request, 100 jobs per request, newest first, no daily cap.
    Returns True when it handled the search, False to fall back to the free MCP path."""
    key = C.get('jobdatalake_api_key')
    if not key: return False
    stamp = os.path.join(R, 'state', 'last_jdl_rest.txt')
    now_ms = int(time.time() * 1000)
    try: since_ms = int(open(stamp).read().strip())
    except Exception: since_ms = now_ms - 7 * 86400000
    if BACKFILL: since_ms = now_ms - BACKFILL * 86400000
    seniority = ','.join(x for x, want in [('Entry', 'early-career' in SEN or WANT_NEWGRAD), ('Mid Level', 'mid-level' in SEN)] if want)
    cap, calls, added = C.get('jobdatalake_rest_max_calls', 60), 0, 0
    places = []
    for loc in T.get('locations', []):
        if loc == 'Remote (US)': places.append({'remote_type': 'fully_remote'})
        elif 'new york' in loc.lower(): places.append({'states': 'NY'})
        elif 'chicago' in loc.lower(): places.append({'states': 'IL', 'location': 'Chicago'})
        else: places.append({'location': loc})
    for q in C.get('jobdatalake_rest_queries', ['software engineer']):
        for pl in places:
            for page in (1, 2, 3):
                if calls >= cap: log('jobdatalake REST: call cap reached'); open(stamp, 'w').write(str(now_ms)); return True
                a = {'q': q, 'countries': 'US', 'job_function': 'eng', 'employment_type': 'full_time', 'posted_after': since_ms,
                     'per_page': 100, 'page': page, 'sort_by': 'posted_at:desc', **pl}
                if seniority: a['seniority'] = seniority
                try:
                    req = urllib.request.Request('https://api.jobdatalake.com/v1/jobs?' + urllib.parse.urlencode(a),
                                                 headers={'X-API-Key': key, 'User-Agent': 'please-hire-me/1'})
                    with urllib.request.urlopen(req, timeout=40, context=ssl.create_default_context()) as r: d = json.load(r)
                    calls += 1
                except urllib.error.HTTPError as e:
                    log(f'jobdatalake REST HTTP {e.code} ({"out of credits" if e.code == 402 else "error"})')
                    return e.code not in (401, 402)       # bad key or no credits: fall back to the free MCP path
                except Exception as e: log('jobdatalake REST error', e); return False
                jobs = d.get('jobs') or []
                for j in jobs:
                    lo, hi = j.get('salary_min_usd'), j.get('salary_max_usd')
                    band = f'${lo}K-${hi}K' if lo and hi else ''
                    where = '; '.join(j.get('locations') or []) + (' (remote)' if j.get('remote_type') == 'fully_remote' else '')
                    posted = datetime.datetime.fromtimestamp((j.get('posted_at') or 0) / 1000, UTC).isoformat()[:16]
                    add('jobdatalake', j.get('company_name', ''), j.get('title', ''), where, j.get('url', ''), posted, band,
                        'Skills: ' + ', '.join(j.get('required_skills') or [])); added += 1
                log(f'jobdatalake REST {q} / {list(pl.values())[0]} p{page}: {len(jobs)}')
                if len(jobs) < 100: break
                time.sleep(0.15)
    open(stamp, 'w').write(str(now_ms)); log(f'jobdatalake REST: {calls} credits, {added} rows'); return True

def jobdatalake():
    if jobdatalake_rest(): return True
    try:
        from jobdatalake import Client
        cl = Client()
    except Exception as e:
        log('jobdatalake unavailable:', e); return False
    stamp = os.path.join(R, 'state', 'last_jdl.txt')
    if not BACKFILL and '--force' not in ARGS:
        try:
            if time.time() - os.path.getmtime(stamp) < C.get('jobdatalake_min_hours', 3) * 3600:
                log('jobdatalake: ran recently, skipped (free tier is 500 calls/day)'); return True
        except OSError: pass
    within = '30d' if BACKFILL else C.get('jobdatalake_posted_within', '7d')
    seniority = ','.join(x for x, want in [('Entry', 'early-career' in SEN or WANT_NEWGRAD),
                                          ('Mid Level', 'mid-level' in SEN)] if want) or None
    calls = 0
    for loc in T.get('locations', []):
        for q in C.get('jobdatalake_queries', ['software engineer']):
            a = {'query': q, 'countries': 'US', 'job_function': 'eng', 'employment_type': 'full_time',
                 'posted_within': within, 'per_page': 100, 'sort_by': 'posted_at:desc'}
            if loc == 'Remote (US)': a['remote_type'] = 'fully_remote'
            else: a['location'] = loc
            if seniority: a['seniority'] = seniority
            if FLOOR: a['salary_min'] = FLOOR
            for page in (1, 2, 3):
                a['page'] = page
                try: text = cl.call('search_jobs', a); calls += 1
                except Exception as e: log('jobdatalake error', q, loc, e); break
                text = text if isinstance(text, str) else json.dumps(text)
                n = 0
                for m in JDL_ENTRY.finditer(text):
                    title, co, meta, url = m.groups()
                    parts = [p.strip() for p in meta.split('|')]
                    where = parts[0] + (' (remote)' if 'fully_remote' in meta else '')
                    add('jobdatalake', co, title, where, url, '', ' '.join(parts[2:]) if len(parts) > 2 else '')
                    n += 1
                log(f'jobdatalake {loc} / {q} p{page}: {n}')
                if calls >= C.get('jobdatalake_max_calls', 20): open(stamp, 'w').write(str(calls)); return True
                if n < 50: break       # a short page means we reached the end of this query
    open(stamp, 'w').write(str(calls))
    return True

# ---- 2. vetting from public APIs -------------------------------------------------------------------------
CTX = ssl.create_default_context()
def get_json(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=20, context=CTX) as r: return json.load(r), 200
    except urllib.error.HTTPError as e: return None, e.code
    except Exception: return None, 0

ASH_CACHE = {}
def enrich(l):
    """Fills desc, band, posted, location, closed state and (Greenhouse) required questions."""
    ats, b, jid = l['ats'], l.get('board'), l['jid']
    if ats == 'gh' and b:
        d, code = get_json(f'https://boards-api.greenhouse.io/v1/boards/{b}/jobs/{jid}?questions=true')
        if code == 404: l['closed'] = True; return
        if not d: return
        l['desc'] = strip_html(d.get('content', ''))[:12000]
        l['company'] = d.get('company_name') or l['company']
        l['posted'] = (d.get('first_published') or l.get('posted') or '')[:16]
        l['location'] = (d.get('location') or {}).get('name') or l['location']
        l['url'] = d.get('absolute_url') or l['url']
        req_q = [q.get('label', '') for q in d.get('questions', []) if q.get('required')]
        demo = [q.get('label', '') for q in ((d.get('demographic_questions') or {}).get('questions') or []) if q.get('required')]
        l['required_questions'] = [x[:160] for x in req_q]
        l['required_self_id'] = demo
    elif ats == 'ash' and b:
        if b not in ASH_CACHE:
            ASH_CACHE[b] = get_json(f'https://api.ashbyhq.com/posting-api/job-board/{b}?includeCompensation=true')[0] or {}
            time.sleep(0.3)
        j = next((x for x in ASH_CACHE[b].get('jobs', []) if (x.get('id') or '').lower() == jid), None)
        if ASH_CACHE[b].get('jobs') and not j: l['closed'] = True; return
        if not j: return
        l['desc'] = (j.get('descriptionPlain') or l.get('desc') or '')[:12000]
        l['band'] = ((j.get('compensation') or {}).get('compensationTierSummary') or l.get('band') or '')
        l['posted'] = (j.get('publishedAt') or l.get('posted') or '')[:16]
        l['location'] = j.get('location') or l['location']
        if j.get('isListed') is False: l['closed'] = True
    elif ats == 'lv' and b:
        d, code = get_json(f'https://api.lever.co/v0/postings/{b}/{jid}')
        if code == 404: l['closed'] = True; return
        if not d: return
        l['desc'] = ((d.get('descriptionPlain') or '') + ' ' + ' '.join(x.get('content', '') for x in d.get('lists') or []))[:12000]
        l['desc'] = strip_html(l['desc'])
        sr = d.get('salaryRange') or {}
        if sr.get('max'): l['band'] = f"${sr.get('min'):,}-${sr.get('max'):,} {sr.get('interval', '')}".strip()
        l['location'] = (d.get('categories') or {}).get('location') or l['location']
        if d.get('createdAt'): l['posted'] = datetime.datetime.fromtimestamp(d['createdAt'] / 1000, UTC).isoformat()[:16]
    l['enriched'] = START.isoformat()[:16]

BLOCK_Q = [re.compile(p, re.I) for p in C.get('blocking_question_patterns', [])]

def gate(l, count, in_tracker):
    """-> (status, reason). Order matters: hard mismatches are skips; blockers route to the user."""
    t, co = l.get('title', ''), l.get('company', '')
    if l.get('closed'): return 'closed', 'posting no longer live'
    if not TIT.search(t) or NOT_WANTED.search(t) or TITLE_EXCLUDE.search(t) or NON_SOFTWARE.search(t): return 'skipped', 'title out of scope'
    bad = BAD.search(re.sub(r'technical staff', '', t, flags=re.I))
    if bad and not (bad.group(0).lower() == 'iii' and III_OK.search(co + ' ' + l.get('url', ''))):
        return 'skipped', f'title level ({bad.group(0)})'
    if not SOFT_TITLE.search(t) and len(FIT.skills((l.get('desc') or '') + ' ' + t)[0]) < 2:
        return 'skipped', 'not a software role'
    if not loc_ok(l.get('location', '')): return 'skipped', 'location'
    if re.search(r'(ashbyhq\.com|lever\.co|greenhouse\.io)/[^/]+/?$', l.get('url', '')): return 'skipped', 'link is a whole job board, not one posting'
    if any(P.same_company(co, s) for s in SKIP_COS): return 'skipped', 'skip list'
    if l.get('url') in in_tracker: return 'skipped', 'already in tracker'
    if count(co) >= RUN.get('max_applications_per_company_lifetime', 2): return 'skipped', 'company at lifetime cap'
    y = years_min(l.get('desc', ''))
    l['years_min'] = y
    if y is not None and y > MAX_YEARS: return 'skipped', f'{y}+ years required'
    lo, hi = band_from(l.get('band') or '')
    if hi is None: lo, hi = band_from(l.get('desc', ''))
    if hi is not None:
        if not l.get('band'): l['band'] = f'${lo/1000:.0f}K-${hi/1000:.0f}K (from description)'
        if FLOOR and hi < FLOOR: return 'skipped', f'pay max ${hi:,.0f} under floor'
    l['fit'] = FIT.score(t, l.get('desc', ''), y, l.get('location', ''), lo, hi)
    if l['fit'] < C.get('min_fit', 0): return 'skipped', f"low fit ({l['fit']}/100)"
    host = host_of(l.get('url', ''))
    if ACCOUNT_HOST.search(l.get('url', '')) and host not in SIGNED and host not in OPEN_PORTALS:
        return 'blocked', 'career site needs your account'
    if l.get('required_self_id') and C.get('route_required_self_id_to_you', True):
        return 'blocked', 'form requires demographic self-ID answers (agent is blocked from filling them)'
    for q in l.get('required_questions', []):
        for p in BLOCK_Q:
            if p.search(q): return 'blocked', f'required question with no answer on file: "{q[:110]}"'
    return 'ready', ''

TODO = {'career site needs your account': 'Sign in on the career site and apply (or sign in once in Chrome and ask to add the site to signed_in_portals)',
        'self-ID': 'Apply on the posting; your self-ID answers are in config/profile.json',
        'question': 'Answer that question and apply; or add the fact to config/answers.md so future runs can'}

def to_tracker(leads):
    if not leads: return 0
    try: text = open(P.TRACKER, encoding='utf-8').read()
    except OSError: return 0
    i = text.find('## Apply yourself')
    j = text.find('|---', i) if i >= 0 else -1
    if j < 0: return 0
    k = text.find('\n', j) + 1
    rows = []
    for l in leads:
        if l['url'] in text: continue
        why = l['reason']
        todo = TODO['career site needs your account'] if 'account' in why else TODO['self-ID'] if 'self-ID' in why else TODO['question']
        cell = lambda s: str(s or '').replace('|', '/').replace('\n', ' ')
        rows.append('| ' + ' | '.join(cell(x) for x in [P.today(), l['company'], l['title'], l['location'] or 'see posting',
                    l.get('band') or 'see posting', l['url'], why, todo, 'Open']) + ' |\n')
    if rows:
        with open(P.TRACKER, 'w', encoding='utf-8') as f: f.write(text[:k] + ''.join(rows) + text[k:])
    return len(rows)

def vet():
    count, _ = P.company_counts()
    in_tracker = P.tracker_urls()
    stale_days = C.get('stale_after_days', 30)
    todo = sorted([l for l in POOL.values() if l['status'] == 'new'], key=P.sort_key, reverse=True)
    budget = C.get('max_enrich_per_run', 400)
    routed, tally = [], {}
    for l in todo:
        if l['ats'] in ('gh', 'ash', 'lv') and l.get('board') and not l.get('enriched'):
            if budget <= 0: continue          # no budget left: stay 'new' and get vetted properly next run
            enrich(l); budget -= 1
            if l['ats'] != 'ash': time.sleep(0.25)
        status, reason = gate(l, count, in_tracker)
        l['status'], l['reason'] = status, reason
        tally[status] = tally.get(status, 0) + 1
        if status == 'blocked': routed.append(l)
    # Ready leads that sat too long go stale (the agent re-checks liveness anyway).
    cutoff = (START - datetime.timedelta(days=stale_days)).isoformat()[:16]
    for l in POOL.values():
        if l['status'] == 'ready' and (l.get('posted') or l['found']) < cutoff: l['status'] = 'stale'
    return tally, to_tracker(routed)

# ---- main ------------------------------------------------------------------------------------------------
def main():
    stamp = os.path.join(R, 'state', 'last_collect.txt')
    gap = C.get('min_minutes_between_runs', 20) * 60
    if not (BACKFILL or VET_ONLY or '--force' in ARGS or '--import' in ARGS):
        try:
            if time.time() - os.path.getmtime(stamp) < gap:
                print(f'collector ran {int((time.time()-os.path.getmtime(stamp))/60)} min ago; nothing to do yet (--force to override)'); return
        except OSError: pass
    try: os.mkdir(LOCK)
    except FileExistsError:
        if time.time() - os.path.getmtime(LOCK) < 1800:
            print('collector already running; skipped'); return
    try:
        log(f'\n===== collect {START.isoformat()[:16]}Z backfill={BACKFILL} vet_only={VET_ONLY}')
        if '--import' in ARGS:
            # Leads found by a Claude session (GrepJob needs the user's login, so only a session can call it).
            # File: JSON list of {company, title, location, url, band, desc, posted}. They get the same vetting.
            rows = json.load(open(ARGS[ARGS.index('--import') + 1], encoding='utf-8'))
            for r in rows:
                add('grepjob', r.get('company', ''), r.get('title', ''), r.get('location', ''), r.get('url', ''),
                    r.get('posted', ''), r.get('band', ''), r.get('desc', ''))
            print(f'imported {len(rows)} GrepJob rows; {len(NEW)} were new')
        ok = {} if (VET_ONLY or '--import' in ARGS) else search()
        save_pool()                                  # save BEFORE vetting: found leads are never lost
        if VET_ONLY:
            for l in POOL.values():
                if l['status'] in ('ready', 'skipped', 'blocked') and l.get('reason') != 'already in tracker':
                    l['status'] = 'new'
        tally, routed = vet()
        save_pool()
        st = {}
        for l in POOL.values(): st[l['status']] = st.get(l['status'], 0) + 1
        failed = [k for k, v in ok.items() if not v]
        msg = (f'collector: {len(NEW)} new leads; vetted {sum(tally.values())} -> ' +
               ', '.join(f'{k} {v}' for k, v in sorted(tally.items())) +
               f'; {routed} added to "Apply yourself". Pool now: ' + ', '.join(f'{k} {v}' for k, v in sorted(st.items())) +
               (f'. Sources that failed: {", ".join(failed)} (see logs/collector.log)' if failed else ''))
        log(msg); print(msg)
        if not VET_ONLY: open(stamp, 'w').write(START.isoformat())
    finally:
        try: os.rmdir(LOCK)
        except OSError: pass

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""All-jobs feed: every open software-type role in the US (or remote) posted in the last N days, from every source
this repo can read without a login. No gate on level, pay or years. Feeds the "All Engineering Jobs" page.

    python3 scripts/all_jobs.py                  # writes jobs-page/jobs.json (30 days)
    python3 scripts/all_jobs.py --days 14 --out /some/dir
    python3 scripts/all_jobs.py --only workday,oracle     # test some sources

Sources: Ashby, Greenhouse, Lever (data/slug-candidates.txt + data/boards.md), SmartRecruiters, Gem, Breezy,
Rippling (data/extra-slugs.json), Getro investor boards, Workday and Oracle career sites (data/portals.json),
Amazon, Google, Microsoft, Netflix, Jane Street, Y Combinator and JobDataLake. Reads nothing from config/ or
state/, so it runs on a fresh checkout. Runs about 15 minutes; every source is optional and a failing one is
reported in the summary, not fatal.
"""
import csv, hashlib, html, json, os, re, sys, time, datetime, urllib.request, urllib.parse, urllib.error, concurrent.futures as cf

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ARGS = sys.argv[1:]
arg = lambda n, d=None: ARGS[ARGS.index(n) + 1] if n in ARGS else d
DAYS = int(arg('--days', 30))
OUT = arg('--out', os.path.join(R, 'jobs-page'))
ONLY = set(arg('--only', '').split(',')) - {''}
UTC = datetime.timezone.utc
NOW = datetime.datetime.now(UTC)
CUT = NOW - datetime.timedelta(days=DAYS)
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128 Safari/537.36'
T0 = time.time()

ROLE = re.compile(r'software (engineer|developer|development engineer)|\bswe\b|\bsde\b|full[- ]?stack|product engineer|back[- ]?end (software )?engineer|front[- ]?end (software )?engineer'
                  r'|forward[- ]deployed|platform engineer|infrastructure engineer|site reliability|\bsre\b|devops|cloud engineer|distributed systems|data engineer'
                  r'|machine learning engineer|\bml engineer|\bai engineer|ai/ml engineer|\bsdet\b|engineer in test|test automation|security engineer'
                  r'|developer (tools|experience|productivity)|member of technical staff|\bmts\b|applied ai engineer|systems engineer|web developer|application developer', re.I)
EXCL = re.compile(r'\bios\b|android|mobile|embedded|firmware|hardware|electrical|mechanical|network engineer|sales engineer|solutions? engineer|support engineer|\bit engineer|devrel'
                  r'|developer relations|developer advocate|robotics|silicon|\basic\b|\bfpga\b|solutions? (architect|consultant)|account (manager|executive)|customer success|recruit'
                  r'|field engineer|manufactur|process engineer|\bintern\b|internship|co-?op\b|\bcontract(or)?\b|part.?time|forward deployed (accountant|strategist|analyst)', re.I)
MGMT = re.compile(r'manager|director|head of|\bvp\b|vice president|chief', re.I)
want = lambda t: bool(t and ROLE.search(t) and not EXCL.search(t) and not MGMT.search(t))

NYC = re.compile(r'new york|\bnyc\b|brooklyn|manhattan|\bny\b|jersey city|hoboken', re.I)
REMOTE = re.compile(r'remote|anywhere|distributed|work from home|virtual', re.I)
USW = re.compile(r'united states|\busa?\b|u\.s\.|\bamericas?\b|north america|new york|\bnyc\b|san francisco|\bsf\b|bay area|seattle|chicago|boston|austin|los angeles|denver|atlanta'
                 r'|palo alto|mountain view|menlo park|sunnyvale|san jose|redwood city|oakland|berkeley|san mateo|santa clara|cupertino|brooklyn|washington,? d\.?c|miami|jersey city'
                 r'|philadelphia|pittsburgh|san diego|dallas|houston|nashville|raleigh|salt lake|phoenix|minneapolis|detroit|columbus|california|texas|colorado|massachusetts|illinois|virginia', re.I)
FOREIGN = re.compile(r'london|toronto|vancouver|montr[eé]al|canada|india|bangalore|bengaluru|hyderabad|pune|chennai|gurugram|noida|mumbai|delhi|berlin|munich|paris|singapore|sydney'
                     r'|melbourne|tokyo|europe|emea|apac|mexico|brazil|s[aã]o paulo|israel|tel aviv|dublin|amsterdam|zurich|poland|warsaw|krak[oó]w|hong kong|\buk\b|united kingdom|england'
                     r'|germany|portugal|lisbon|spain|madrid|barcelona|france|netherlands|ireland|italy|sweden|stockholm|norway|denmark|copenhagen|finland|romania|bucharest|ukraine|czech|prague'
                     r'|hungary|budapest|bulgaria|serbia|greece|turkey|argentina|colombia|chile|peru|latam|philippines|manila|japan|korea|seoul|china|shanghai|beijing|taiwan|australia'
                     r'|new zealand|south africa|nigeria|kenya|egypt|dubai|\buae\b|vietnam|thailand|indonesia|malaysia|pakistan|belgium|austria|vienna|switzerland|costa rica|ontario|quebec|scotland', re.I)
STATES = re.compile(r'(?:,|\s-)\s*(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC)\b')
def us_ok(loc):
    if not loc: return True
    if USW.search(loc): return True
    if FOREIGN.search(loc): return False
    return bool(STATES.search(loc) or REMOTE.search(loc))

LEVEL = [('Intern', re.compile(r'\bintern(ship)?\b|co-?op\b', re.I)),
         ('Senior+', re.compile(r'senior|\bsr\.?\b|staff|principal|\blead\b|architect|\b(III|IV|V)\b|\b[3-6]\b$|founding|distinguished', re.I)),
         ('Entry', re.compile(r'new ?grad|new college|university|graduate\b|early career|entry|junior|\bjr\b|associate\b|\b(I|1)\b(?!\w)', re.I))]
level = lambda t: next((n for n, rx in LEVEL if rx.search(t)), 'Mid / unspecified')

def get(u, data=None, headers=None, text=False, tries=3, timeout=25):
    h = {'User-Agent': UA, 'Accept': 'text/html' if text else 'application/json'}
    if data is not None: h['Content-Type'] = 'application/json'
    h.update(headers or {})
    for a in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, data=json.dumps(data).encode() if data is not None else None, headers=h), timeout=timeout) as r:
                b = r.read().decode('utf-8', 'replace')
                return b if text else json.loads(b)
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 403, 404, 406, 410, 422) or a == tries - 1: return None
            time.sleep(3 * (a + 1))
        except Exception:
            if a == tries - 1: return None
            time.sleep(1)

def ts(s):
    try:
        d = datetime.datetime.fromisoformat((s or '').strip().replace('Z', '+00:00'))
        return (d if d.tzinfo else d.replace(tzinfo=UTC)).astimezone(UTC)
    except Exception: return None

def strip(x):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html.unescape(html.unescape(x or '')))).strip()

# ---- fit against the resume: scripts/fit.py (edit HAVE / GAPS there). Full score needs the description; other rows are scored on title + location only.
import fit as FIT
YRS = re.compile(r'(?<![\d$.])(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*\d{1,2}\s*\+?\s*)?(?:years?|yrs?)\b(?:\s+of)?[^.\n;]{0,70}?(?:experience|industry|professional|engineering|software|building|working|developing)', re.I)
MONEY = re.compile(r'\$\s?(\d{1,3}(?:,\d{3})+|\d{2,3}(?:\.\d+)?\s?[kK]\b)')
def fit_of(r):
    desc = r.pop('_desc', None) or ''
    v = [int(m.group(1)) for m in YRS.finditer(desc) if 0 < int(m.group(1)) <= 15]
    years = min(v) if v else None
    amt = []
    for m in MONEY.finditer((r['p'] or '') + ' ' + desc[-3000:]):
        x = m.group(1).replace(',', '').replace(' ', ''); x = float(x[:-1]) * 1000 if x[-1] in 'kK' else float(x)
        if 40_000 <= x <= 1_500_000: amt.append(x)
    lo, hi = (min(amt), max(amt)) if amt else (None, None)
    have, gaps = FIT.skills(desc + ' ' + r['t']) if desc else ([], [])
    r.update(f=FIT.score(r['t'], desc, years, r['l'], lo, hi), fd=1 if desc else 0, y=years or 0, g=', '.join(gaps[:4]), m=', '.join(have[:6]))

ROWS, STATS = [], {}
def add(src, company, title, loc, posted, url, pay='', dated=True, desc=None):
    """posted: aware datetime or None. dated=False marks a source that gives no posting date."""
    title = re.sub(r'\s+', ' ', title or '').strip(); loc = re.sub(r'\s+', ' ', loc or '').strip()
    if not url or not want(title) or not us_ok(loc): return 0
    if dated and (not posted or posted < CUT): return 0
    ROWS.append(dict(s=src, c=(company or '').strip(), t=title, l=loc[:140], p=(pay or '')[:60], d=posted.isoformat()[:10] if (dated and posted) else '', u=url, k=1 if dated else 0, _desc=desc))
    return 1
def source(name):
    def deco(fn):
        def run():
            if ONLY and name not in ONLY: return
            t, n0 = time.time(), len(ROWS)
            try: note = fn() or ''
            except Exception as e: note = f'FAILED {type(e).__name__}: {e}'
            STATS[name] = dict(jobs=len(ROWS) - n0, seconds=round(time.time() - t), note=str(note))
            print(f'  {name}: {len(ROWS) - n0} jobs, {time.time() - t:.0f}s {note}', flush=True)
        run.__name__ = name; return run
    return deco
def pool(fn, items, threads):
    with cf.ThreadPoolExecutor(threads) as ex: return list(ex.map(fn, items))

# ---------------------------------------------------------------- company boards
def slugs():
    s = set()
    for l in open(os.path.join(R, 'data', 'slug-candidates.txt'), encoding='utf-8'):
        l = l.strip()
        if l and not l.startswith('#') and '/' not in l and ' ' not in l: s.add(l)
    for l in open(os.path.join(R, 'data', 'boards.md'), encoding='utf-8'):
        if l.startswith('|'):
            c = l.split('|')
            if len(c) > 3: s.update(re.findall(r'`([A-Za-z0-9._-]+)`', c[2]))
    s.discard('jobgether')   # reposts other companies' jobs
    return sorted(s)
try: EXTRA = json.load(open(os.path.join(R, 'data', 'extra-slugs.json'), encoding='utf-8'))
except Exception: EXTRA = {}
LIVE = set()

def b_ashby(s):
    d = get(f'https://api.ashbyhq.com/posting-api/job-board/{s}?includeCompensation=true')
    if not isinstance(d, dict) or not d.get('jobs'): return
    LIVE.add(s)
    for j in d['jobs']:
        if not j.get('isListed', True): continue
        loc = ' | '.join(x for x in [j.get('location') or ''] + [x.get('location', '') for x in (j.get('secondaryLocations') or [])] if x)
        if j.get('isRemote') and not REMOTE.search(loc): loc += ' | Remote'
        add('Ashby', s, j.get('title'), loc, ts(j.get('publishedAt')), j.get('jobUrl'), (j.get('compensation') or {}).get('compensationTierSummary'), desc=j.get('descriptionPlain'))
def b_greenhouse(s):
    d = get(f'https://boards-api.greenhouse.io/v1/boards/{s}/jobs')
    if not isinstance(d, dict) or not d.get('jobs'): return
    LIVE.add(s)
    hit = [j for j in d['jobs'] if want(j.get('title')) and us_ok((j.get('location') or {}).get('name')) and (ts(j.get('first_published')) or CUT) >= CUT]
    if not hit: return
    full = get(f'https://boards-api.greenhouse.io/v1/boards/{s}/jobs?content=true')   # second call only for boards with a match: descriptions for the fit score
    body = {j.get('id'): strip(j.get('content')) for j in (full or {}).get('jobs') or []} if isinstance(full, dict) else {}
    for j in hit: add('Greenhouse', j.get('company_name') or s, j.get('title'), (j.get('location') or {}).get('name'), ts(j.get('first_published')), j.get('absolute_url'), desc=body.get(j.get('id')))
def b_lever(s):
    d = get(f'https://api.lever.co/v0/postings/{s}?mode=json')
    if not isinstance(d, list) or not d: return
    LIVE.add(s)
    for j in d:
        c = j.get('categories') or {}; sr = j.get('salaryRange') or {}
        loc = ' | '.join(dict.fromkeys(x for x in [c.get('location') or ''] + (c.get('allLocations') or []) if x))
        if j.get('workplaceType') == 'remote' and not REMOTE.search(loc): loc += ' | Remote'
        add('Lever', s, j.get('text'), loc, datetime.datetime.fromtimestamp((j.get('createdAt') or 0) / 1000, UTC), j.get('hostedUrl'),
            f"${sr['min']:,}-${sr['max']:,}" if sr.get('min') and sr.get('max') else '',
            desc=(j.get('descriptionPlain') or '') + ' ' + ' '.join(strip(x.get('content')) for x in j.get('lists') or []))
def b_smart(s):
    for off in range(0, 1000, 100):
        d = get(f'https://api.smartrecruiters.com/v1/companies/{s}/postings?limit=100&offset={off}')
        items = (d or {}).get('content') if isinstance(d, dict) else None
        if not items: return
        for j in items:
            l = j.get('location') or {}
            loc = ', '.join(x for x in (l.get('city'), l.get('region'), (l.get('country') or '').upper()) if x) + (' | Remote' if l.get('remote') else '')
            add('SmartRecruiters', (j.get('company') or {}).get('name') or s, j.get('name'), loc, ts(j.get('releasedDate')), f"https://jobs.smartrecruiters.com/{s}/{j.get('id')}")
        if len(items) < 100: return
def b_gem(s):
    for j in get(f'https://api.gem.com/job_board/v0/{s}/job_posts/') or []:
        loc = (j.get('location') or {}).get('name', '') if isinstance(j.get('location'), dict) else str(j.get('location') or '')
        if j.get('location_type') == 'remote' and not REMOTE.search(loc): loc += ' | Remote'
        add('Gem', s, j.get('title'), loc, ts(j.get('first_published_at') or j.get('updated_at')), j.get('absolute_url'))
def b_breezy(s):
    for j in get(f'https://{s}.breezy.hr/json') or []:
        l = j.get('location') or {}
        loc = (l.get('name') or ', '.join(x for x in (l.get('city'), (l.get('state') or {}).get('name')) if x)) + (' | Remote' if l.get('is_remote') else '')
        add('Breezy', (j.get('company') or {}).get('name') or s, j.get('name'), loc, ts(j.get('published_date')), j.get('url'))
def b_rippling(s):
    for pg in range(5):
        items = (get(f'https://ats.rippling.com/api/v2/board/{s}/jobs?page={pg}&pageSize=50') or {}).get('items') or []
        for j in items: add('Rippling', s, j.get('name'), '; '.join(x.get('name', '') for x in (j.get('locations') or [])), None, j.get('url'), dated=False)
        if len(items) < 50: return

@source('boards')
def boards():
    S = slugs()
    for fn in (b_ashby, b_greenhouse, b_lever): pool(fn, S, 32)
    return f'{len(S)} company names, {len(LIVE)} with a live board'
@source('small-ats')
def small_ats():
    S = slugs()
    pool(b_smart, sorted(set(EXTRA.get('smartrecruiters', [])) | {s for s in S if s not in LIVE}), 16)
    pool(b_gem, EXTRA.get('gem', []), 8); pool(b_breezy, EXTRA.get('breezy', []), 8); pool(b_rippling, EXTRA.get('rippling', []), 8)

# ---------------------------------------------------------------- investor boards (Getro)
GETRO = ['jobs.accel.com', 'jobs.generalcatalyst.com', 'jobs.khoslaventures.com', 'jobs.insightpartners.com', 'jobs.greycroft.com', 'jobs.menlovc.com', 'jobs.thrivecap.com', 'jobs.luxcapital.com']
GETRO_Q = ['software engineer', 'backend engineer', 'full stack engineer', 'infrastructure engineer', 'forward deployed engineer', 'site reliability engineer', 'data engineer', 'machine learning engineer', 'platform engineer']
def getro(host):
    page = get(f'https://{host}/jobs', text=True) or ''
    m = re.search(r'"network_?[iI]d"\s*:\s*"?(\d+)', page)
    if not m: return
    hdr = {'Origin': f'https://{host}', 'Referer': f'https://{host}/jobs'}
    for q in GETRO_Q:
        for pg in range(4):
            d = get(f'https://api.getro.com/api/v2/collections/{m.group(1)}/search/jobs', {'hits_per_page': 100, 'page': pg, 'query': q, 'filters': {}}, hdr)
            jobs = ((d or {}).get('results') or {}).get('jobs') or []
            if not jobs: break
            for j in jobs:
                locs = '; '.join(j.get('searchable_locations') or []) + (' | Remote' if j.get('work_mode') == 'remote' else '')
                mx, mn = j.get('compensation_amount_max_cents'), j.get('compensation_amount_min_cents')
                add('Investor board', (j.get('organization') or {}).get('name'), j.get('title'), locs, datetime.datetime.fromtimestamp(j.get('created_at', 0), UTC), j.get('url'),
                    f'${(mn or 0) // 100000}K-${mx // 100000}K' if mx else '')
            time.sleep(0.3)
@source('investor-boards')
def investor(): pool(getro, GETRO, 4)

# ---------------------------------------------------------------- big-company career sites
try: PORTALS = json.load(open(os.path.join(R, 'data', 'portals.json'), encoding='utf-8'))
except Exception: PORTALS = {}
WD_BUDGET, WD_END = int(arg('--workday-seconds', 600)), [0]
REL = re.compile(r'Posted (Today|Yesterday|(\d+)\+? Days? Ago)', re.I)
def wd_get(u, body):
    """Workday throttles by caller, across employers (HTTP 429): pace every call and back off hard."""
    for a in range(2):
        if time.time() > WD_END[0]: return None
        time.sleep(0.5)
        try:
            with urllib.request.urlopen(urllib.request.Request(u, data=json.dumps(body).encode(), headers={'User-Agent': UA, 'Accept': 'application/json', 'Content-Type': 'application/json'}), timeout=25) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429: return None
            time.sleep(10)
        except Exception:
            if a: return None
def workday(row):
    label, ten, wd, site = row; ok = False; seen = set()
    for q, pages in (('software engineer', 4), ('data engineer', 1), ('machine learning engineer', 1)):
        for off in range(0, pages * 20, 20):
            d = wd_get(f'https://{ten}.{wd}.myworkdayjobs.com/wday/cxs/{ten}/{site}/jobs', {'appliedFacets': {}, 'limit': 20, 'offset': off, 'searchText': q})
            posts = (d or {}).get('jobPostings') if isinstance(d, dict) else None
            if not posts: break
            ok = True
            for j in posts:
                m = REL.search(j.get('postedOn') or ''); path = j.get('externalPath', '')
                if not m or path in seen: continue
                seen.add(path)
                days = 0 if m.group(1).lower() == 'today' else 1 if m.group(1).lower() == 'yesterday' else int(m.group(2))
                loc = j.get('locationsText') or ''
                if re.match(r'\d+ Locations', loc): loc = re.sub(r'[-_]', ' ', (re.search(r'/job/([^/]+)/', path) or [0, ''])[1]) + f' (+{loc})'
                add('Workday', label, j.get('title'), loc, NOW - datetime.timedelta(days=days), f'https://{ten}.{wd}.myworkdayjobs.com/en-US/{site}{path}')
            if len(posts) < 20: break
    return ok
@source('workday')
def workday_all():
    rows = PORTALS.get('workday', [])
    k = (NOW.timetuple().tm_yday * 97) % max(1, len(rows))   # start somewhere new each day, so a cut-off run still covers everyone over the week
    WD_END[0] = time.time() + WD_BUDGET
    res = pool(workday, rows[k:] + rows[:k], 2)
    return f'{sum(res)} of {len(res)} employers answered in the {WD_BUDGET // 60}-minute budget'
def oracle(row):
    label, host, site = row; ok = False
    for q in ('software engineer', 'data engineer', 'machine learning engineer'):
        for off in range(0, 300, 100):
            d = get(f'https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList'
                    f'&finder=findReqs;siteNumber={site},keyword=%22{urllib.parse.quote(q)}%22,limit=100,offset={off},sortBy=POSTING_DATES_DESC', tries=2)
            reqs = (((d or {}).get('items') or [{}])[0].get('requisitionList') or []) if isinstance(d, dict) else []
            if not reqs: break
            ok = True; old = False
            for x in reqs:
                p = ts((x.get('PostedDate') or '') + 'T00:00:00+00:00')
                if p and p < CUT: old = True
                url = f"https://jobs.uber.com/en/jobs/{x['Id']}/" if label == 'Uber' else f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{x['Id']}"
                add('Oracle', label, x.get('Title'), x.get('PrimaryLocation'), p, url)
            if old or len(reqs) < 100: break
    return ok
@source('oracle')
def oracle_all():
    res = pool(oracle, PORTALS.get('oracle', []), 6)
    return f'{sum(res)} of {len(res)} employers answered'

@source('amazon')
def amazon():
    seen = set()
    for q in ('software development engineer', 'software engineer', 'data engineer', 'machine learning engineer', 'systems development engineer'):
        for off in range(0, 2000, 100):
            d = get('https://www.amazon.jobs/en/search.json?' + urllib.parse.urlencode({'base_query': q, 'country[]': 'USA', 'result_limit': 100, 'offset': off, 'sort': 'recent'}))
            jobs = (d or {}).get('jobs') if isinstance(d, dict) else None
            if not jobs: break
            old = 0
            for j in jobs:
                try: p = datetime.datetime.strptime(j.get('posted_date', ''), '%B %d, %Y').replace(tzinfo=UTC)
                except Exception: continue
                old += p < CUT
                if j.get('job_path') in seen: continue
                seen.add(j.get('job_path'))
                add('Amazon', 'Amazon', j.get('title'), j.get('normalized_location') or j.get('location'), p, 'https://www.amazon.jobs' + (j.get('job_path') or ''))
            if old > 50: break
            time.sleep(0.5)
@source('google')
def google():
    seen = set()
    for q in ('software engineer', 'data engineer', 'site reliability engineer', 'machine learning engineer', 'security engineer'):
        for locq in ('New York, NY, USA', 'United States'):
            for page in range(1, 6):
                t = get('https://www.google.com/about/careers/applications/jobs/results/?' + urllib.parse.urlencode({'q': q, 'location': locq, 'sort_by': 'date', 'page': page}), text=True)
                cards = re.split(r'<li class="lLd3Je"', t or '')[1:]
                if not cards: break
                for c in cards:
                    jid = re.search(r"ssk='\d+:(\d+)'", c); ti = re.search(r'<h3 class="QJPWVe">([^<]+)</h3>', c)
                    if not jid or not ti or jid.group(1) in seen: continue
                    seen.add(jid.group(1))
                    locs = '; '.join(dict.fromkeys(re.findall(r'([A-Z][a-zA-Z .]+, [A-Z]{2}, USA)', c))) or locq
                    add('Google', 'Google', html.unescape(ti.group(1)), locs, None, f'https://www.google.com/about/careers/applications/jobs/results/{jid.group(1)}', dated=False)
                time.sleep(0.7)
    return 'newest listings per search; Google shows no posting date'
@source('microsoft')
def microsoft():
    for q in ('software engineer', 'data engineer', 'machine learning engineer', 'site reliability engineer'):
        for start in range(0, 100, 10):
            d = get('https://apply.careers.microsoft.com/api/pcsx/search?' + urllib.parse.urlencode({'domain': 'microsoft.com', 'query': q, 'location': 'United States', 'start': start}))
            ps = ((d or {}).get('data') or {}).get('positions') if isinstance(d, dict) else None
            if not ps: break
            for p in ps:
                add('Microsoft', 'Microsoft', (p.get('name') or '').lstrip('#'), '; '.join(p.get('locations') or []), datetime.datetime.fromtimestamp(int(p['postedTs']), UTC) if p.get('postedTs') else None,
                    f"https://apply.careers.microsoft.com{p.get('positionUrl') or '/careers/job/' + str(p['id'])}")
            time.sleep(1.5)
@source('netflix')
def netflix():
    d = get('https://explore.jobs.netflix.net/api/apply/v2/jobs?' + urllib.parse.urlencode({'domain': 'netflix.com', 'query': 'engineer', 'location': 'United States', 'num': 100, 'sort_by': 'timestamp'}))
    for p in (d or {}).get('positions') or [] if isinstance(d, dict) else []:
        add('Netflix', 'Netflix', p.get('name'), ' | '.join(dict.fromkeys([p.get('location') or ''] + (p.get('locations') or []))), datetime.datetime.fromtimestamp(int(p['t_create']), UTC) if p.get('t_create') else None,
            f"https://explore.jobs.netflix.net/careers/job/{p['id']}")
@source('janestreet')
def janestreet():
    CITY = {'NYC': 'New York, NY', 'CHI': 'Chicago, IL'}
    for j in get('https://www.janestreet.com/jobs/main.json') or []:
        if j.get('city') in CITY and 'Experienced' in (j.get('availability') or ''):
            pay = f"${j['min_salary']}-${j['max_salary']}" if j.get('min_salary') and j.get('max_salary') else ''
            add('Jane Street', 'Jane Street', j.get('position'), CITY[j['city']], None, f"https://www.janestreet.com/join-jane-street/position/{j.get('id')}/", pay, dated=False)
    return 'no posting dates in the feed'
@source('ycombinator')
def yc():
    seen = set()
    for role in ('software-engineer', 'software-engineer/new-york', 'software-engineer/remote', 'software-engineer/san-francisco'):
        t = get(f'https://www.ycombinator.com/jobs/role/{role}', text=True) or ''
        m = re.search(r'data-page="([^"]+)"', t)
        if not m: continue
        for j in (json.loads(html.unescape(m.group(1))).get('props') or {}).get('jobPostings') or []:
            if j.get('id') in seen: continue
            seen.add(j.get('id'))
            add('Y Combinator', j.get('companyName'), j.get('title'), j.get('location'), None, 'https://www.ycombinator.com' + (j.get('url') or ''), j.get('salaryRange'), dated=False)
    return 'first page of each search; dates are relative'

# ---------------------------------------------------------------- JobDataLake (aggregator; dates not trusted)
@source('jobdatalake')
def jdl():
    import jobdatalake as J
    c = J.Client(timeout=60); calls = failed = 0
    ITEM = re.compile(r'^\d+\.\s+\*\*(.+?)\*\*\s+at\s+(.+?)\s*$\n\s+(.*?)\s*$\n(?:\s+Skills:.*$\n)?\s+Apply:\s+(\S+)', re.M)
    for q in ('software engineer', 'full stack engineer', 'backend engineer', 'product engineer', 'forward deployed engineer', 'platform engineer', 'infrastructure engineer',
              'site reliability engineer', 'devops engineer', 'data engineer', 'machine learning engineer', 'ai engineer'):
        for locq in ('New York', 'Remote'):
            for page in range(1, 4):
                calls += 1
                try: out = c.call('search_jobs', {'query': q, 'location': locq, 'countries': 'US', 'posted_within': '14d', 'per_page': 100, 'page': page})
                except Exception:
                    failed += 1
                    try: c = J.Client(timeout=60)
                    except Exception: return f'stopped after {calls} calls: service not answering'
                    break
                items = ITEM.findall(out if isinstance(out, str) else json.dumps(out))
                for title, co, meta, url in items:
                    if 'jobgether' in url.lower(): continue
                    parts = [p.strip() for p in meta.split('|')]
                    add('JobDataLake', co, title, parts[0] + (' | Remote' if 'fully_remote' in meta and not REMOTE.search(parts[0]) else ''), None, url, parts[-1] if '$' in parts[-1] else '', dated=False)
                if len(items) < 100: break
    return f'{calls} of 500 free daily calls used ({failed} failed); New York and remote only'

# ---------------------------------------------------------------- run
for fn in (boards, small_ats, investor, workday_all, oracle_all, amazon, google, microsoft, netflix, janestreet, yc, jdl): fn()

def key(u):
    u = re.sub(r'[?#].*$', '', (u or '').lower()).rstrip('/')
    m = re.search(r'([0-9a-f]{8}-[0-9a-f-]{27})', u) or re.search(r'amazon\.jobs/.*?/jobs/(\d+)', u) or re.search(r'(?:greenhouse\.io/.*/jobs/|gh_jid=)(\d+)', u) \
        or re.search(r'myworkdayjobs\.com/.*_([a-z]*-?\d{4,}(?:-\d+)?)$', u)
    return m.group(1) if m else re.sub(r'^https?://(www\.)?', '', u)
ROWS.sort(key=lambda r: (-r['k'], r['s'] == 'Investor board'))   # company's own dated posting wins over a copy
seen, jobs = set(), []
for r in ROWS:
    k = key(r['u'])
    if k in seen: continue
    seen.add(k)
    fit_of(r)
    r.update(v=level(r['t']), n=1 if NYC.search(r['l']) else 0, r=1 if REMOTE.search(r['l']) else 0, h=hashlib.sha1(k.encode()).hexdigest()[:12])
    jobs.append(r)
jobs.sort(key=lambda r: r['d'] or '0', reverse=True)

os.makedirs(OUT, exist_ok=True)
meta = dict(generated=NOW.isoformat(timespec='minutes').replace('+00:00', 'Z'), days=DAYS, total=len(jobs), dated=sum(j['k'] for j in jobs), nyc=sum(j['n'] for j in jobs),
            companies=len({j['c'].lower() for j in jobs}), sources=STATS)
json.dump(dict(meta=meta, jobs=jobs), open(os.path.join(OUT, 'jobs.json'), 'w', encoding='utf-8'), separators=(',', ':'), ensure_ascii=False)
with open(os.path.join(OUT, 'jobs.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f); w.writerow(['fit_%', 'fit_basis', 'title', 'company', 'location', 'level', 'years_asked', 'skills_you_have', 'skills_missing', 'pay', 'posted', 'source', 'url'])
    for j in jobs: w.writerow([j['f'], 'full description' if j['fd'] else 'title only', j['t'], j['c'], j['l'], j['v'], j['y'] or '', j['m'], j['g'], j['p'], j['d'] or 'not dated', j['s'], j['u']])
print(f"DONE {time.time() - T0:.0f}s: {len(jobs)} jobs ({meta['dated']} dated, {meta['nyc']} New York) from {meta['companies']} companies -> {os.path.join(OUT, 'jobs.json')}")

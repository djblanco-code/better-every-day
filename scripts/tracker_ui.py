#!/usr/bin/env python3
"""Local job tracker UI.   python3 scripts/tracker_ui.py   ->  http://127.0.0.1:8787

Reads logs/job-tracker.md (the agent's applied list + your "Apply yourself" list), keeps your pipeline notes in
state/tracker.json, and writes "Applied by me YYYY-MM-DD" back into job-tracker.md so the agent never duplicates it.
Binds to 127.0.0.1 only. No login, no network except the posting you paste (read-only fetch for auto-fill).
"""
import importlib.util
import datetime, hashlib, html, json, os, re, ssl, sys, threading, urllib.parse, urllib.request, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MD = os.path.join(R, 'logs', 'job-tracker.md')
DB = os.path.join(R, 'state', 'tracker.json')
PORT = int(os.environ.get('TRACKER_PORT', '8787'))
def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(R, 'scripts', name + '.py'))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

LOCK = threading.Lock()
CTX = ssl.create_default_context()
STAGES = ['applied', 'intro_call', 'interview', 'final', 'offer', 'ghosted', 'rejected', 'passed']

def today(): return datetime.date.today().isoformat()
def key(url, company='', role=''):
    base = (url or '').split('?')[0].rstrip('/').lower() or (company + role).lower()
    return hashlib.sha1(base.encode()).hexdigest()[:12]

# ----------------------------------------------------------------------------------------------- markdown
def read_md():
    try: return open(MD, encoding='utf-8').read().split('\n')
    except OSError: return []

def cells(line): return [c.strip() for c in line.strip().strip('|').split('|')]

def parse_md():
    """Rows are classified by shape, not by heading: older runs left rows of both kinds in both sections.
    7 columns = applied by the agent; 9 columns = a role you apply to yourself (last column is the status)."""
    agent, mine = [], []
    for i, line in enumerate(read_md()):
        if not re.match(r'^\|\s*20\d\d-\d\d-\d\d', line): continue
        c = cells(line)
        if len(c) >= 9:
            st = c[8]
            mine.append({'date': c[0], 'company': c[1], 'role': c[2], 'location': c[3], 'pay': c[4], 'url': c[5], 'blocker': c[6], 'todo': c[7],
                         'status': st, 'applied': st.lower().startswith('applied by me'), 'skipped': st.lower().startswith('skipped'), 'line': i})
        elif len(c) >= 6:
            agent.append({'date': c[0], 'company': c[1], 'role': c[2], 'location': c[3], 'pay': c[4], 'url': c[5], 'record': c[6] if len(c) > 6 else '', 'line': i})
    return agent, mine

def write_md(lines):
    tmp = MD + '.tmp'
    open(tmp, 'w', encoding='utf-8', newline='\n').write('\n'.join(lines))
    os.replace(tmp, MD)

def set_status(url, status):
    lines = read_md(); hit = False
    for i, line in enumerate(lines):
        if url and url in line and re.match(r'^\|\s*20', line):
            c = cells(line)
            if len(c) >= 9:
                c[8] = status; lines[i] = '| ' + ' | '.join(c) + ' |'; hit = True
    if hit: write_md(lines)
    return hit

def add_manual_row(info):
    """Add a posting the user applied to by hand as an 'Applied by me' row so dupe_check sees it."""
    lines = read_md()
    for i, line in enumerate(lines):
        if line.startswith('## Apply yourself'):
            j = i + 2
            row = '| {d} | {co} | {role} | {loc} | {pay} | {url} | Applied by hand and logged in the tracker UI | none | Applied by me {d} |'.format(
                d=today(), co=info.get('company', ''), role=info.get('role', ''), loc=info.get('location', '') or 'see posting',
                pay=info.get('pay', '') or 'not posted', url=info.get('url', ''))
            lines.insert(j, row); write_md(lines); return True
    return False

# ----------------------------------------------------------------------------------------------- db
def load_db():
    try: return json.load(open(DB, encoding='utf-8'))
    except Exception: return {'items': {}}

def save_db(d):
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    tmp = DB + '.tmp'; json.dump(d, open(tmp, 'w', encoding='utf-8'), indent=1); os.replace(tmp, DB)

# A "search" is a named date window. Starting a new one closes the current window today and opens a fresh one, so
# the Jobs app shows only this search's applications while every older row stays on disk (and in job-tracker.md,
# so the agent's duplicate and lifetime rules still see them). Past searches stay viewable from the picker.
def searches(db):
    L = db.setdefault('searches', [])
    if not L:
        agent, mine = parse_md()
        first = min([a['date'] for a in agent] + [m['date'] for m in mine] + [today()])
        L.append({'id': 's1', 'name': 'Job search 1', 'start': first, 'end': None})
    return L

def start_search(name):
    with LOCK:
        db = load_db(); L = searches(db); d = today()
        for s in L:
            if not s['end']: s['end'] = d
        sid = 's%d' % (len(L) + 1)
        L.append({'id': sid, 'name': (name or '').strip() or 'Job search %d' % (len(L) + 1), 'start': d, 'end': None})
        save_db(db)
    return {'ok': True, 'id': sid}

def rename_search(sid, name):
    with LOCK:
        db = load_db()
        for s in searches(db):
            if s['id'] == sid and name.strip(): s['name'] = name.strip()
        save_db(db)
    return {'ok': True}

def state(sid=None):
    agent, mine = parse_md(); db = load_db(); items = db['items']
    S = searches(db); cur = next(s for s in S if not s['end'])
    view = None if sid == 'all' else next((s for s in S if s['id'] == sid), cur)
    inside = lambda d: view is None or (view['start'] <= d and (not view['end'] or d < view['end']) or (view['end'] and d == view['end'] and view is cur))
    apps = []
    for a in agent:
        k = key(a['url'], a['company'], a['role']); it = items.get(k, {})
        apps.append({**a, 'key': k, 'source': 'agent', 'stage': it.get('stage', 'applied'), 'notes': it.get('notes', ''), 'follow_up': it.get('follow_up', ''),
                     'history': it.get('history', []), 'applied_on': a['date']})
    for m in mine:
        if not m['applied'] and not (key(m['url'], m['company'], m['role']) in items and items[key(m['url'], m['company'], m['role'])].get('manual')): continue
        k = key(m['url'], m['company'], m['role']); it = items.get(k, {})
        d = re.search(r'\d{4}-\d{2}-\d{2}', m['status']);
        apps.append({**m, 'key': k, 'source': 'me', 'stage': it.get('stage', 'applied'), 'notes': it.get('notes', ''), 'follow_up': it.get('follow_up', ''),
                     'history': it.get('history', []), 'applied_on': d.group(0) if d else m['date']})
    seen = {a['key'] for a in apps}
    for k, it in items.items():          # added by link but missing from the md (should be rare)
        if k not in seen and it.get('manual'):
            apps.append({**it.get('info', {}), 'key': k, 'source': 'me', 'stage': it.get('stage', 'applied'), 'notes': it.get('notes', ''),
                         'follow_up': it.get('follow_up', ''), 'history': it.get('history', []), 'applied_on': it.get('applied_on', today())})
    apps = [a for a in apps if inside(a['applied_on'])]
    keys = {a['key'] for a in apps}
    todo = [{**m, 'key': key(m['url'], m['company'], m['role'])} for m in mine if not m['applied'] and not m['skipped'] and inside(m['date'])]
    # assessments and actions are dated, so a past search shows the ones that fell inside its window
    assess = [a for a in db.get('assessments', []) if view is None or view is cur or inside(a.get('invited') or a.get('due') or '')]
    actions = [a for a in db.get('actions', []) if view is None or view is cur or inside(a.get('due') or '')]
    return {'apps': apps, 'todo': todo, 'assessments': assess, 'actions': actions, 'today': today(), 'stages': STAGES,
            'suggestions': [x for x in load_sug() if x.get('status') == 'new'] if (view is None or view is cur) else [],
            'searches': S, 'search': cur['id'], 'viewing': view['id'] if view else 'all'}

SUG = os.path.join(R, 'state', 'gmail_suggestions.json')
def load_sug():
    try: return json.load(open(SUG, encoding='utf-8'))
    except Exception: return []

def set_sug(sid, status):
    with LOCK:
        L = load_sug()
        for x in L:
            if x['id'] == sid: x['status'] = status
        json.dump(L, open(SUG, 'w', encoding='utf-8'), indent=1)

def update_item(k, **kw):
    with LOCK:
        db = load_db(); it = db['items'].setdefault(k, {})
        if 'stage' in kw and kw['stage'] != it.get('stage', 'applied'):
            it.setdefault('history', []).append({'stage': kw['stage'], 'on': today()})
        for f in ('stage', 'notes', 'follow_up'):
            if f in kw: it[f] = kw[f]
        save_db(db)

# ----------------------------------------------------------------------------------------------- link auto-fill
def fetch(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers={'User-Agent': 'Mozilla/5.0 Chrome/128', **(headers or {})})
    with urllib.request.urlopen(req, timeout=25, context=CTX) as r: return r.read().decode('utf-8', 'replace')

def pay_in(text):
    t = html.unescape(re.sub(r'<[^>]+>', ' ', text or ''))
    m = re.search(r'\$\s?(\d{2,3}(?:,\d{3})?)\s?[kK]?\s*(?:-|–|—|to)\s*\$?\s?(\d{2,3}(?:,\d{3})?)\s?[kK]?', t)
    if not m: return ''
    a, b = m.group(1), m.group(2)
    f = lambda x: int(x.replace(',', '')) * (1000 if len(x.replace(',', '')) <= 3 else 1)
    return f'${f(a)//1000}K-${f(b)//1000}K'

def lookup(url):
    u = url.strip(); info = {'url': u, 'company': '', 'role': '', 'location': '', 'pay': '', 'summary': ''}
    host = urllib.parse.urlparse(u).netloc.lower(); path = urllib.parse.urlparse(u).path
    q = urllib.parse.parse_qs(urllib.parse.urlparse(u).query)
    try:
        m = re.search(r'greenhouse\.io/(?:embed/job_app\?for=([^&]+)|([^/]+)/jobs/(\d+))', u)
        gh_board = (m.group(1) or m.group(2)) if m else (q.get('for') or q.get('gh_board') or [None])[0]
        gh_id = (m.group(3) if m else None) or (q.get('gh_jid') or q.get('token') or [None])[0]
        if gh_board and gh_id:
            j = json.loads(fetch(f'https://boards-api.greenhouse.io/v1/boards/{gh_board}/jobs/{gh_id}'))
            info.update(company=j.get('company_name') or gh_board, role=j.get('title', ''), location=(j.get('location') or {}).get('name', ''),
                        pay=pay_in(html.unescape(j.get('content', ''))), summary=re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html.unescape(html.unescape(j.get('content', '')))))[:500])
            info['url'] = j.get('absolute_url') or u; return info
        m = re.search(r'jobs\.ashbyhq\.com/([^/]+)/([0-9a-f-]{36})', u)
        if m:
            d = json.loads(fetch(f'https://api.ashbyhq.com/posting-api/job-board/{urllib.parse.unquote(m.group(1))}?includeCompensation=true'))
            for j in d.get('jobs', []):
                if j.get('id') == m.group(2):
                    comp = (j.get('compensation') or {}).get('compensationTierSummary', '')
                    info.update(company=urllib.parse.unquote(m.group(1)), role=j.get('title', ''), location=j.get('location', ''), pay=pay_in(comp) or comp,
                                summary=(j.get('descriptionPlain') or '')[:500]); return info
        m = re.search(r'jobs\.lever\.co/([^/]+)/([0-9a-f-]{36})', u)
        if m:
            j = json.loads(fetch(f'https://api.lever.co/v0/postings/{m.group(1)}/{m.group(2)}'))
            info.update(company=m.group(1), role=j.get('text', ''), location=(j.get('categories') or {}).get('location', ''),
                        pay=pay_in(j.get('descriptionPlain', '')), summary=(j.get('descriptionPlain') or '')[:500]); return info
    except Exception: pass
    try:
        page = fetch(u)
        for blk in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S):
            try: d = json.loads(blk)
            except Exception: continue
            for j in (d if isinstance(d, list) else d.get('@graph', [d])):
                if isinstance(j, dict) and j.get('@type') == 'JobPosting':
                    loc = j.get('jobLocation') or {}; loc = loc[0] if isinstance(loc, list) and loc else loc
                    addr = (loc.get('address') or {}) if isinstance(loc, dict) else {}
                    sal = ((j.get('baseSalary') or {}).get('value') or {}) if isinstance(j.get('baseSalary'), dict) else {}
                    info.update(company=(j.get('hiringOrganization') or {}).get('name', ''), role=j.get('title', ''),
                                location=', '.join(x for x in (addr.get('addressLocality'), addr.get('addressRegion')) if x) or ('Remote' if j.get('jobLocationType') else ''),
                                pay=(f"${int(sal['minValue'])//1000}K-${int(sal['maxValue'])//1000}K" if sal.get('minValue') and sal.get('maxValue') else pay_in(j.get('description', ''))),
                                summary=re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', j.get('description', ''))))[:500]); return info
        t = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', page) or re.search(r'<title>(.*?)</title>', page, re.S)
        title = html.unescape(t.group(1)).strip() if t else ''
        site = re.search(r'<meta[^>]+property="og:site_name"[^>]+content="([^"]+)"', page)
        parts = re.split(r'\s+[|–—@-]\s+', title)
        info.update(role=parts[0][:100], company=(html.unescape(site.group(1)) if site else (parts[1] if len(parts) > 1 else host.replace('www.', ''))), pay=pay_in(page[:200000]))
    except Exception as e: info['error'] = str(e)[:120]
    return info

# ----------------------------------------------------------------------------------------------- http
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, body, ctype='application/json'):
        b = body if isinstance(body, bytes) else (json.dumps(body) if not isinstance(body, str) else body).encode()
        self.send_response(code); self.send_header('Content-Type', ctype + '; charset=utf-8'); self.send_header('Content-Length', str(len(b)))
        self.send_header('Cache-Control', 'no-store'); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path.startswith('/api/state'):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            return self.send(200, state((q.get('search') or [None])[0]))
        if self.path.startswith('/api/recall/state'):
            try: return self.send(200, load('recall').public_state())
            except Exception as e: return self.send(200, {'error': str(e)[:600]})
        if self.path.startswith('/api/journal'):
            try: return self.send(200, load('journal').journal_state())
            except Exception as e: return self.send(200, {'error': str(e)[:600]})
        if self.path.startswith('/api/network'):
            try: return self.send(200, load('journal').net_state())
            except Exception as e: return self.send(200, {'error': str(e)[:600]})
        if self.path.split('?')[0].rstrip('/') in ('', '/jobs', '/recall', '/network'): return self.send(200, PAGE, 'text/html')
        self.send(404, {'error': 'not found'})
    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0)); body = json.loads(self.rfile.read(n) or b'{}')
        # Same-origin only. '.ts.net' lets `tailscale serve` front this server for your own devices (see docs/HOSTING.md).
        o = self.headers.get('Origin', '')
        if o and not any(x in o for x in ('127.0.0.1', 'localhost', '.ts.net')): return self.send(403, {'error': 'origin'})
        p = self.path
        if p == '/api/lookup': return self.send(200, lookup(body.get('url', '')))
        if p in ('/api/journal', '/api/network'):
            try:
                jn = load('journal'); act = body.get('action')
                if p == '/api/journal': return self.send(200, jn.delete_entry(body) if act == 'delete' else jn.add_entry(body))
                return self.send(200, jn.net_delete(body) if act == 'delete' else jn.net_save(body))
            except Exception as e: return self.send(200, {'error': str(e)[:600]})
        if p == '/api/search':
            if body.get('action') == 'start': return self.send(200, start_search(body.get('name', '')))
            if body.get('action') == 'rename': return self.send(200, rename_search(body.get('id', ''), body.get('name', '')))
            return self.send(400, {'error': 'unknown search action'})
        if p == '/api/suggest':
            if body.get('action') == 'accept':
                update_item(body['key'], stage=body['stage'], notes=body.get('note', ''))
                set_sug(body['id'], 'accepted')
            else: set_sug(body['id'], 'dismissed')
            return self.send(200, {'ok': True})
        if p == '/api/gmail-sync':
            import subprocess
            r = subprocess.run([sys.executable, os.path.join(R, 'scripts', 'gmail_status.py')], capture_output=True, text=True, timeout=300, encoding='utf-8', errors='replace', env={**os.environ, 'PYTHONUTF8': '1'})
            try: return self.send(200, json.loads(r.stdout.strip().splitlines()[-1]))
            except Exception: return self.send(200, {'status': 'error', 'detail': (r.stderr or r.stdout)[-200:]})
        if p.startswith('/api/recall/'):
            try:
                rc = load('recall'); fn = p.split('/')[-1]
                if fn == 'settings': return self.send(200, rc.save_settings(body))
                if fn == 'assess': return self.send(200, rc.assess(body))
                if fn == 'restate': return self.send(200, rc.restate(body))
                if fn == 'test': return self.send(200, rc.test_key(body))
                if fn == 'statement': return self.send(200, rc.statement(body))
                if fn == 'swap': return self.send(200, rc.swap_slot(body))
                if fn == 'done': return self.send(200, rc.mark_done(body))
                if fn == 'minutes': return self.send(200, rc.log_minutes(body))
                if fn == 'program': return self.send(200, rc.set_program(body))
                return self.send(404, {'error': 'unknown recall action'})
            except Exception as e:
                return self.send(200, {'error': str(e)[:600]})
        if p == '/api/action':
            with LOCK:
                db = load_db(); L = db.setdefault('actions', []); act = body.get('action')
                if act == 'add':
                    a = {k: str(body.get(k, '')).strip() for k in ('company', 'text', 'type', 'due', 'note')}
                    a['done'] = False; a['id'] = hashlib.sha1((a['company'] + a['text'] + str(len(L)) + today()).encode()).hexdigest()[:10]; L.append(a)
                else:
                    for a in list(L):
                        if a['id'] == body.get('id'):
                            if act == 'delete': L.remove(a)
                            else:
                                if 'done' in body: a['done'] = bool(body['done'])
                                for f in ('due', 'text', 'note', 'type'):
                                    if f in body: a[f] = str(body[f])
                save_db(db)
            return self.send(200, {'ok': True})
        if p == '/api/assess':
            with LOCK:
                db = load_db(); L = db.setdefault('assessments', []); act = body.get('action')
                if act == 'add':
                    a = {k: str(body.get(k, '')).strip() for k in ('company', 'role', 'platform', 'invited', 'due', 'notes')}
                    a['minutes'] = str(body.get('minutes', '')).strip(); a['status'] = 'todo'
                    a['id'] = hashlib.sha1((a['company'] + a['platform'] + a['invited'] + str(len(L))).encode()).hexdigest()[:10]; L.append(a)
                else:
                    for a in list(L):
                        if a['id'] == body.get('id'):
                            if act == 'delete': L.remove(a)
                            else:
                                for f in ('status', 'due', 'notes', 'platform', 'minutes'):
                                    if f in body: a[f] = str(body[f])
                save_db(db)
            return self.send(200, {'ok': True})
        if p == '/api/item': update_item(body['key'], **{k: body[k] for k in ('stage', 'notes', 'follow_up') if k in body}); return self.send(200, {'ok': True})
        if p == '/api/mark':
            with LOCK:
                url, on = body.get('url', ''), body.get('applied', True)
                set_status(url, f'Applied by me {today()}' if on else 'Open')
                k = body.get('key') or key(url)
                db = load_db(); it = db['items'].setdefault(k, {}); it['manual'] = bool(on); it.setdefault('stage', 'applied')
                if on: it['applied_on'] = today()
                save_db(db)
            return self.send(200, {'ok': True})
        if p == '/api/add':
            info = body; k = key(info.get('url'), info.get('company', ''), info.get('role', ''))
            with LOCK:
                add_manual_row(info)
                db = load_db(); db['items'][k] = {**db['items'].get(k, {}), 'manual': True, 'info': info, 'stage': 'applied', 'applied_on': today(), 'notes': body.get('notes', '')}
                save_db(db)
            return self.send(200, {'ok': True})
        self.send(404, {'error': 'not found'})

PAGE = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tracker_ui.html'), encoding='utf-8').read() if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tracker_ui.html')) else '<h1>tracker_ui.html missing</h1>'

if __name__ == '__main__':
    srv = ThreadingHTTPServer(('127.0.0.1', PORT), H)
    url = f'http://127.0.0.1:{PORT}'; print('Job tracker running at', url, '(Ctrl+C to stop)')
    if '--no-open' not in sys.argv: threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try: srv.serve_forever()
    except KeyboardInterrupt: pass

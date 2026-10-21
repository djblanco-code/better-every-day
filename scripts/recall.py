#!/usr/bin/env python3
"""Recall: interview-prep engine behind the tracker UI's Recall tab.

Banks (tracked, shareable):   data/recall-leetcode.json, data/recall-python.json, data/recall-systemdesign.json
Your progress (gitignored):    state/recall.json      sessions, per-item spaced-repetition state, cached restatements
Your AI key (gitignored):      config/recall.json     {"provider": "anthropic"|"gemini", "model": "...", "api_key": "...", "default_minutes": 25}

The AI only grades what you wrote. Nothing is executed. LeetCode problem text is never copied here; the tab links
to the problem and can ask the model for a short restatement in its own words.
"""
import datetime, json, os, re, threading, urllib.request, urllib.error

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANKS = {'leetcode': 'recall-leetcode.json', 'python': 'recall-python.json', 'system_design': 'recall-systemdesign.json',
         'dsa': 'recall-dsa.json', 'debugging': 'recall-debugging.json'}
CURRICULUM = os.path.join(R, 'data', 'recall-curriculum.json')
STATE = os.path.join(R, 'state', 'recall.json')
CFG = os.path.join(R, 'config', 'recall.json')
LOCK = threading.Lock()
DEFAULT_MODEL = {'anthropic': 'claude-sonnet-5-5', 'gemini': 'gemini-2.5-flash'}

def today(): return datetime.date.today().isoformat()

def _load(p, default):
    try: return json.load(open(p, encoding='utf-8'))
    except Exception: return default

def _save(p, d):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'; json.dump(d, open(tmp, 'w', encoding='utf-8'), indent=1); os.replace(tmp, p)

def cfg(): return _load(CFG, {})
def state(): return _load(STATE, {'sessions': [], 'items': {}, 'restated': {}, 'program': {}, 'plans': {}})

# ---------------------------------------------------------------- banks
_bank_cache = {}
def bank(track):
    path = os.path.join(R, 'data', BANKS[track])
    try: mt = os.path.getmtime(path)
    except OSError: mt = 0
    if track not in _bank_cache or _bank_cache[track].get('_mtime') != mt:   # editing a bank file takes effect without a restart
        d = _load(path, {})
        if track == 'leetcode':
            items = []
            for p in d.get('problems', []):
                comps = sorted(p.get('companies', {}).items(), key=lambda kv: -(kv[1].get('6m', 0) or kv[1].get('all', 0)))
                items.append({'id': p['slug'], 'title': p['title'], 'difficulty': p['difficulty'], 'topic': p['category'] or (p['topics'][0] if p['topics'] else ''),
                              'topics': p['topics'], 'lists': p['lists'], 'url': p['url'], 'companies': [c for c, _ in comps[:12]], 'company_count': len(comps)})
            _bank_cache[track] = {'items': items, 'categories': d.get('categories', []), 'companies': d.get('companies', []),
                                  'company_lists': d.get('company_lists', {}), '_mtime': mt}
        else:
            _bank_cache[track] = {'items': d.get('items', []), 'categories': sorted({i['topic'] for i in d.get('items', [])}), 'companies': [], '_mtime': mt}
    return _bank_cache[track]

def find(track, iid):
    return next((i for i in bank(track)['items'] if i['id'] == iid), None)

def companies_for(track, iid):
    if track != 'leetcode': return []
    d = _load(os.path.join(R, 'data', BANKS['leetcode']), {})
    p = next((p for p in d.get('problems', []) if p['slug'] == iid), None)
    return p.get('companies', {}) if p else {}

# ---------------------------------------------------------------- progress + spaced repetition
def _key(track, iid): return f'{track}:{iid}'

def schedule(item, score):
    """SM-2-lite. 8+ doubles the interval, 5-7 repeats tomorrow, below 5 comes back today."""
    interval = item.get('interval', 0)
    if score >= 8: interval = max(1, interval * 2) if interval else 1
    elif score >= 5: interval = 1
    else: interval = 0
    item['interval'] = interval
    item['next_due'] = (datetime.date.today() + datetime.timedelta(days=interval)).isoformat()

def public_state():
    st = state(); c = cfg()
    sessions = st.get('sessions', [])
    by_day = {}
    for s in sessions:
        d = by_day.setdefault(s['date'], {'date': s['date'], 'count': 0, 'scores': []})
        d['count'] += 1; d['scores'].append(s['score'])
    daily = [{'date': k, 'count': v['count'], 'avg': round(sum(v['scores']) / len(v['scores']), 1)} for k, v in sorted(by_day.items())]
    # streak: consecutive days ending today or yesterday. A mock or real interview logged in the journal counts as a day too.
    days = {d['date'] for d in daily} | {e['date'] for e in st.get('external', [])}; streak = 0; cur = datetime.date.today()
    if cur.isoformat() not in days: cur -= datetime.timedelta(days=1)
    while cur.isoformat() in days: streak += 1; cur -= datetime.timedelta(days=1)
    return {'settings': {'provider': c.get('provider', 'anthropic'), 'model': c.get('model') or DEFAULT_MODEL.get(c.get('provider', 'anthropic')),
                         'has_key': bool(c.get('api_key')), 'default_minutes': int(c.get('default_minutes', 25)), 'company_focus': c.get('company_focus', '')},
            'banks': {t: bank(t) for t in BANKS}, 'items': st.get('items', {}), 'restated': st.get('restated', {}),
            'sessions': sessions[-200:], 'daily': daily, 'streak': streak, 'today': today(), 'external': st.get('external', [])[-100:],
            'plan': plan(st), 'program': program_view(st), 'metrics': metrics(st)}   # plan first: it starts the program on day one

def save_settings(body):
    with LOCK:
        c = cfg()
        for k in ('provider', 'model', 'default_minutes'):
            if k in body and body[k] not in (None, ''): c[k] = body[k]
        if 'company_focus' in body: c['company_focus'] = str(body['company_focus'] or '').strip()   # empty clears it
        if body.get('api_key'): c['api_key'] = str(body['api_key']).strip()   # typed by the user in the UI; never echoed back
        if body.get('clear_key'): c.pop('api_key', None)
        _save(CFG, c)
    return {'ok': True}

# ---------------------------------------------------------------- model calls
# Stability rules for every model call: temperature 0 (same answer, same grade), a JSON schema enforced by the provider
# (Claude tool use / Gemini responseSchema) so there is no prose to parse, retries with backoff on 429/5xx/network blips,
# and a version stamp on every prompt so scores from different months are comparable.
def _call_model(system, user, max_tokens=1800, schema=None):
    c = cfg(); key = c.get('api_key'); prov = c.get('provider', 'anthropic'); model = c.get('model') or DEFAULT_MODEL[prov]
    if not key: raise RuntimeError('No API key saved. Open Settings in the Recall tab and paste your Anthropic or Gemini key.')
    if prov == 'anthropic':
        body = {'model': model, 'max_tokens': max_tokens, 'temperature': 0, 'system': system, 'messages': [{'role': 'user', 'content': user}]}
        if schema:
            body['tools'] = [{'name': 'emit', 'description': 'Return the result.', 'input_schema': schema}]
            body['tool_choice'] = {'type': 'tool', 'name': 'emit'}
        req = urllib.request.Request('https://api.anthropic.com/v1/messages', method='POST',
            headers={'content-type': 'application/json', 'x-api-key': key, 'anthropic-version': '2023-06-01'}, data=json.dumps(body).encode())
        out = _http(req)
        if schema:
            tu = next((b for b in out.get('content', []) if b.get('type') == 'tool_use'), None)
            if tu: return tu['input']
        return ''.join(b.get('text', '') for b in out.get('content', []))
    if prov == 'gemini':
        gen = {'maxOutputTokens': max_tokens, 'temperature': 0}
        if schema: gen['responseMimeType'] = 'application/json'; gen['responseSchema'] = _gemini_schema(schema)
        req = urllib.request.Request(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent', method='POST',
            headers={'content-type': 'application/json', 'x-goog-api-key': key},
            data=json.dumps({'system_instruction': {'parts': [{'text': system}]}, 'contents': [{'role': 'user', 'parts': [{'text': user}]}], 'generationConfig': gen}).encode())
        out = _http(req); txt = ''.join(p.get('text', '') for p in out.get('candidates', [{}])[0].get('content', {}).get('parts', []))
        return json.loads(txt) if schema else txt
    raise RuntimeError(f'Unknown provider {prov}')

def _gemini_schema(s):
    """Gemini's schema dialect: no additionalProperties, enums ok, nullable via 'nullable'."""
    if isinstance(s, dict):
        o = {k: _gemini_schema(v) for k, v in s.items() if k not in ('additionalProperties',)}
        if isinstance(o.get('type'), list):          # ["integer","null"] -> integer, nullable
            o['nullable'] = 'null' in o['type']; o['type'] = next(t for t in o['type'] if t != 'null')
        return o
    if isinstance(s, list): return [_gemini_schema(x) for x in s]
    return s

def _http(req, tries=3):
    import time
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=120) as r: return json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', 'replace')[:400]
            if e.code in (408, 409, 429, 500, 502, 503, 504, 529) and i < tries - 1: time.sleep(2 ** (i + 1)); continue
            raise RuntimeError(f'Model API error {e.code}: {body}')
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if i < tries - 1: time.sleep(2 ** (i + 1)); continue
            raise RuntimeError(f'Could not reach the model API: {str(e)[:200]}')

def _json_in(text):
    """Fallback only, for a provider path that returned text instead of a structured object."""
    if isinstance(text, dict): return text
    m = re.search(r'\{.*\}', text, re.S)
    if not m: raise RuntimeError('The model did not return JSON. Raw: ' + text[:300])
    return json.loads(m.group(0))

def _call_json(system, user, schema, max_tokens=1800):
    return _json_in(_call_model(system, user, max_tokens, schema=schema))

GRADER_VERSION = 2
_S10 = {'type': 'integer', 'minimum': 0, 'maximum': 10}
GRADE_SCHEMA = {'type': 'object', 'additionalProperties': False,
    'properties': {'score': _S10, 'correctness': _S10, 'complexity': _S10, 'code_quality': _S10, 'communication': _S10,
                   'verdict': {'type': 'string'}, 'strengths': {'type': 'array', 'items': {'type': 'string'}}, 'gaps': {'type': 'array', 'items': {'type': 'string'}},
                   'next_step': {'type': 'string'}, 'model_outline': {'type': 'string'}},
    'required': ['score', 'correctness', 'complexity', 'code_quality', 'communication', 'verdict', 'strengths', 'gaps', 'next_step', 'model_outline']}
BANDS = """Score bands (apply them the same way every time): 9-10 = strong hire, correct, optimal, clearly explained; 7-8 = hire, correct with minor gaps;
5-6 = borderline, works on the main case but misses edge cases or complexity; 3-4 = no hire, wrong approach or major bug; 0-2 = empty, off-topic, or no attempt.
Grade the same answer the same way regardless of how it is phrased. Do not reward length."""

GRADER = """You are a strict but fair senior engineer grading a candidate's interview answer. You never run code; you read it.
Return ONLY a JSON object with these keys:
"score": integer 0-10 overall (10 = would clearly pass a strong interview on this question),
"correctness": 0-10, "complexity": 0-10 (time/space analysis stated and right; for design questions use this for scalability reasoning),
"code_quality": 0-10 (clarity, naming, structure; for design questions use this for structure of the write-up),
"communication": 0-10 (explained approach, trade-offs, edge cases),
"verdict": one sentence,
"strengths": [2-4 short bullets],
"gaps": [2-5 short bullets of concrete mistakes or omissions, with the fix],
"next_step": one sentence on what to practice next,
"model_outline": a compact outline of a strong answer (no more than 12 lines; for code questions include the approach and complexity, not a full solution).
Be specific. Quote the candidate's own lines when pointing at a bug. If the answer is empty or off-topic, score it 0-2 and say so."""

DEBUG_GRADER = """You are a senior engineer grading how a candidate DEBUGGED a short Python script. You never run code; you read it.
Grade the debugging process as much as the answer. A strong answer: (1) restates the symptom and forms a hypothesis, (2) explains how to reproduce or isolate it
(a print, a minimal case, a bisect, a tool like pdb/tracemalloc/cProfile), (3) names the ROOT CAUSE precisely, quoting the line, (4) gives a correct fix,
(5) says how to prevent a recurrence (test, lint rule, type hint, invariant). Return ONLY a JSON object with these keys:
"score": integer 0-10 overall,
"correctness": 0-10 (root cause identified and right),
"complexity": 0-10 (the method: hypothesis, reproduce, isolate, confirm; use this key for process quality),
"code_quality": 0-10 (the fix is correct, minimal and idiomatic),
"communication": 0-10 (clear, ordered, says what was checked and why),
"verdict": one sentence,
"strengths": [2-4 short bullets],
"gaps": [2-5 short bullets of what was missed, with the fix],
"next_step": one sentence on what debugging habit to practice next,
"model_outline": a compact outline of a strong diagnosis (symptom -> hypothesis -> how to confirm -> root cause -> fix -> prevention; no more than 12 lines).
If the candidate only pasted a fixed script with no reasoning, cap the score at 5 and say why."""

def assess(body):
    track, iid = body['track'], body['id']
    item = find(track, iid)
    if not item: raise RuntimeError('Unknown problem')
    answer = (body.get('answer') or '').strip()
    if track == 'leetcode':
        q = f"LeetCode problem: {item['title']} ({item['difficulty']}; topics: {', '.join(item['topics'])}). URL: {item['url']}. You know this problem; grade against its real statement and constraints."
    elif track == 'debugging':
        q = f"Debugging exercise: {item['title']}\nSymptom reported: {item['symptom']}\nScript:\n```python\n{item['prompt']}\n```\nWhat a strong diagnosis contains: {item.get('rubric','')}"
    else:
        q = f"Question: {item['title']}\n{item['prompt']}\nRubric for a strong answer: {item.get('rubric','')}"
    user = f"{q}\n\nTime allowed: {body.get('timer_minutes', 25)} min. Time used: {body.get('minutes_used', '?')} min.\n\nCANDIDATE ANSWER (not executed):\n```\n{answer[:12000]}\n```"
    g = _call_json((DEBUG_GRADER if track == 'debugging' else GRADER) + '\n' + BANDS, user, GRADE_SCHEMA)
    def num(k):
        try: return max(0, min(10, int(round(float(g.get(k, 0))))))
        except Exception: return 0
    sess = {'id': f"{today()}-{int(datetime.datetime.now().timestamp())}", 'date': today(), 'time': datetime.datetime.now().strftime('%H:%M'),
            'track': track, 'item': iid, 'title': item['title'], 'difficulty': item.get('difficulty', ''), 'topic': item.get('topic', ''),
            'minutes_used': body.get('minutes_used'), 'timer_minutes': body.get('timer_minutes'), 'score': num('score'),
            'sub': {k: num(k) for k in ('correctness', 'complexity', 'code_quality', 'communication')},
            'verdict': str(g.get('verdict', '')), 'strengths': [str(x) for x in g.get('strengths', [])][:5], 'gaps': [str(x) for x in g.get('gaps', [])][:6],
            'next_step': str(g.get('next_step', '')), 'model_outline': str(g.get('model_outline', '')), 'answer': answer[:12000],
            'grader': GRADER_VERSION, 'model': cfg().get('model') or DEFAULT_MODEL.get(cfg().get('provider', 'anthropic'))}
    with LOCK:
        st = state(); st.setdefault('sessions', []).append(sess)
        it = st.setdefault('items', {}).setdefault(_key(track, iid), {'attempts': 0, 'best': 0, 'interval': 0})
        it['attempts'] += 1; it['best'] = max(it['best'], sess['score']); it['last'] = sess['score']; it['last_date'] = today()
        schedule(it, sess['score']); _save(STATE, st)
    return sess

RESTATER = """Restate the given LeetCode problem in your own words for a candidate who will solve it from memory. Do not quote LeetCode's text.
Give: one paragraph describing the task, the input/output shape, 2 small examples you invent yourself, the key constraints (sizes, value ranges) as you recall them, and the follow-up if the problem is known to have one. Plain text, under 180 words. No hints about the solution."""

def restate(body):
    track, iid = body['track'], body['id']
    st = state()
    if iid in st.get('restated', {}): return {'text': st['restated'][iid], 'cached': True}
    item = find(track, iid)
    text = _call_model(RESTATER, f"Problem: {item['title']} ({item['difficulty']}; topics: {', '.join(item['topics'])}). URL: {item['url']}", 600).strip()
    with LOCK:
        st = state(); st.setdefault('restated', {})[iid] = text; _save(STATE, st)
    return {'text': text, 'cached': False}

STATEMENTS = os.path.join(R, 'state', 'recall-statements')
PREMIUM = os.path.join(R, 'data', 'recall-premium-statements.json')

def _as_list(v):
    if isinstance(v, list): return v
    if isinstance(v, str) and v.strip().startswith('['):
        try:
            import ast; return ast.literal_eval(v)
        except Exception: return []
    return []

def statement(body):
    """Problem statement for a session. LeetCode: the user's local copy of the open leetcode-problems dataset
    (state/recall-statements/<slug>.json, gitignored) or our own wording for premium-only problems.
    Python/System Design: the bank's own prompt."""
    track, iid = body['track'], body['id']
    if track == 'debugging':
        it = find(track, iid)
        if not it: return {'text': '', 'format': 'text'}
        txt = '**Symptom.** ' + it['symptom'] + chr(10) * 2 + '```' + chr(10) + it['prompt'].rstrip() + chr(10) + '```' + chr(10) * 2 + \
              'Write your diagnosis: what you suspect, how you would confirm it, the root cause, the fix, and how you would keep it from coming back.'
        return {'text': txt, 'format': 'markdown'}
    if track != 'leetcode':
        it = find(track, iid); return {'text': it['prompt'] if it else '', 'format': 'text'}
    d = _load(os.path.join(STATEMENTS, f'{iid}.json'), None)
    if not d:
        prem = _load(PREMIUM, {}).get(iid)
        return {'text': prem, 'format': 'markdown'} if prem else {'text': '', 'format': 'text', 'missing': True}
    txt = (d.get('description') or d.get('content') or '').replace(chr(160), ' ').strip()
    txt = re.sub(r'(?:\s*(?:Example \d+:|Constraints:|Follow-?up:?)\s*)+$', '', txt).strip()   # dataset left empty section headers behind
    parts = [txt]
    for i, e in enumerate(_as_list(d.get('examples'))):
        et = e.get('example_text', '') if isinstance(e, dict) else str(e)
        parts.append('Example %d:' % (i + 1) + chr(10) + et.strip())
    cons = _as_list(d.get('constraints'))
    sup = lambda c: re.sub(r'(?<![\d.])10(10|[4-9])(?!\d)', lambda m: '10^' + m.group(1), str(c))   # flattened exponents: 104 -> 10^4
    if cons: parts.append('Constraints:' + chr(10) + chr(10).join('- ' + sup(c) for c in cons))
    return {'text': (chr(10) * 2).join(p for p in parts if p), 'format': 'markdown'}

def test_key(body=None):
    txt = _call_model('Reply with the single word OK.', 'ping', 10)
    return {'ok': 'OK' in txt.upper(), 'reply': txt[:40]}

# ---------------------------------------------------------------- 6-month program: today's plan, recommender, metrics
# Principles (see data/recall-curriculum.json "principles"): spaced repetition, retrieval practice, interleaving,
# deliberate practice on the weakest category, 25-minute time-boxing, mastery gating at 3 strong scores per category.
DAILY_MIN = 60
SLOT_MIN = 25
MASTER_N = 3
ROTATION = ['python', 'system_design', 'dsa', 'debugging']   # the second daily slot cycles through these
DIFF_W = {'Easy': 1, 'Medium': 2, 'Hard': 3}

def curriculum(): return _load(CURRICULUM, {'weeks': [], 'program_weeks': 26, 'daily_minutes': DAILY_MIN, 'principles': []})

def _prog(st): return st.setdefault('program', {})

def week_no(st, d=None):
    s = _prog(st).get('start')
    if not s: return 1
    days = (datetime.date.fromisoformat(d or today()) - datetime.date.fromisoformat(s)).days
    return max(1, min(len(curriculum()['weeks']) or 26, days // 7 + 1))

def week_of(n): return next((w for w in curriculum()['weeks'] if w['week'] == n), None)

def mastery(st, track):
    """Per category: total, attempted, strong (best 8+), mastered flag, avg best."""
    items = st.get('items', {}); out = {}
    for it in bank(track)['items']:
        c = out.setdefault(it.get('topic') or '', {'total': 0, 'attempted': 0, 'strong': 0, 'scores': []})
        c['total'] += 1
        p = items.get(_key(track, it['id']))
        if p and p.get('attempts'):
            c['attempted'] += 1; c['scores'].append(p.get('best', 0))
            if p.get('best', 0) >= 8: c['strong'] += 1
    for c in out.values():
        c['mastered'] = c['strong'] >= min(MASTER_N, c['total'])
        c['avg'] = round(sum(c['scores']) / len(c['scores']), 1) if c['scores'] else None
        c.pop('scores')
    return out

def readiness(st, track):
    """0-100. 70% difficulty-weighted coverage of strong (8+) items, 30% average of the last 10 scores.
    LeetCode coverage is measured against NeetCode 150 so the denominator is reachable in 6 months."""
    items = st.get('items', {}); B = bank(track)['items']
    if track == 'leetcode': B = [i for i in B if 'neetcode150' in (i.get('lists') or [])] or B
    tot = sum(DIFF_W.get(i.get('difficulty'), 2) for i in B) or 1
    strong = sum(DIFF_W.get(i.get('difficulty'), 2) for i in B if items.get(_key(track, i['id']), {}).get('best', 0) >= 8)
    recent = [s['score'] for s in st.get('sessions', []) if s['track'] == track][-10:]
    avg = sum(recent) / len(recent) if recent else 0
    return round(70 * strong / tot + 30 * avg / 10)

def recommend(st, track, exclude=(), d=None):
    """Pick the next item for a track. Tiers: due reviews (weakest first) > new in this week's focus category >
    new in the earliest unmastered roadmap category > attempted but weak > everything else. Difficulty steps up as a
    category gets strong scores, and a category practised yesterday is pushed down unless it is due (interleaving)."""
    d = d or today(); items = st.get('items', {}); B = [i for i in bank(track)['items'] if i['id'] not in set(exclude)]
    if not B: return None
    yday = (datetime.date.fromisoformat(d) - datetime.timedelta(days=1)).isoformat()
    recent = {s.get('topic') for s in st.get('sessions', []) if s['track'] == track and s['date'] in (d, yday)}
    wk = week_of(week_no(st, d)) or {}
    focus = (wk.get('focus') or {}).get(track, '')
    mast = mastery(st, track)
    road = list(bank(track)['categories'])
    # an active interview loop beats the curriculum: the company's last-30-days list, most frequent first
    focus_co = cfg().get('company_focus', '') if track == 'leetcode' else ''
    crank = {s: n for n, s in enumerate(bank('leetcode').get('company_lists', {}).get(focus_co, []))} if focus_co else {}
    def diff_rank(i):
        m = mast.get(i.get('topic') or '', {}); s = m.get('strong', 0)
        order = ['Medium', 'Hard', 'Easy'] if s >= 2 else ['Medium', 'Easy', 'Hard'] if (s >= 1 or m.get('attempted', 0) >= 2) else ['Easy', 'Medium', 'Hard']
        return order.index(i.get('difficulty')) if i.get('difficulty') in order else 3
    def road_rank(i):
        cat = i.get('topic') or ''
        unm = [c for c in road if not mast.get(c, {}).get('mastered')]
        return unm.index(cat) if cat in unm else len(road) + (road.index(cat) if cat in road else 99)
    def key(n_i):
        n, i = n_i; p = items.get(_key(track, i['id']), {}); cat = i.get('topic') or ''
        attempted = bool(p.get('attempts')); due = attempted and p.get('next_due') and p['next_due'] <= d
        pref150 = 0 if (track != 'leetcode' or 'neetcode150' in (i.get('lists') or [])) else 1
        if due: tier, sub = 0, (p.get('best', 0), n)
        elif not attempted and i['id'] in crank: tier, sub = 1, (crank[i['id']], n)
        elif not attempted and cat == focus: tier, sub = 1.2, (pref150, diff_rank(i), n)
        elif not attempted: tier, sub = 2, (road_rank(i), pref150, diff_rank(i), n)
        elif p.get('best', 0) < 8: tier, sub = 3, (p.get('best', 0), n)
        else: tier, sub = 4, (p.get('next_due') or '', n)
        if tier and cat in recent: tier += 0.5
        return (tier, sub)
    n, best = min(enumerate(B), key=key)
    p = items.get(_key(track, best['id']), {}); cat = best.get('topic') or ''
    is_due = bool(p.get('attempts') and p.get('next_due') and p['next_due'] <= d)
    if is_due: why = 'Due for review (best %s/10)' % p.get('best', 0)
    elif not p.get('attempts') and best['id'] in crank: why = "#%d on %s's last-30-days list" % (crank[best['id']] + 1, focus_co)
    elif not p.get('attempts') and cat == focus: why = "This week's focus: %s" % focus
    elif not p.get('attempts'): why = 'New, in your weakest category: %s' % cat
    elif p.get('best', 0) < 8: why = 'Below 8 last time (%s/10), try again' % p.get('best', 0)
    else: why = 'Keeping a strong topic warm'
    return {'id': best['id'], 'title': best['title'], 'difficulty': best.get('difficulty', ''), 'topic': cat, 'why': why}

def _due_count(st, track, d):
    return sum(1 for k, v in st.get('items', {}).items() if k.startswith(track + ':') and v.get('next_due') and v['next_due'] <= d)

def _second_track(st, d):
    """Rotate the second slot: most due reviews wins, else the lowest readiness, never the same track two days running."""
    prev = None
    for pd, pl in sorted(st.get('plans', {}).items()):
        if pd < d:
            for s in pl.get('slots', []):
                if s.get('kind') == 'practice' and s.get('track') in ROTATION: prev = s['track']
    cands = [t for t in ROTATION if t != prev] or ROTATION
    due = {t: _due_count(st, t, d) for t in cands}
    top = max(cands, key=lambda t: due[t])
    if due[top] > 0: return top, 'has %d review%s due' % (due[top], '' if due[top] == 1 else 's')
    t = min(cands, key=lambda t: (readiness(st, t), ROTATION.index(t)))
    return t, 'your lowest readiness (%d%%)' % readiness(st, t)

def _third_slot(st, d):
    """First unfinished reading of the current week, else first unfinished homework, else next week's first reading."""
    done = _prog(st).get('done', {}); n = week_no(st, d)
    for wn in (n, n + 1):
        w = week_of(wn)
        if not w: continue
        for kind in ('reading', 'homework'):
            for r in w.get(kind, []):
                if r['id'] not in done:
                    return {'kind': kind, 'id': r['id'], 'week': wn, 'minutes': int(r.get('est_min', 20)),
                            'title': r.get('what') or r.get('text'), 'book': r.get('book', ''), 'track': r.get('track', '')}
    return None

def build_plan(st, d=None):
    d = d or today(); pr = _prog(st)
    if not pr.get('start'): pr['start'] = d
    lc = recommend(st, 'leetcode', d=d)
    t2, why2 = _second_track(st, d); it2 = recommend(st, t2, d=d)
    slots = [{'kind': 'practice', 'track': 'leetcode', 'minutes': SLOT_MIN, **(lc or {})},
             {'kind': 'practice', 'track': t2, 'minutes': SLOT_MIN, 'track_why': why2, **(it2 or {})}]
    third = _third_slot(st, d)
    if third: slots.append(third)
    return {'date': d, 'week': week_no(st, d), 'slots': slots, 'generated': datetime.datetime.now().strftime('%H:%M')}

def plan(st, d=None):
    """Today's plan is generated once and stays put all day, so it does not shift under you. Completion is derived live."""
    d = d or today(); plans = st.setdefault('plans', {})
    if d not in plans:
        with LOCK:
            st2 = state(); plans2 = st2.setdefault('plans', {})
            if d not in plans2:
                plans2[d] = build_plan(st2, d)
                for k in sorted(plans2)[:-60]: plans2.pop(k)   # keep two months of plans
                _save(STATE, st2)
            st.update(st2); plans = st['plans']
    p = json.loads(json.dumps(plans[d])); done = _prog(st).get('done', {})
    todays = [s for s in st.get('sessions', []) if s['date'] == d]
    for s in p['slots']:
        if s['kind'] == 'practice':
            hit = [x for x in todays if x['track'] == s['track'] and x['item'] == s.get('id')]
            alt = [x for x in todays if x['track'] == s['track']]
            s['done'] = bool(hit or alt); s['score'] = (hit or alt)[-1]['score'] if (hit or alt) else None
            s['substituted'] = bool(alt and not hit)
        else:
            s['done'] = s['id'] in done
    p['minutes_planned'] = sum(s.get('minutes', 0) for s in p['slots'])
    p['minutes_done'] = _minutes_on(st, d)
    p['target'] = curriculum().get('daily_minutes', DAILY_MIN)
    p['complete'] = all(s['done'] for s in p['slots'])
    return p

def _minutes_on(st, d):
    m = sum(float(s.get('minutes_used') or 0) for s in st.get('sessions', []) if s['date'] == d)
    m += float(_prog(st).get('minutes', {}).get(d, 0))
    m += sum(float(e.get('minutes') or 0) for e in st.get('external', []) if e['date'] == d)
    return round(m, 1)

# ---------------------------------------------------------------- real reps: mocks, interviews, study logged from the journal
def log_external(rec):
    """A mock interview, a real interview, or study done outside Recall. Counts toward minutes, streak and the metrics."""
    with LOCK:
        st = state(); L = st.setdefault('external', [])
        L[:] = [e for e in L if e.get('id') != rec.get('id')]
        try: rec['rating'] = max(1, min(10, int(rec['rating']))) if rec.get('rating') is not None else None
        except Exception: rec['rating'] = None
        try: rec['minutes'] = int(rec['minutes']) if rec.get('minutes') is not None else None
        except Exception: rec['minutes'] = None
        L.append(rec); _save(STATE, st)
    return {'ok': True}

def delete_external(body):
    with LOCK:
        st = state(); st['external'] = [e for e in st.get('external', []) if e.get('entry') != body.get('entry') and e.get('id') != body.get('id')]; _save(STATE, st)
    return {'ok': True}

def external_summary(st):
    L = st.get('external', []); cut = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    mocks = [e for e in L if e['kind'] == 'mock_interview']; real = [e for e in L if e['kind'] == 'interview']
    avg = lambda xs: round(sum(x['rating'] for x in xs if x.get('rating')) / max(1, len([x for x in xs if x.get('rating')])), 1) if any(x.get('rating') for x in xs) else None
    return {'mocks': len(mocks), 'mocks_30d': len([m for m in mocks if m['date'] >= cut]), 'mock_avg': avg(mocks),
            'interviews': len(real), 'interviews_30d': len([r for r in real if r['date'] >= cut]), 'interview_avg': avg(real)}

def swap_slot(body):
    """Replace one practice slot's problem with the next recommendation (excluding what was there)."""
    d = today(); n = int(body.get('slot', 0))
    with LOCK:
        st = state(); p = st.setdefault('plans', {}).get(d) or build_plan(st, d); st['plans'][d] = p
        s = p['slots'][n]
        if s['kind'] != 'practice': raise RuntimeError('Only practice slots can be swapped')
        ex = set(s.get('skipped', [])) | {s.get('id')}
        r = recommend(st, s['track'], exclude=ex, d=d)
        if not r: raise RuntimeError('Nothing else in this track')
        s.update(r); s['skipped'] = sorted(x for x in ex if x)
        _save(STATE, st)
    return plan(state(), d)

def mark_done(body):
    """Tick a reading or homework item (minutes count toward today) or untick it."""
    iid = body['id']; mins = int(body.get('minutes') or 0); d = today()
    with LOCK:
        st = state(); pr = _prog(st); done = pr.setdefault('done', {}); mn = pr.setdefault('minutes', {})
        if body.get('undo'):
            old = done.pop(iid, None)
            if old: mn[old['date']] = max(0, float(mn.get(old['date'], 0)) - float(old.get('minutes', 0)))
        else:
            if iid in done: return {'ok': True}
            done[iid] = {'date': d, 'minutes': mins}; mn[d] = float(mn.get(d, 0)) + mins
        _save(STATE, st)
    return {'ok': True}

def log_minutes(body):
    """Extra study minutes outside a graded session (a textbook hour, a mock interview)."""
    mins = int(body.get('minutes') or 0); d = today()
    with LOCK:
        st = state(); mn = _prog(st).setdefault('minutes', {}); mn[d] = float(mn.get(d, 0)) + mins; _save(STATE, st)
    return {'ok': True}

def set_program(body):
    with LOCK:
        st = state(); pr = _prog(st)
        if body.get('start'): datetime.date.fromisoformat(body['start']); pr['start'] = body['start']
        if body.get('reset_plan'): st.get('plans', {}).pop(today(), None)
        _save(STATE, st)
    return {'ok': True}

def program_view(st):
    c = curriculum(); n = week_no(st); done = _prog(st).get('done', {})
    weeks = []
    for w in c['weeks']:
        r = w.get('reading', []); h = w.get('homework', [])
        weeks.append({**w, 'reading_done': sum(1 for x in r if x['id'] in done), 'homework_done': sum(1 for x in h if x['id'] in done)})
    start = _prog(st).get('start')
    return {'start': start, 'week': n, 'of': len(c['weeks']), 'phase': (week_of(n) or {}).get('phase', 'learn'),
            'daily_minutes': c.get('daily_minutes', DAILY_MIN), 'principles': c.get('principles', []), 'weeks': weeks, 'done': done,
            'end': (datetime.date.fromisoformat(start) + datetime.timedelta(weeks=len(c['weeks']))).isoformat() if start else None}

def metrics(st):
    d0 = datetime.date.today(); sessions = st.get('sessions', [])
    target = curriculum().get('daily_minutes', DAILY_MIN)
    days = []
    for i in range(29, -1, -1):
        d = (d0 - datetime.timedelta(days=i)).isoformat(); m = _minutes_on(st, d)
        days.append({'date': d, 'minutes': m, 'sessions': sum(1 for s in sessions if s['date'] == d), 'hit': m >= target})
    adh = lambda n: round(100 * sum(1 for x in days[-n:] if x['hit']) / n)
    rd = {t: readiness(st, t) for t in BANKS}
    weights = {'leetcode': 0.4, 'python': 0.15, 'system_design': 0.2, 'dsa': 0.15, 'debugging': 0.1}
    overall = round(sum(rd[t] * weights[t] for t in BANKS))
    last20 = sessions[-20:]
    under = round(100 * sum(1 for s in last20 if s.get('minutes_used') is not None and s.get('timer_minutes') and float(s['minutes_used']) <= float(s['timer_minutes']) and s['score'] >= 7) / len(last20)) if last20 else None
    cut14 = (d0 - datetime.timedelta(days=14)).isoformat(); cut28 = (d0 - datetime.timedelta(days=28)).isoformat()
    a = [s['score'] for s in sessions if s['date'] >= cut14]; b = [s['score'] for s in sessions if cut28 <= s['date'] < cut14]
    trend = round((sum(a) / len(a)) - (sum(b) / len(b)), 1) if a and b else None
    # one readiness snapshot per day, so the 6-month curve is real history and not a recomputation
    snaps = _prog(st).get('snapshots', {})
    if snaps.get(d0.isoformat()) != overall:
        with LOCK:
            st2 = state(); sn = _prog(st2).setdefault('snapshots', {}); sn[d0.isoformat()] = overall; _save(STATE, st2); snaps = sn
    all_min = sum(float(s.get('minutes_used') or 0) for s in sessions) + sum(float(v) for v in _prog(st).get('minutes', {}).values())
    active = len({s['date'] for s in sessions} | {k for k, v in _prog(st).get('minutes', {}).items() if v})
    return {'target': target, 'today_minutes': days[-1]['minutes'], 'days': days, 'adherence_7': adh(7), 'adherence_30': adh(30),
            'total_hours': round(all_min / 60, 1), 'days_active': active, 'readiness': rd, 'readiness_overall': overall,
            'mastery': {t: mastery(st, t) for t in BANKS}, 'under_time_rate': under, 'trend_14d': trend, 'reps': external_summary(st),
            'snapshots': [{'date': k, 'readiness': v} for k, v in sorted(snaps.items())][-200:]}

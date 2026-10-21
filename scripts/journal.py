#!/usr/bin/env python3
"""Daily journal + networking behind the Better Every Day home page.

You tell it what happened today (typed or dictated): a job fair, people you met, a mock interview, a real interview.
If a Recall API key is saved, the note is parsed into structured items with the model; otherwise the note is kept raw.
  state/journal.json   entries [{id, date, time, text, summary, items:[...]}]
  state/network.json   {people:[...], events:[...]}        (both gitignored)
Mock and real interviews are also logged into Recall (state/recall.json "external"), so they count toward the day.
"""
import datetime, hashlib, importlib.util, json, os, threading, uuid

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOURNAL = os.path.join(R, 'state', 'journal.json')
NET = os.path.join(R, 'state', 'network.json')
LOCK = threading.Lock()

def _recall():
    spec = importlib.util.spec_from_file_location('recall', os.path.join(R, 'scripts', 'recall.py'))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def today(): return datetime.date.today().isoformat()
def _load(p, d):
    try: return json.load(open(p, encoding='utf-8'))
    except Exception: return d
def _save(p, d):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    t = p + '.tmp'; json.dump(d, open(t, 'w', encoding='utf-8'), indent=1); os.replace(t, p)
def _id(*parts): return hashlib.sha1(('|'.join(map(str, parts)) + uuid.uuid4().hex).encode()).hexdigest()[:10]   # the clock alone collides on Windows

def journal(): return _load(JOURNAL, {'entries': []})
def network(): return _load(NET, {'people': [], 'events': []})

PARSER = """You turn a job-seeker's end-of-day note into structured items. Return ONLY a JSON object:
{"summary": one sentence in the second person ("You did ..."),
 "items": [ ... ]}
Each item is one of:
 {"type":"mock_interview","with":who or where,"format":"coding|system design|behavioral|mixed","rating":1-10,"minutes":int or null,"notes":short}
 {"type":"interview","company":name,"stage":"phone screen|technical|onsite|final|other","rating":1-10,"minutes":int or null,"notes":short}
 {"type":"event","name":event name,"kind":"job fair|meetup|conference|info session|other","org":host if known,"notes":short}
 {"type":"person","name":full name or best guess,"company":company or "","role":role or "","relationship":"contact|mentor|recruiter|peer","met_at":event or context,"how_they_can_help":one phrase,"follow_up":what to do next or ""}
 {"type":"study","what":short,"minutes":int or null}
 {"type":"other","notes":short}
Rating words: aced/crushed/nailed = 9, went well/good = 8, okay/fine/decent = 6, rough/bad/bombed = 3. Use null for unknown minutes.
Every item has a "date": today unless the note says yesterday, a weekday, or a date. Apply these rules the same way every time.
"three people" with no names = three person items named "Person 1/2/3" with met_at set. Never invent companies or names that are not implied. Keep every string under 120 characters."""

PARSER_VERSION = 2
_STR = {'type': 'string'}
_NINT = {'type': ['integer', 'null']}
JOURNAL_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['summary', 'items'],
    'properties': {'summary': _STR, 'items': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False, 'required': ['type', 'date'],
        'properties': {'type': {'type': 'string', 'enum': ['mock_interview', 'interview', 'event', 'person', 'study', 'other']},
                       'date': {'type': 'string', 'description': 'YYYY-MM-DD the item happened; today unless the note says yesterday or a date'},
                       'with': _STR, 'format': _STR, 'rating': _NINT, 'minutes': _NINT, 'notes': _STR,
                       'company': _STR, 'stage': _STR, 'name': _STR, 'kind': _STR, 'org': _STR, 'role': _STR,
                       'relationship': {'type': 'string', 'enum': ['contact', 'mentor', 'recruiter', 'peer']},
                       'met_at': _STR, 'how_they_can_help': _STR, 'follow_up': _STR, 'what': _STR}}}}}

def _parse(text, date):
    rc = _recall()
    if not rc.cfg().get('api_key'): return None, []
    g = rc._call_json(PARSER, 'Today is %s (%s).\n\nNote:\n%s' % (date, datetime.date.fromisoformat(date).strftime('%A'), text), JOURNAL_SCHEMA, 1500)
    items = [i for i in g.get('items', []) if isinstance(i, dict) and i.get('type')]
    for i in items:
        try: datetime.date.fromisoformat(i.get('date', ''))
        except Exception: i['date'] = date
    return str(g.get('summary', '')), items[:20]

def add_entry(body):
    text = (body.get('text') or '').strip()
    if len(text) < 3: raise RuntimeError('Say or type what happened first.')
    date = body.get('date') or today()
    try: summary, items = _parse(text, date)
    except Exception as e: summary, items = None, []; err = str(e)[:200]
    else: err = ''
    eid = _id('j', text)
    entry = {'id': eid, 'date': date, 'time': datetime.datetime.now().strftime('%H:%M'), 'text': text, 'summary': summary, 'items': items, 'parse_error': err, 'parser': PARSER_VERSION}
    with LOCK:
        j = journal(); j['entries'].append(entry); _save(JOURNAL, j)
        n = network()
        for it in items:
            it['id'] = _id('i', eid); it['entry'] = eid; idate = it.get('date') or date
            if it['type'] == 'person':
                n['people'].append({'id': it['id'], 'entry': eid, 'date': idate, 'name': it.get('name', ''), 'company': it.get('company', ''), 'role': it.get('role', ''),
                                    'relationship': it.get('relationship', 'contact'), 'met_at': it.get('met_at', ''), 'how_they_can_help': it.get('how_they_can_help', ''),
                                    'follow_up': it.get('follow_up', ''), 'follow_up_done': False, 'notes': ''})
            elif it['type'] == 'event':
                n['events'].append({'id': it['id'], 'entry': eid, 'date': idate, 'name': it.get('name', ''), 'kind': it.get('kind', 'other'), 'org': it.get('org', ''), 'notes': it.get('notes', '')})
        _save(NET, n)
    rc = _recall()
    for it in items:
        if it['type'] in ('mock_interview', 'interview', 'study'):
            rc.log_external({'id': it['id'], 'entry': eid, 'date': it.get('date') or date, 'kind': it['type'], 'with': it.get('with') or it.get('company') or it.get('what', ''),
                             'format': it.get('format') or it.get('stage', ''), 'rating': it.get('rating'), 'minutes': it.get('minutes'), 'notes': it.get('notes', '')})
    return entry

def delete_entry(body):
    eid = body['id']
    with LOCK:
        j = journal(); j['entries'] = [e for e in j['entries'] if e['id'] != eid]; _save(JOURNAL, j)
        n = network(); n['people'] = [p for p in n['people'] if p.get('entry') != eid]; n['events'] = [e for e in n['events'] if e.get('entry') != eid]; _save(NET, n)
    _recall().delete_external({'entry': eid})
    return {'ok': True}

def journal_state():
    j = journal(); return {'entries': sorted(j['entries'], key=lambda e: (e['date'], e['time']))[-30:][::-1], 'today': today()}

# ---------------------------------------------------------------- networking
def net_state():
    n = network()
    people = sorted(n['people'], key=lambda p: p.get('date', ''), reverse=True)
    events = sorted(n['events'], key=lambda e: e.get('date', ''), reverse=True)
    for e in events: e['people'] = sum(1 for p in people if p.get('met_at') and p['met_at'].lower() == (e.get('name') or '').lower())
    return {'people': people, 'events': events, 'follow_ups': [p for p in people if p.get('follow_up') and not p.get('follow_up_done')], 'today': today()}

def net_save(body):
    kind = body.get('kind'); rec = body.get('record') or {}
    if kind not in ('person', 'event'): raise RuntimeError('kind must be person or event')
    with LOCK:
        n = network(); L = n['people' if kind == 'person' else 'events']
        cur = next((x for x in L if x['id'] == rec.get('id')), None)
        fields = ('name', 'company', 'role', 'relationship', 'met_at', 'how_they_can_help', 'follow_up', 'follow_up_done', 'notes', 'date', 'email', 'linkedin') if kind == 'person' else ('name', 'kind', 'org', 'notes', 'date')
        clean = {k: rec.get(k, '') for k in fields}
        if cur: cur.update(clean)
        else: L.append({'id': _id(kind), 'date': clean.get('date') or today(), **clean})
        _save(NET, n)
    return {'ok': True}

def net_delete(body):
    with LOCK:
        n = network(); k = 'people' if body.get('kind') == 'person' else 'events'
        n[k] = [x for x in n[k] if x['id'] != body.get('id')]; _save(NET, n)
    return {'ok': True}

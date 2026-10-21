#!/usr/bin/env python3
"""Gmail status sync: read your inbox (read-only) and suggest stage changes for the jobs you applied to.

    python3 scripts/gmail_status.py                 # new mail since the last sync (first run: 45 days)
    python3 scripts/gmail_status.py --days 90       # look further back
    python3 scripts/gmail_status.py --selftest      # offline test of the matcher, no mailbox needed

Same setup as the code broker: the Gmail app password in Windows Credential Manager (jobapply-gmail-imap).
Read-only IMAP: messages are fetched with BODY.PEEK (they stay unread), nothing is sent, moved, labelled or deleted.
Verification-code emails are skipped. Only job-related mail is kept: a message must match one of your applications.
Output: state/gmail_suggestions.json. The tracker UI shows each one with Accept / Dismiss; nothing changes until you accept.
The password and message bodies are never printed or stored; only sender, subject, date and a 160-character snippet are.
"""
import datetime, email, email.header, email.utils, importlib.util, imaplib, json, os, re, sys, time

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(R, 'state', 'gmail_suggestions.json')
STAMP = os.path.join(R, 'state', 'last_gmail_sync.txt')
ORDER = ['applied', 'intro_call', 'interview', 'final', 'offer']          # a suggestion never moves an application backwards
TERMINAL = {'rejected', 'passed', 'ghosted'}

def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(R, 'scripts', name + '.py'))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

REJECT = re.compile(r'unfortunately|not (?:be )?(?:moving|proceeding) forward|decided to (?:move|proceed|go) (?:forward )?with (?:other|another)|'
                    r'regret to inform|will not be (?:moving|proceeding|advancing)|no longer (?:considering|being considered)|position has been filled|'
                    r'not (?:a )?(?:fit|match) (?:at this time|for)|pursue other candidates|other candidates whose', re.I)
OFFER = re.compile(r'offer letter|pleased to offer|extend (?:you )?an offer|offer of employment|we.d like to offer you', re.I)
INTERVIEW = re.compile(r'schedule (?:a|an|your|some|time)|invite you to (?:interview|a call|chat|speak)|book (?:a )?time|calendly\.com|goodtime|'
                       r'phone screen|recruiter (?:screen|call|chat)|introductory call|intro call|technical (?:screen|interview)|'
                       r'availability (?:for|this|next)|next steps? (?:in|for) (?:the|your) (?:interview|process)|would like to (?:speak|chat|connect|meet) with you|'
                       r'move you forward|moving you forward|advance(?:d)? (?:to|you)', re.I)
INTRO = re.compile(r'recruiter|intro|introductory|phone screen|initial (?:call|chat|conversation)|quick (?:call|chat)', re.I)
CODE = re.compile(r'verification code|security code|confirm you.?re a human|one[- ]time|\bpasscode\b|your code\b', re.I)
ACK = re.compile(r'thank you for (?:applying|your application|your interest)|received your application|application (?:has been )?(?:received|submitted)', re.I)
SUFFIX = re.compile(r'\b(inc|llc|ltd|corp|corporation|co|company|technologies|technology|labs|ai|group|holdings|capital|usa|us|the)\b|[^a-z0-9 ]', re.I)

def classify(subject, body):
    t = subject + '\n' + body
    if CODE.search(t): return None
    if OFFER.search(t): return 'offer'
    if REJECT.search(t) and not INTERVIEW.search(subject): return 'rejected'
    if INTERVIEW.search(t) and not ACK.search(subject):
        return 'intro_call' if INTRO.search(t) else 'interview'
    return None

def norm(c): return re.sub(r'\s+', ' ', SUFFIX.sub(' ', (c or '').lower())).strip()

def match(apps, sender, subject, body):
    hay = (sender + ' ' + subject + ' ' + body[:600]).lower()
    tokens = re.findall(r'[a-z0-9]+', hay); compact = re.sub(r'[^a-z0-9]', '', hay)
    best, score = None, 0
    for a in apps:
        n = norm(a['company'])
        if len(n) < 3: continue
        words = [w for w in n.split() if len(w) >= 3]
        if not words: continue
        s = 0
        if n in hay or n.replace(' ', '') in compact: s = len(n) + 5
        elif len(words[0]) >= 4 and any(t.startswith(words[0]) for t in tokens): s = len(words[0])
        if s and a['role'] and a['role'].lower()[:25] in hay: s += 3
        if s > score: best, score = a, s
    return best if score >= 4 else None

def decode(h):
    try: return str(email.header.make_header(email.header.decode_header(h or '')))
    except Exception: return h or ''

def body_text(msg):
    for part in msg.walk():
        if part.get_content_type() == 'text/plain' and not part.get_filename():
            try: return part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', 'replace')
            except Exception: pass
    for part in msg.walk():
        if part.get_content_type() == 'text/html':
            try: return re.sub(r'<[^>]+>', ' ', part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', 'replace'))
            except Exception: pass
    return ''

def suggestions_for(apps, db_items, msgs, existing):
    out, seen = list(existing), {s['id'] for s in existing}
    dismissed = {k for k, v in (db_items or {}).items() if False}
    for m in msgs:
        if m['id'] in seen: continue
        stage = classify(m['subject'], m['body'])
        if not stage: continue
        a = match(apps, m['from'], m['subject'], m['body'])
        if not a: continue
        cur = a.get('stage', 'applied')
        if cur == stage or cur in TERMINAL or (stage in ORDER and cur in ORDER and ORDER.index(stage) <= ORDER.index(cur)): continue
        snippet = re.sub(r'\s+', ' ', m['body']).strip()[:160]
        out.append({'id': m['id'], 'key': a['key'], 'company': a['company'], 'role': a['role'], 'stage': stage, 'status': 'new',
                    'from': m['from'][:80], 'subject': m['subject'][:120], 'date': m['date'], 'snippet': snippet})
        seen.add(m['id'])
    return out

def selftest():
    apps = [{'key': 'k1', 'company': 'Affirm', 'role': 'Software Engineer II', 'stage': 'applied'},
            {'key': 'k2', 'company': 'Qube Research & Technologies', 'role': 'C++ Software Engineer', 'stage': 'applied'},
            {'key': 'k3', 'company': 'Tonic AI', 'role': 'FDE', 'stage': 'intro_call'}]
    msgs = [dict(id='1', **{'from': 'Affirm Recruiting <no-reply@greenhouse-mail.io>', 'subject': 'Your application to Affirm', 'date': '2026-10-18', 'body': 'Unfortunately we are not moving forward with your application at this time.'}),
            dict(id='2', **{'from': 'Jane <jane@quberesearch.com>', 'subject': 'Chat about C++ role?', 'date': '2026-10-18', 'body': 'Hi there, I would like to schedule a call with our recruiter. What is your availability this week?'}),
            dict(id='3', **{'from': 'no-reply@greenhouse-mail.io', 'subject': 'Security code for Affirm', 'date': '2026-10-18', 'body': 'Your verification code is ABC12345'}),
            dict(id='4', **{'from': 'Tonic <recruiting@tonic.ai>', 'subject': 'Thanks for applying to Tonic AI', 'date': '2026-10-18', 'body': 'Thank you for applying. We received your application.'}),
            dict(id='5', **{'from': 'Newsletter <news@random.com>', 'subject': 'Weekly digest', 'date': '2026-10-18', 'body': 'Unfortunately the market is down.'})]
    r = suggestions_for(apps, {}, msgs, [])
    got = {(s['company'], s['stage']) for s in r}
    ok = got == {('Affirm', 'rejected'), ('Qube Research & Technologies', 'intro_call')}
    print('selftest', 'OK' if ok else 'FAILED', sorted(got)); sys.exit(0 if ok else 1)

def main():
    if '--selftest' in sys.argv: selftest()
    tu = load('tracker_ui'); st = tu.state(); apps = [a for a in st['apps']]
    cb = load('code_broker'); c = cb.cfg()
    days = int(sys.argv[sys.argv.index('--days') + 1]) if '--days' in sys.argv else None
    try: last = datetime.datetime.fromisoformat(open(STAMP).read().strip())
    except Exception: last = None
    since = (datetime.date.today() - datetime.timedelta(days=days)) if days else ((last.date() - datetime.timedelta(days=1)) if last else datetime.date.today() - datetime.timedelta(days=45))
    M = cb.imap_login(c)                       # exits with {"status": "setup_error"} until the app password exists
    msgs = []
    try:
        for box in cb.mailboxes(M)[:1]:
            M.select('"' + box.strip('"') + '"', readonly=True)
            typ, data = M.search(None, 'SINCE', since.strftime('%d-%b-%Y'))
            ids = (data[0] or b'').split()[-1500:]
            for i in range(0, len(ids), 50):
                chunk = b','.join(ids[i:i + 50])
                typ, rows = M.fetch(chunk, '(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)] BODY.PEEK[TEXT]<0.2500>)')
                hdr = None
                for row in rows:
                    if not isinstance(row, tuple): continue
                    if b'HEADER' in row[0]: hdr = email.message_from_bytes(row[1]); continue
                    if hdr is None: continue
                    part = email.message_from_bytes(b'Content-Type: text/plain; charset=utf-8\r\n\r\n' + row[1])
                    txt = body_text(part) or row[1].decode('utf-8', 'replace')
                    sender = decode(hdr.get('From')); subj = decode(hdr.get('Subject'))
                    d = email.utils.parsedate_to_datetime(hdr['Date']).date().isoformat() if hdr.get('Date') else ''
                    msgs.append({'id': (hdr.get('Message-ID') or sender + subj + d).strip(), 'from': sender, 'subject': subj, 'date': d, 'body': txt})
                    hdr = None
    finally:
        try: M.logout()
        except Exception: pass
    try: existing = json.load(open(OUT, encoding='utf-8'))
    except Exception: existing = []
    sug = suggestions_for(apps, {}, msgs, existing)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(sug, open(OUT, 'w', encoding='utf-8'), indent=1)
    open(STAMP, 'w').write(datetime.datetime.now().isoformat(timespec='minutes'))
    new = [s for s in sug if s['status'] == 'new']
    print(json.dumps({'status': 'ok', 'scanned': len(msgs), 'new_suggestions': len(new)}))

if __name__ == '__main__': main()

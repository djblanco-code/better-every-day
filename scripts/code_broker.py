#!/usr/bin/env python3
"""Code broker: fetch an emailed verification code and hand it to the page WITHOUT the agent seeing it.

Scope: post-Submit application email verification (Greenhouse's 8-character code). Never login codes:
a one-time login code is a password, and signing in is always the user's.

    python3 scripts/code_broker.py check                       # Keychain item present + IMAP login works
    python3 scripts/code_broker.py fetch --to you@gmail.com --from <greenhouse sender domain> --since 1790000000 [--wait 300]
    python3 scripts/code_broker.py fetch --tag acme --from acme.com --since 1790000000   # plus address from settings
    python3 scripts/code_broker.py selftest                    # puts a dummy value on the clipboard (paste test)

How it works: reads Gmail over IMAP (read-only, messages stay unread) with an app password stored in the
macOS Keychain, finds the newest message to the plus address from the expected sender domain that arrived
after --since (epoch seconds, taken BEFORE clicking Submit), checks DKIM, extracts the code, and puts it
on the clipboard marked concealed + transient so clipboard managers skip it. A detached child clears the
clipboard after --hold seconds (default 20). The agent clicks the code field and presses cmd+v (ctrl+v on Windows).

Windows: the app password lives in Windows Credential Manager instead of the Keychain. The user stores it
once in their own PowerShell with `cmdkey /generic:jobapply-gmail-imap /user:<gmail> /pass` (hidden prompt);
the clipboard copy is flagged so Windows clipboard history and cloud sync skip it.

The code, the message body and the app password are never printed, returned, or logged. stdout is one JSON
line: {"status": ...}. Exit 0 = ready on clipboard, 1 = not found / timed out, 2 = refused (ambiguous code,
sender failed DKIM), 3 = setup error. Events go to state/broker.jsonl, without the code.

Setup is the user's, once (the agent never handles the password): see config/settings.example.json -> broker.
"""
import email, email.header, email.utils, html, imaplib, json, os, re, ssl, subprocess, sys, time, datetime

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(R, 'state', 'broker.jsonl')
DEFAULTS = {'gmail_account': '', 'signup_email_pattern': '', 'keychain_service': 'jobapply-gmail-imap'}

def cfg():
    try: s = json.load(open(os.path.join(R, 'config', 'settings.json'))).get('broker', {})
    except Exception: s = {}
    return {k: s.get(k) or v for k, v in DEFAULTS.items()}

def out(status, code=0, **kw):
    print(json.dumps(dict(status=status, **kw)))
    sys.exit(code)

def log(**kw):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    kw['ts'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    with open(LOG, 'a') as f: f.write(json.dumps(kw) + '\n')

WINDOWS = sys.platform == 'win32'
PASTE = 'ctrl+v' if WINDOWS else 'cmd+v'

def _win_cred(target, user):
    """Generic credential from Windows Credential Manager (stored by the user with
    `cmdkey /generic:<target> /user:<gmail> /pass`). Returns the password or None."""
    import ctypes
    from ctypes import wintypes
    class CREDENTIAL(ctypes.Structure):
        _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD), ('TargetName', wintypes.LPWSTR),
                    ('Comment', wintypes.LPWSTR), ('LastWritten', wintypes.FILETIME),
                    ('CredentialBlobSize', wintypes.DWORD), ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)),
                    ('Persist', wintypes.DWORD), ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
                    ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR)]
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    p = ctypes.POINTER(CREDENTIAL)()
    # cmdkey /generic stores CRED_TYPE_DOMAIN_PASSWORD (2); a script-made one is CRED_TYPE_GENERIC (1).
    for ctype in (1, 2):
        if advapi.CredReadW(target, ctype, 0, ctypes.byref(p)):
            try:
                cr = p.contents
                if user and (cr.UserName or '').lower() != user.lower(): return None
                raw = ctypes.string_at(cr.CredentialBlob, cr.CredentialBlobSize)
                return raw.decode('utf-16-le') if len(raw) % 2 == 0 else raw.decode('utf-8', 'replace')
            finally:
                advapi.CredFree(p)
    return None

def app_password(c):
    if WINDOWS: return _win_cred(c['keychain_service'], c['gmail_account'])
    r = subprocess.run(['security', 'find-generic-password', '-s', c['keychain_service'], '-a', c['gmail_account'], '-w'],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None

def imap_login(c):
    if not c['gmail_account']: out('setup_error', 3, detail='settings.json broker.gmail_account is empty')
    pw = app_password(c)
    if not pw: out('setup_error', 3, detail=f'no Keychain item service={c["keychain_service"]} account={c["gmail_account"]}')
    # python.org Python ships no CA bundle; use the system one, as portal_sweep.py does.
    ctx = ssl.create_default_context(cafile='/etc/ssl/cert.pem') if os.path.exists('/etc/ssl/cert.pem') else ssl.create_default_context()
    try: M = imaplib.IMAP4_SSL('imap.gmail.com', 993, ssl_context=ctx)
    except (OSError, ssl.SSLError) as e: out('setup_error', 3, detail=f'cannot reach imap.gmail.com: {type(e).__name__}')
    try: M.login(c['gmail_account'], pw)
    except imaplib.IMAP4.error: out('setup_error', 3, detail='IMAP login refused (wrong app password, or IMAP off)')
    finally: del pw
    return M

def mailboxes(M):
    """All Mail + Spam, found by IMAP special-use flag so a localized Gmail still works."""
    typ, rows = M.list()
    found = []
    for row in rows or []:
        s = row.decode(errors='replace')
        if '\\All' in s or '\\Junk' in s:
            found.append(s.rsplit(' "/" ', 1)[-1])
    return found or ['INBOX']

# ---- code extraction -------------------------------------------------------------------------------
KEY = re.compile(r'code|passcode|verification|verify|one[- ]time|\botp\b|\bpin\b', re.I)
CAND = re.compile(r'(?<![\w#/.@-])([A-Z0-9]{4,8})(?![\w/@-])')

def text_of(msg):
    subj = str(email.header.make_header(email.header.decode_header(msg.get('Subject', ''))))
    plain, htm = [], []
    for part in msg.walk():
        ct = part.get_content_type()
        if ct not in ('text/plain', 'text/html') or part.get_filename(): continue
        try: body = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='replace')
        except Exception: continue
        (plain if ct == 'text/plain' else htm).append(body)
    body = '\n'.join(plain) if plain else re.sub(r'<[^>]+>', ' ', re.sub(r'(?is)<(style|script).*?</\1>', ' ', '\n'.join(htm)))
    return subj + '\n' + html.unescape(body)

def extract(text):
    """One code or None. Candidates must contain a digit and sit near a code keyword. More than one
    distinct candidate (after preferring 6-digit numerics) means ambiguous: refuse rather than guess."""
    near = set()
    for k in KEY.finditer(text):
        window = text[max(0, k.start() - 60): k.end() + 120]
        near.update(m for m in CAND.findall(window) if re.search(r'\d', m) and not re.fullmatch(r'(19|20)\d\d', m))
    six = {m for m in near if re.fullmatch(r'\d{6}', m)}
    pool = six or near
    if len(pool) == 1: return next(iter(pool)), 'ok'
    return None, ('ambiguous' if pool else 'no_code')

def dkim_ok(msg, domain):
    ar = ' '.join(msg.get_all('Authentication-Results') or [])
    for m in re.finditer(r'dkim=pass[^;]*?header\.(?:i|d)=@?([\w.-]+)', ar, re.I):
        d = m.group(1).lower()
        if d == domain or d.endswith('.' + domain): return True
    return False

# ---- clipboard (JXA, value passed on stdin so it never appears in argv / ps) --------------------------
JXA_SET = '''ObjC.import("AppKit");function run(){var d=$.NSFileHandle.fileHandleWithStandardInput.readDataToEndOfFile;
var s=$.NSString.alloc.initWithDataEncoding(d,$.NSUTF8StringEncoding);var p=$.NSPasteboard.generalPasteboard;p.clearContents;
p.setStringForType(s,"public.utf8-plain-text");p.setStringForType($(""),"org.nspasteboard.ConcealedType");
p.setStringForType($(""),"org.nspasteboard.TransientType");return p.changeCount;}'''
JXA_CLEAR = '''ObjC.import("AppKit");function run(a){var p=$.NSPasteboard.generalPasteboard;
if(p.changeCount==parseInt(a[0])){p.clearContents;return "cleared"}return "untouched"}'''

# ---- clipboard (Windows): Win32 API, marked so clipboard history / cloud sync / monitors skip it -------
def _win_clip():
    import ctypes
    from ctypes import wintypes
    u, k = ctypes.WinDLL('user32', use_last_error=True), ctypes.WinDLL('kernel32', use_last_error=True)
    u.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]; u.SetClipboardData.restype = wintypes.HANDLE
    u.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]; u.RegisterClipboardFormatW.restype = wintypes.UINT
    k.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]; k.GlobalAlloc.restype = wintypes.HGLOBAL
    k.GlobalLock.argtypes = [wintypes.HGLOBAL]; k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    return ctypes, u, k

def _win_open(u):
    for _ in range(20):
        if u.OpenClipboard(None): return True
        time.sleep(0.05)
    return False

def _win_put(u, k, ctypes, fmt, data):
    h = k.GlobalAlloc(0x0002, len(data)); ptr = k.GlobalLock(h)
    ctypes.memmove(ptr, data, len(data)); k.GlobalUnlock(h)
    u.SetClipboardData(fmt, h)

def win_to_clipboard(value, hold):
    ctypes, u, k = _win_clip()
    if not _win_open(u): out('clipboard_error', 3, detail='OpenClipboard failed')
    try:
        u.EmptyClipboard()
        _win_put(u, k, ctypes, 13, (value + '\0').encode('utf-16-le'))  # CF_UNICODETEXT
        _win_put(u, k, ctypes, u.RegisterClipboardFormatW('ExcludeClipboardContentFromMonitorProcessing'), b'\0\0\0\0')
        _win_put(u, k, ctypes, u.RegisterClipboardFormatW('CanIncludeInClipboardHistory'), b'\0\0\0\0')
        _win_put(u, k, ctypes, u.RegisterClipboardFormatW('CanUploadToCloudClipboard'), b'\0\0\0\0')
    finally:
        u.CloseClipboard()
    n = u.GetClipboardSequenceNumber()
    # Detached child clears the clipboard after `hold` seconds, only if nothing else replaced it since.
    subprocess.Popen([sys.executable, os.path.abspath(__file__), '_clear', str(n), str(hold)],
                     creationflags=0x00000008 | 0x00000200 | 0x08000000,  # DETACHED | NEW_GROUP | NO_WINDOW
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)

def win_clear(n, hold):
    time.sleep(hold)
    ctypes, u, k = _win_clip()
    if u.GetClipboardSequenceNumber() == n and _win_open(u):
        try: u.EmptyClipboard()
        finally: u.CloseClipboard()

def to_clipboard(value, hold):
    if WINDOWS: return win_to_clipboard(value, hold)
    r = subprocess.run(['osascript', '-l', 'JavaScript', '-e', JXA_SET], input=value, capture_output=True, text=True)
    if r.returncode != 0: out('clipboard_error', 3, detail=r.stderr.strip()[:200])
    n = r.stdout.strip()
    # /bin/sh, not a Python child: framework Python runs as Python.app, and App Nap stretched its sleep(30) to minutes.
    subprocess.Popen(['/bin/sh', '-c', 'sleep "$1"; osascript -l JavaScript -e "$2" "$3"', 'sh', str(hold), JXA_CLEAR, n],
                     start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# ---- commands --------------------------------------------------------------------------------------
def arg(name, default=None):
    a = sys.argv
    return a[a.index(name) + 1] if name in a and a.index(name) + 1 < len(a) else default

def cmd_fetch(c):
    to = arg('--to')
    if not to and arg('--tag'):
        if '{tag}' not in c['signup_email_pattern']: out('setup_error', 3, detail='broker.signup_email_pattern needs {tag}')
        to = c['signup_email_pattern'].replace('{tag}', arg('--tag'))
    frm, since = (arg('--from') or '').lower().lstrip('@'), arg('--since')
    if not (to and frm and since): out('usage', 3, detail='need --to or --tag, --from DOMAIN, --since EPOCH')
    since, wait, hold = float(since), int(arg('--wait', '300')), int(arg('--hold', '20'))
    days = max(1, int((time.time() - since) // 86400) + 1)
    query = f'to:{to} from:{frm} newer_than:{days}d'
    M = imap_login(c)
    boxes, deadline, last = mailboxes(M), time.time() + wait, 'no_message'
    while True:
        best = None  # (internal_epoch, msg)
        for box in boxes:
            if M.select(box, readonly=True)[0] != 'OK': continue
            typ, data = M.uid('SEARCH', 'X-GM-RAW', '"' + query.replace('"', '') + '"')
            for uid in (data[0].split() if typ == 'OK' and data and data[0] else [])[-10:]:
                typ, parts = M.uid('FETCH', uid, '(INTERNALDATE BODY.PEEK[])')
                if typ != 'OK' or not parts or not isinstance(parts[0], tuple): continue
                t = imaplib.Internaldate2tuple(parts[0][0])
                ts = time.mktime(t) if t else 0
                if ts >= since - 30 and (best is None or ts > best[0]):
                    best = (ts, email.message_from_bytes(parts[0][1]))
        if best:
            ts, msg = best
            sender = email.utils.parseaddr(msg.get('From', ''))[1].lower()
            received = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            if not (sender.endswith('@' + frm) or sender.endswith('.' + frm)) or not dkim_ok(msg, frm):
                log(cmd='fetch', to=to, sender_domain=frm, status='unverified_sender', received=received)
                out('unverified_sender', 2, received=received, detail='From or DKIM does not match --from; not used')
            code, why = extract(text_of(msg))
            if code:
                to_clipboard(code, hold); del code
                log(cmd='fetch', to=to, sender_domain=frm, status='ready', received=received)
                out('ready', 0, received=received, hold_s=hold, next=f'click the code field, press {PASTE}, never read the field back')
            if why == 'ambiguous':
                log(cmd='fetch', to=to, sender_domain=frm, status='ambiguous', received=received)
                out('ambiguous', 2, received=received, detail='several candidate codes; NEEDS HUMAN')
            last = why  # no_code: keep waiting, a second email may carry it
        if time.time() >= deadline: break
        time.sleep(10)
    log(cmd='fetch', to=to, sender_domain=frm, status=last)
    out(last, 1, waited_s=wait)

def cmd_check(c):
    M = imap_login(c)
    boxes = mailboxes(M); M.logout()
    out('ok', 0, account=c['gmail_account'], mailboxes=boxes, signup_email_pattern=c['signup_email_pattern'] or None)

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == '_clear' and WINDOWS:  # internal: the detached clipboard-clearing child
        win_clear(int(sys.argv[2]), int(sys.argv[3])); sys.exit(0)
    if cmd == 'selftest':
        to_clipboard('BROKER-TEST-4821', int(arg('--hold', '20')))
        out('ready', 0, hold_s=int(arg('--hold', '20')), detail='dummy value BROKER-TEST-4821 on clipboard; paste it to test')
    c = cfg()
    if cmd == 'check': cmd_check(c)
    if cmd == 'fetch': cmd_fetch(c)
    out('usage', 3, detail=__doc__.strip().splitlines()[2:6])

if __name__ == '__main__':
    main()

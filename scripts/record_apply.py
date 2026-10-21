#!/usr/bin/env python3
"""Record one outcome in one command (keeps rounds cheap and the records consistent).

  python3 scripts/record_apply.py applied <pool-id> "<Company>" "<Role>" "<Location>" "<Pay>" "<posting url>" <doc-slug> [--shot]
  python3 scripts/record_apply.py needs_human <pool-id> "<Company>" "<Role>" "<Location>" "<Pay>" "<posting url>" "<blocker>" "<what you need to do>"
  python3 scripts/record_apply.py skipped <pool-id> "<reason>"

applied: copies the newest screenshot from the Claude tool-results folder to screenshots/<doc-slug>-<date>.jpg (--shot),
marks the lead applied, adds the "Applied by the agent" row and the applications-log line.
Then run `python3 scripts/pool.py take` for the next lead.
"""
import datetime, glob, os, re, shutil, subprocess, sys

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODAY = datetime.date.today().isoformat()
MD = os.path.join(R, 'logs', 'job-tracker.md')
LOG = os.path.join(R, 'logs', 'applications-log.md')

def pool(*a): subprocess.run([sys.executable, os.path.join(R, 'scripts', 'pool.py'), *a], cwd=R)

def insert_row(row, nine):
    """Newest row at the top of the matching table. Rows are classified by column count (7 = agent, 9 = apply yourself)."""
    lines = open(MD, encoding='utf-8').read().split('\n')
    heading = '## Apply yourself' if nine else '## Applied by the agent'
    for i, l in enumerate(lines):
        if l.startswith(heading):
            lines.insert(i + 2, row); break
    open(MD, 'w', encoding='utf-8', newline='\n').write('\n'.join(lines))

def newest_shot():
    base = os.path.expanduser('~/.claude/projects')
    files = glob.glob(os.path.join(base, '*', '*', 'tool-results', '*.jpg'))
    return max(files, key=os.path.getmtime) if files else None

def main():
    k = sys.argv[1]
    if k == 'skipped':
        pool('mark', sys.argv[2], 'skipped', sys.argv[3]); return
    pid, co, role, loc, pay, url = sys.argv[2:8]
    if k == 'applied':
        slug = sys.argv[8]; shot = f'{slug}-{TODAY}.jpg'
        if '--shot' in sys.argv:
            src = newest_shot()
            if src: shutil.copy(src, os.path.join(R, 'screenshots', shot))
        pool('mark', pid, 'applied', f'submitted {TODAY}')
        insert_row(f'| {TODAY} | {co} | {role} | {loc} | {pay or "not posted"} | {url} | applications/{slug}.md, screenshots/{shot} |', False)
        open(LOG, 'a', encoding='utf-8').write(f'- {TODAY} {co} {role} SUBMITTED\n')
    elif k == 'needs_human':
        blocker, todo = sys.argv[8], sys.argv[9]
        pool('mark', pid, 'needs_human', blocker)
        insert_row(f'| {TODAY} | {co} | {role} | {loc} | {pay or "not posted"} | {url} | {blocker} | {todo} | Open |', True)
        open(LOG, 'a', encoding='utf-8').write(f'- {TODAY} NEEDS HUMAN {co} {role}: {blocker}\n')

main()

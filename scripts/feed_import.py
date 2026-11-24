#!/usr/bin/env python3
"""Once a day: rebuild the all-jobs feed and hand its best-fit roles to the applying agent's queue.

    python3 scripts/feed_import.py            # skips itself if the feed is under 20 hours old
    python3 scripts/feed_import.py --force

Runs scripts/all_jobs.py (about 20 minutes, no Claude usage), then scripts/collect.py --import on
jobs-page/apply_queue.json: every role at 60%+ fit in New York, Chicago or remote. collect.py still applies the
full gate from config/settings.json (level, years, skip list, duplicates, collector.min_fit). run.sh calls this
before the collector; a failure here never blocks a run.
"""
import os, subprocess, sys, time
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
Q = os.path.join(R, 'jobs-page', 'apply_queue.json')
if '--force' not in sys.argv and os.path.exists(Q) and time.time() - os.path.getmtime(Q) < 20 * 3600:
    print(f'feed is {int((time.time() - os.path.getmtime(Q)) / 3600)}h old; nothing to do (--force to rebuild)'); sys.exit(0)
env = dict(os.environ, PYTHONUTF8='1')
a = subprocess.run([sys.executable, os.path.join(R, 'scripts', 'all_jobs.py'), '--days', '14'], capture_output=True, text=True, env=env, cwd=R)
print((a.stdout.strip().splitlines() or ['all_jobs.py printed nothing'])[-1])
if a.returncode or not os.path.exists(Q): sys.exit('all_jobs.py failed: ' + a.stderr[-400:])
b = subprocess.run([sys.executable, os.path.join(R, 'scripts', 'collect.py'), '--import', Q], capture_output=True, text=True, env=env, cwd=R)
print((b.stdout.strip() or b.stderr[-400:]))

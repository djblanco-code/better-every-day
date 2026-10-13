# Windows support, lead pool, and the collector

This fork adds three things on top of upstream please-hire-me.

## 1. Runs on Windows 11 (Git Bash)
- `run.cmd` launches `run.sh` from PowerShell; `scripts/schedule.sh` installs a Windows Task Scheduler task.
- `scripts/code_broker.py` reads the Gmail app password from Windows Credential Manager
  (`cmdkey /generic:jobapply-gmail-imap /user:<gmail> /pass`) and uses the Win32 clipboard.
- Line endings are forced to LF (`.gitattributes`), `PYTHONUTF8=1` is set, and `python3` resolves to python.org.

## 2. A collector that spends no Claude usage
`scripts/collect.py` searches every source in plain Python (company ATS boards, VC portfolio boards, big-company
career sites, JobDataLake), reads each posting from public APIs, vets it against `config/settings.json`
(titles, level, location, years, pay, skip list, duplicates, required questions) and scores it with
`scripts/fit.py`. Every lead lands in `state/pool.json` first, so a run that dies loses nothing.

## 3. A lead pool the agent works from
`scripts/pool.py take` atomically claims the next lead (fresh first, then best fit) so two sessions never take the
same job. `pool.py mark <id> applied|closed|skipped|needs_human` records the outcome. `/round`
(`.claude/commands/round.md`) runs the whole flow in Claude Code.
GrepJob (needs its own login) is queried only from a session; its rows are imported with
`python3 scripts/collect.py --import rows.json`.

## Making it yours
Copy the `config/*.example.*` files, edit `HAVE`/`GAPS` in `scripts/fit.py` to match your resume, and never commit
`config/profile.json`, `config/answers.md`, `config/settings.json`, `data/*.pdf`, `applications/`, `logs/`,
`screenshots/` or `state/` (all are in `.gitignore`).

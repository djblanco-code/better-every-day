## Sourcing method (fastest first)
Start from `data/boards.md`, which lists the org slugs already verified live, and read
`data/ats-field-notes.md` before opening any form. Then query the ATS board APIs from the shell
instead of crawling search pages.
- Ashby: `https://api.ashbyhq.com/posting-api/job-board/<org>?includeCompensation=true` → JSON with
  title, location, `compensation.compensationTierSummary`, and `descriptionPlain`.
- Greenhouse: `https://boards-api.greenhouse.io/v1/boards/<token>/jobs`, then `/jobs/<id>`.
- Lever: `https://api.lever.co/v0/postings/<org>?mode=json`.
- SmartRecruiters: `https://api.smartrecruiters.com/v1/companies/<org>/postings` (org is case-sensitive).
- Workable: `https://apply.workable.com/api/v1/widget/accounts/<org>?details=true`.
- **★ The delta sweep is `python3 scripts/delta_sweep.py`. Run it in the FOREGROUND** (Bash tool, timeout
  540000), never `run_in_background`. A headless run that backgrounds it and "waits for the notification"
  ends its turn, and the session ends with it: four runs in a row once did zero work that way. The
  script keeps its own cutoff in `state/last_sweep.txt` and advances it on success, stops itself at 7
  minutes, and writes `state/sweep/cands.json`. Do not rebuild it in `/tmp`; edit the one in `scripts/`.
- **`python3 scripts/portal_sweep.py`, once per run, foreground.** Lists new-grad software postings on company
  portals without logging in: Amazon, Nvidia, Salesforce, Intel, Arrowstreet, G-Research, Google, D. E. Shaw,
  Two Sigma, Bloomberg, Microsoft, Qualcomm, AMD, Apple (signed-in portals) and Netflix, Millennium, Uber,
  Renaissance (no account needed, `OPEN_PORTALS` in the script). Rows under "AGENT MAY APPLY" are yours: on a
  signed-in portal confirm the signed-in header first, then apply. Rows under "FOR YOU, BY HAND" go verbatim
  into the run summary's top section. Never try to log in. The sweep cannot list Meta, Tesla, Citadel,
  Citadel Securities or Balyasny (scripts are blocked); their apply forms need no account except Meta's, so
  check their careers pages in the browser when a run has spare capacity. Apply flows per portal:
  `data/manual-portals.md`.
- **`python3 scripts/list_sweep.py`, once per run, foreground.** New postings since the last run from the
  SimplifyJobs new-grad and internship lists (their `listings.json` feeds) and the Consider-hosted VC boards
  (a16z, Sequoia, Lightspeed, Kleiner Perkins, GV, Bessemer). Already filtered on `targets.locations`, the
  start window (internship terms and seasons in titles), sponsorship, `minYearsExp` and the comp floor; the
  prestige gate is yours, per posting. Every row links to the company's own ATS. It also appends ATS slugs it
  has not seen to `data/slug-candidates.txt`, so `delta_sweep.py` reads those boards in full from the next run.
- **GrepJob MCP (`mcp__grepjob__search_jobs`), when connected.** A curated database of software engineering
  jobs with filters for location, sub_category, seniority (intern / entry level / mid level / senior / staff+),
  tech_stack_filters, min_salary and page (20 per page). Map `targets` onto those filters, read a few pages per
  location, and treat every row as a lead: follow its url to the company's own ATS, verify it is live, check
  the years-of-experience text, then the usual duplicate and eligibility checks. If it reports that it needs
  authentication, the user finishes that once in an interactive `claude` session with `/mcp`.
- **JobDataLake MCP (`mcp__jobdatalake__*`), no account.** About a million listings pulled hourly from
  direct company ATS feeds (Greenhouse, Lever, Ashby, Workday and more). Call `get_filter_options` once for
  the exact filter values, then `search_jobs` per location with the salary, seniority and posted-date filters;
  `get_job` gives the full description for the years-of-experience check. Free tier is 500 requests a day:
  stay under 30 per run. Same lead rule as GrepJob.
- Hacker News monthly hiring thread: `./scripts/fetch_hn_hiring.sh`. Startups that never post to a
  job board, roles link straight to the company ATS. Refill an empty queue from here first.

Notes that keep costing runs when forgotten:
- Grep `descriptionPlain` for `\d+ years`, *senior*, *staff-level*, *proven*, *at scale* before
  opening a tab. Seniority often lives in the body, not the title. Print the surrounding context:
  a "18 years" match can be a founder bio, not a gate.
- `compensation: null` is not proof of no band. The band is often in the body text.
- Sleep ~2s between org queries. Rate-limited responses fail to parse and read as dead boards.
- Org slugs are not company names. Try hyphenated and suffixed variants before recording a board as
  dead, and re-test "dead" slugs occasionally; they come back.
- A req id carried over from a previous run can die. Re-verify `isListed: true` before filling.


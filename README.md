<div align="center">

# Better Every Day

**A private, local app for the whole job hunt: track applications, practice for interviews one hour a day, and remember the people who can help.**

[![License: MIT](https://img.shields.io/badge/License-MIT-black.svg)](LICENSE)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-black.svg)](CONTRIBUTING.md)
[![Runs on Claude Code](https://img.shields.io/badge/runs%20on-Claude%20Code-black.svg)](https://claude.com/claude-code)
[![Windows | macOS | Linux](https://img.shields.io/badge/Windows%20%7C%20macOS%20%7C%20Linux-black.svg)](#better-every-day-setup)

Three apps in one page, served from your own machine, with your own AI key. Nothing about you leaves
your computer. Plus the application agent that fills real ATS forms for you (below).

</div>

| App | What it does |
|---|---|
| **Job Tracker** | Every application in one place with stages (applied → intro call → interviewing → final → offer), a Sankey funnel, assessments to do, intro calls to book, Gmail sync that suggests stage changes from recruiter email, and "start a new job search" when it is time for a fresh window. |
| **Recall** | A 26-week, 60-minutes-a-day interview program. Each day: 25 min LeetCode, 25 min of Python / System Design / Data Structures & Algorithms / Debugging (rotating), and a textbook reading or homework item. A Google-Doc-style page shows the problem; you write, nothing runs; Claude or Gemini grades it against a rubric. Spaced repetition, interleaving, mastery gating, readiness per track, and metrics over six months. |
| **Network** | People you met, mentors, recruiters, events, who can connect you to what, and follow-ups. |
| **Home journal** | Say or type what you did today ("went to a job fair, met three people, aced a mock interview, Google screen went okay") and it is sorted into Network and Recall. |

## Better Every Day setup

**You need:** Python 3.10+ (python.org on Windows, `brew install python` on macOS), Chrome, and an
[Anthropic API key](https://console.anthropic.com/) (or a Gemini key) for grading and journal parsing.

```bash
git clone https://github.com/djblanco-code/better-every-day.git
cd better-every-day
python3 scripts/fetch_statements.py     # optional: LeetCode problem statements from the open leetcode-problems dataset
python3 scripts/tracker_ui.py           # Windows: double-click tracker.cmd
```

Open <http://127.0.0.1:8787>. Then, once:

1. **Recall → Settings**: pick Anthropic or Gemini, paste your key, click *Test the key*. The key is saved
   to `config/recall.json` (gitignored) and sent only to that provider. Set *Program start* if today is
   not day one.
2. **Job Tracker**: it reads `logs/job-tracker.md` (the agent writes it, or add rows by hand with
   *Manual applications → Add by link*, which auto-fills from Greenhouse / Ashby / Lever / any
   JobPosting page). Stages and notes live in `state/tracker.json`.
3. **Gmail sync (optional)**: a read-only IMAP check that suggests stage changes from recruiter
   email. Create a Google app password, store it yourself (never in chat):
   `cmdkey /generic:jobapply-gmail-imap /user:you@gmail.com /pass` on Windows, or
   `security add-generic-password -s jobapply-gmail-imap -a you@gmail.com -w` on macOS, and set
   `broker.gmail_account` in `config/settings.json`.

**Use it from your phone** without exposing it: see [docs/HOSTING.md](docs/HOSTING.md) (Tailscale in
ten minutes, or Cloudflare Tunnel with a Google login screen).

<details>
<summary><b>How Recall decides what you do today</b></summary>

The plan is generated once per day and does not move. It is deterministic, no model involved:

1. **Due reviews first**, weakest best-score first (SM-2-style spacing: 8+ doubles the interval,
   5-7 repeats tomorrow, under 5 comes back today).
2. **New problems from this week's focus category** (`data/recall-curriculum.json` walks the NeetCode
   roadmap over 18 learning weeks, then 8 speed weeks).
3. **Earliest unmastered category** on the roadmap. A category is mastered at three problems scored 8+.
4. Difficulty steps Easy → Medium → Hard as a category collects strong scores.
5. Yesterday's category is pushed down unless due (interleaving).

The second slot rotates Python / System Design / DSA / Debugging: most reviews due wins, else the lowest
readiness, never the same track two days running. Readiness per track is 70% difficulty-weighted
coverage of problems scored 8+ (LeetCode measured against NeetCode 150) and 30% your last ten scores.

Grading is pinned for stability: temperature 0, a JSON schema enforced by the provider (Claude tool use
/ Gemini responseSchema), anchored score bands, retries with backoff, and a grader version stamped on
every session.

Banks you can edit: `data/recall-python.json`, `recall-systemdesign.json`, `recall-dsa.json`,
`recall-debugging.json`, and the curriculum. LeetCode lists come from NeetCode 150/250 and Blind 75 with
company frequency from [leetcode-company-wise-problems](https://github.com/liquidslr/leetcode-company-wise-problems).
Problem text is not redistributed; `fetch_statements.py` pulls it from
[leetcode-problems](https://github.com/prathameshakole/leetcode-problems) into a gitignored folder.

</details>

<details>
<summary><b>Privacy and what stays local</b></summary>

`config/profile.json`, `config/answers.md`, `config/settings.json`, `config/recall.json` (your key),
`state/` (progress, journal, network, plans), `logs/`, `applications/`, `screenshots/`, your resume, and
your interview tracker are all gitignored. The server binds to `127.0.0.1` only and rejects cross-origin
POSTs. The only outbound calls are the model provider you chose (grading, journal parsing), the ATS APIs
used for link auto-fill and sourcing, and Gmail IMAP if you set it up.

</details>

---

# The application agent (please-hire-me)

**An agent that fills out real job applications while you sleep.** Originally
[alecswang/please-hire-me](https://github.com/alecswang/please-hire-me), extended here with Windows
support, a Python lead collector, and the Better Every Day UI above.

You set it up once, in one conversation of about five minutes, and it writes your config from your
resume. After that it runs autonomously, finding live openings, internships and new-grad roles
alike, filling the company's own Greenhouse / Lever / Ashby form field by field in your real Chrome,
and submitting. Every answer is logged before it clicks, every submit is screenshotted, and it never
invents a fact about you.

---

## Quick start

**You need:** [Claude Code](https://claude.com/claude-code) signed in · Chrome with the
[Claude in Chrome](https://claude.ai/chrome) extension on the same account · your resume as a PDF.

<details>
<summary>Setting up the Chrome extension</summary>

Three steps, all manual, none of them scriptable. Chrome requires a real user gesture to install an
extension and to grant it a site, which is the correct behaviour and not something this repo should
try to work around.

1. Install [Claude in Chrome](https://claude.ai/chrome).
2. Sign in with the **same Anthropic account** as your Claude Code session. A mismatch looks exactly
   like the extension not being installed.
3. Let it access the ATS domains when it asks. Access is granted per site.

Setup checks this for you before the first application and tells you which of the three is missing,
so you are not debugging it halfway through a filled form.

</details>

```bash
git clone https://github.com/djblanco-code/better-every-day.git
cd better-every-day
```

Open the repo in Claude Code and say *"set me up"*. Setup is one conversation, about five minutes,
and Claude does the typing:

1. It asks for your resume and reads it.
2. It shows you every value it pulled out so you can correct what is wrong.
3. It asks **one list** of the questions a resume cannot answer, all at once, with the default it
   will use for anything you skip. Work authorization, start date, what counts as a good job to you.
4. It drafts your answer templates from your real work and reads them back for you to approve.

Then it writes your three config files. It never invents a fact about you, and it does not open a
browser or apply to anything during setup.

<details>
<summary>Prefer a terminal wizard?</summary>

`./setup.sh` asks the questions every form asks and writes your config in about two minutes. It
leaves `config/answers.md` as a blank template for you to fill in yourself, which takes about
twenty minutes and is the step that decides whether the agent flies or stalls at every "why do you
want this role?". Letting Claude draft it from your resume is why the guided path is the default.

</details>

**Run it:**

```bash
./run.sh          # one run, using your settings
./run.sh 1        # a single application, good for a first test
```

<details>
<summary><b>How much rope to give it</b></summary>

**The first application is supervised.** At the end of setup it fills one real posting, shows you
every answer, and submits only after you say yes. Say no and it closes the tab and sends nothing.
A real application with a checkpoint, not a rehearsal.

**Scheduled runs submit on their own.** Once `schedule.frequency` is set and the job is installed,
there is no per-application checkpoint. That is the point of it.

**Want a checkpoint every time?** `./run.sh` cannot give you one, it launches a headless session
with nobody there to approve. Instead, open the repo in Claude Code and ask for a run, saying stop
before submitting. You get the same checkpoint as the first application, every time.

</details>

---

## What you give it

A missing fact becomes a question for you, never a guess. Three files decide everything, and setup
writes all three for you:

| File | What goes in it | Where it comes from |
|---|---|---|
| `config/profile.json` | Name, contact, school, degree, graduation, GPA, visa status, links, resume path. | read off your resume, then you correct it |
| `config/answers.md` | Free-text templates, your fact sheet, presets for salary, start date, EEO. **The one that matters.** | drafted from your resume, then you approve it |
| `config/settings.json` | Cap per run, frequency, and what counts as a target: roles, locations, comp floor, skip list, your quality bar. | your answers to the question list |

Each has a `.example` twin showing exactly what belongs there. Your real files are gitignored, so
nothing about you leaves your machine. Edit any of them by hand later; the agent rereads them every
run.

## Settings

One file, `config/settings.json`. The launcher turns it into the instructions the agent must obey.

| Key | Does what |
|---|---|
| `run.max_applications_per_run` | Hard cap per run. Default 3. |
| `run.same_day_company_freeze` | Never open a second role at a company you applied to today. |
| `schedule.frequency` | `manual`, `hourly`, `every-2-hours`, `every-3-hours`, `every-6-hours`, `daily`, `weekdays`. |
| `targets.roles` | Titles to look for. |
| `targets.max_years_experience_required` | Anything above this is skipped as a hard mismatch. |
| `targets.locations` | Cities, plus `Remote (US)` if you want remote. |
| `targets.min_annual_comp_usd` | Compensation floor for **full-time** roles. |
| `targets.internship_min_hourly_usd` | Hourly floor for **internships**, which post hourly pay and would otherwise fail an annual floor. `0` means judge them on the quality bar alone. |
| `targets.prestige_note` | Your quality bar in plain English, used when a posting lists no salary. |
| `targets.skip_companies` | Never apply here. |
| `eligibility.needs_visa_sponsorship` | Skips non-sponsors, ITAR, and clearance roles. |
| `eligibility.graduation` | Skips postings whose graduation window excludes you. |
| `run.max_applications_per_company_lifetime` | Stop at this many applications to one company, ever. Default 2. |
| `run.interview_tracker_path` | Your interview note; every company in it is skipped. See add-ons. |
| `channels.signed_in_portals` | Portals where you are signed in and the agent may apply. See add-ons. |
| `broker.*` | Gmail account for the emailed-code add-on. |
| `safety.*` | No accounts, no CAPTCHA solving, no fabricated facts, screenshot every submit. |

Run it on a schedule:

```bash
./scripts/schedule.sh install        # reads schedule.frequency
./scripts/schedule.sh status         # this checkout, plus every other one on the machine
./scripts/schedule.sh uninstall      # this checkout only
./scripts/schedule.sh uninstall-all  # every please-hire-me job on the machine
```

Each checkout gets its own scheduled job, keyed to its path, so two clones can run on
their own cadences without overwriting each other. `status` shows all of them and marks
which one you are in.

## Optional add-ons (each needs one step from you)

None of these is required. Each unlocks more applications, and each has a step only you can do,
because it involves an account, a password, or your own notes.

**1. Company portals that need an account** (Amazon, Nvidia and other Workday companies, Microsoft,
Apple, Two Sigma, Bloomberg, AMD, Qualcomm...). The agent never creates an account and never logs in.
You sign up or sign in once in Chrome, then add the portal's host to `channels.signed_in_portals`:

```json
"signed_in_portals": ["amazon.jobs", "nvidia.wd5.myworkdayjobs.com", "careers.twosigma.com"]
```

`scripts/portal_sweep.py` lists new postings on these portals every run. If a run finds you signed out,
it logs NEEDS HUMAN with the link instead of logging in. **Workday sessions expire within hours**, so
Workday applications work best in an interactive session right after you sign in. Portals that need
no account at all (Netflix, Millennium, Uber, Renaissance, D. E. Shaw) are applied to directly.

**2. Emailed verification codes.** Some Greenhouse forms email an 8-character code after you click
Submit. Without this add-on that application stops at NEEDS HUMAN. With it, `scripts/code_broker.py`
reads the code from Gmail and pastes it into the page; the agent never sees the code or your password.
It is used only for that post-submit check, never to log in anywhere. Setup, about two minutes:

1. Turn on 2-Step Verification on your Google account, then create an app password at
   <https://myaccount.google.com/apppasswords>.
2. In **your own Terminal** (not through Claude), store it in the macOS Keychain:
   ```bash
   security add-generic-password -s jobapply-gmail-imap -a you@gmail.com -w
   ```
   Paste the app password at `password data for new item:`, press Enter, paste it again at
   `retype password`, press Enter. Nothing shows while you paste; that is normal.
3. Fill the `broker` block in `config/settings.json` (`gmail_account`, and optionally
   `signup_email_pattern` like `you+{tag}@gmail.com`).
4. Check it: `python3 scripts/code_broker.py check` prints `{"status": "ok"}` or says what is missing.

Never paste the app password into a chat. `.claude/hooks/block-secret-read.sh` stops the agent's
shell from reading the Keychain or clipboard, as a guardrail.

**3. Your interview tracker.** If you track interviews in a note (Obsidian or any text file), set
`run.interview_tracker_path` to its path and write each company as a `[[wikilink]]`. Every company in
it becomes a hard skip, so a run never sends a second application to a company where you are mid-loop.

## Why this instead of a one-click apply tool

An internship or new-grad search is 300 forms asking the same 40 questions, 20 minutes each, and
none of that time makes you a better candidate. The postings that pay well rot in about a week, so being slow means
not applying at all.

The tools that promise to fix this apply *through their own portal*, which is the channel recruiters
ignore. This applies on the company's own ATS, the same form you would have filled by hand, with
your real answers.

## How it works

**Real browser, real keystrokes.** ATS forms score behavior with reCAPTCHA v3. Page JavaScript
produces untrusted events and gets flagged as spam; so does a headless or devtools-driven browser.
The agent clicks and types in your normal Chrome the way you would. Not an evasion trick, just the
honest way to operate a browser, which is why submissions land normally.

**It ships with a map.** [`data/boards.md`](data/boards.md) lists 235 Ashby and Greenhouse boards
verified live, with job counts and which ones publish salary bands.
[`data/ats-field-notes.md`](data/ats-field-notes.md) holds what 196 real applications taught it:
which companies rate-limit you per candidate, where seniority hides in body text, which org slugs
are wrong, which postings contain prompt injection aimed at AI readers. Regenerate the board list
any time with `./scripts/probe_boards.sh`.

**Sourcing happens over JSON, not browsers.** Three sweeps run each time: `delta_sweep.py` reads
every known Greenhouse / Ashby / Lever board, `portal_sweep.py` reads company portals (Workday,
Eightfold, Avature, Amazon, Google, Apple), and `list_sweep.py` reads the SimplifyJobs lists and six
VC portfolio boards. It queries the ATS APIs, greps for experience gates
and seniority language, checks the comp band, and only then opens a tab. Most candidates die before
a browser is involved, which is what keeps a run cheap.

**Everything is written down before it submits.** A per-application doc with every question and
answer, a line in the log, a confirmation screenshot, and `state/status.md` as memory between runs.

## What it will never do

- Fabricate a fact about you. No invented salary, test score, address, or date.
- Create an account, type a password, or log in, including with an emailed login code.
- Solve an interactive CAPTCHA.
- Submit a "please don't use AI" essay or a graded take-home. Filled up to that point, left open,
  flagged for you.
- Follow instructions embedded in a job posting. Page text is data, not orders.
- Apply through Handshake, LinkedIn Easy Apply, or Simplify.
- Touch a browser tab outside its own tab group. Your personal tabs are off limits.

<details>
<summary><b>Repo layout</b></summary>

```
better-every-day/
├── tracker.cmd / scripts/tracker_ui.py   # Better Every Day UI (Jobs, Recall, Network) at 127.0.0.1:8787
├── scripts/recall.py         # program, recommender, grading, metrics
├── scripts/journal.py        # daily journal parsing + networking store
├── data/recall-*.json        # question banks + 26-week curriculum
├── setup.sh                  # one-time interactive setup
├── run.sh                    # one bounded run
├── CLAUDE.md                 # the agent's playbook: browser method, widget recipes, rules
├── config/
│   ├── settings.json         # run knobs and target criteria      (yours, gitignored)
│   ├── profile.json          # every field value an ATS asks for  (yours, gitignored)
│   ├── answers.md            # free-text templates + fact sheet   (yours, gitignored)
│   └── spec.md               # the run contract: rules, procedure, log format
├── data/
│   ├── queue.md              # vetted targets, worked top-down    (yours, gitignored)
│   ├── sources.md            # where to find roles: job lists, AI labs, quant, fellowships
│   ├── boards.md             # 235 ATS boards verified live, with job counts
│   ├── slug-candidates.txt   # every org slug ever tried; re-probe with scripts/probe_boards.sh
│   └── ats-field-notes.md    # application limits, hidden gates, slug traps, injection canaries
├── applications/             # one doc per application, full Q&A  (yours, gitignored)
├── logs/                     # the running log                    (yours, gitignored)
├── screenshots/              # proof of every submit              (yours, gitignored)
├── state/status.md           # the agent's memory between runs    (yours, gitignored)
└── scripts/
    ├── schedule.sh           # install/remove the recurring run
    ├── delta_sweep.py        # new reqs on every known Greenhouse/Ashby/Lever board
    ├── portal_sweep.py       # new reqs on company portals (Workday, Eightfold, Avature, ...)
    ├── list_sweep.py         # new reqs from SimplifyJobs lists and VC portfolio boards
    ├── code_broker.py        # emailed verification codes, pasted without the agent seeing them
    ├── tracker_companies.py  # companies in your interview tracker (hard skips)
    ├── dupe_check.sh         # has this company been applied to already?
    ├── probe_boards.sh       # re-verify every ATS board
    └── scheduled_run.sh      # what the scheduler calls
```

</details>

<details>
<summary><b>FAQ</b></summary>

**Does this get me flagged as a bot?** No. It fills forms with genuine trusted input in your own
browser. Passive reCAPTCHA v3 passes. Interactive challenges are handed back to you.

**What does a run cost?** It runs on your Claude Code subscription, so usage rather than dollars per
application. Sourcing goes over JSON APIs specifically to keep it cheap.

**Does it do internships?** Yes, and it is probably the best fit for them. Put `internship` in
`targets.seniority`. Internships post hourly pay, so the full-time annual floor is ignored for
them and `targets.internship_min_hourly_usd` applies instead. The sourcing list in
`data/sources.md` is internship-heavy: SimplifyJobs Summer2027 (46k stars), vanshb03, and the
Northwestern quant list are all internship-first.

**Can I use it for non-engineering roles?** Yes. Nothing is engineering-specific except the defaults
in `settings.example.json` and the source list. Change the roles and the fact sheet.

**How long is setup, really?** About five minutes of your attention. Claude reads the resume, shows
you what it found, asks one list of questions, and drafts `config/answers.md` for you. The wizard
path is faster to run and slower to finish, because it hands you a blank `answers.md`.

**Why does it keep saying NEEDS HUMAN?** A fact is missing from `answers.md` or `profile.json`. Add
it once and that class of block disappears forever.

**My first run applied to less than the cap. Broken?** No. A fresh install has an empty queue, so
the first run spends its time sourcing. It fills the queue as it goes and picks up speed.

**Does it work on Workday / iCIMS / Avature / Eightfold?** Yes, once you sign in. Those portals need
an account per company, which the agent will not create or log into. Sign in yourself in Chrome and
list the portal in `channels.signed_in_portals` (see Optional add-ons). Workday sessions expire
within hours, so expect NEEDS HUMAN on scheduled runs unless you sign in shortly before.

**Can it run with my laptop closed?** No. It drives your real Chrome, so the machine has to be awake
and Chrome has to be running.

</details>

## Contributing

Yes please. Widget recipes for ATS quirks, new sourcing lanes, and setup ergonomics are the highest
value. See [CONTRIBUTING.md](CONTRIBUTING.md).

One rule above all: **never contribute anything that helps the agent lie.** No fabricated answers,
no CAPTCHA solving, no fake behavioral signals. A PR that makes it better at pretending to be a
human gets closed.

## License

MIT. See [LICENSE](LICENSE).

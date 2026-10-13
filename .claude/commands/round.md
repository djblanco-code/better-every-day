---
description: Run a full job application round (finds jobs, applies until none are left or the usage limit hits)
model: sonnet
---

Run a job application round for the user. Follow CLAUDE.md. Do not ask the user anything; they asked never to be stopped. Work in this order:

1. **Preflight (30 seconds).** `python3 scripts/pool.py stats`. Call `list_connected_browsers`: if it is empty, retry a few times over two minutes, then tell the user to open Chrome with the Claude extension signed in, and stop. Close only leftover job-application tabs in your own tab group.
2. **Refresh the queue.** `python3 scripts/collect.py` once, in the FOREGROUND (Bash timeout 1500000). It skips itself if it ran in the last 20 minutes. Never run the sweeps or JobDataLake yourself.
3. **Apply from the saved queue first.** Loop on `python3 scripts/pool.py take`; it claims ONE lead, newest first and best fit first. For each lead: `./scripts/dupe_check.sh "<Company>" <job id>`, open the url, confirm it is live, read the requirements, fill the form with trusted input, submit, screenshot, write the per-application doc and the tracker row. Then record it: `python3 scripts/pool.py mark <id> applied|closed|skipped|needs_human "<reason>"`. A posting that is not live is `closed`. Do not skip a lead for years, pay or "off-target" unless the posting itself shows a hard mismatch; the settings already applied the gate (see `targets` in config/settings.json).
4. **When the queue is thin (fewer than 5 ready), use GrepJob.** If `mcp__grepjob__search_jobs` is available (the user logs in once with `/mcp`): query once per location in `targets.locations`, seniority entry level and mid level, min_salary = `targets.min_annual_comp_usd`, a few pages each. Write the rows to a JSON file `[{company, title, location, url, band, desc}]` and run `python3 scripts/collect.py --import <file>`. They are vetted and queued like any other lead; then keep taking. If GrepJob says it needs authentication, note it in the status block and carry on.
5. **When `take` says NO READY LEADS,** run `python3 scripts/collect.py` again if it has not run in 20 minutes, then `take` again. Only a second NO READY LEADS means the round is over.
6. **Never stop for a question.** Blocked forms go to the "Apply yourself" table in logs/job-tracker.md, not to the user.
7. **Token care.** Prefer `find` and `read_page` refs over screenshots. Take a screenshot after a file upload and for the confirmation JPG. Do not re-read files you already read.
8. **End of round.** Close every tab in your group, confirm `tabs_context_mcp` says no group exists, add a short block to the top of state/status.md, and report: submitted count, skipped, needs-human, and what is left in the queue.

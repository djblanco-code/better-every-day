## ★ FIRST RUN — a fresh clone has no config. Onboard the user, do not apply. ★
If `config/profile.json`, `config/answers.md`, or `config/settings.json` is missing, this is a new
install. **Do not open a browser and do not apply to anything.** Set them up first.

**Do not offer a menu. Start the setup yourself, at step 1, in the same message.** A new user has
no basis to choose between paths, and the choice is the first thing that stalls them. You read
their resume and draft the hard file (`config/answers.md`) for them; that is strictly better than
leaving a blank template, so just do it. A `./setup.sh` terminal wizard also exists — mention it
only if the user asks for a hands-off or non-interactive path.

### Setup, step by step
1. **Copy the templates first** if they are absent: `config/{profile,settings}.example.json` →
   `config/{profile,settings}.json`, `config/answers.example.md` → `config/answers.md`,
   `data/queue.example.md` → `data/queue.md`. Create `applications/ logs/ screenshots/ state/`.
2. **Ask for their resume** and read it (the Read tool opens PDFs). Copy it to the path in
   `profile.json.resume`, default `data/resume.pdf`.
3. **Draft `config/profile.json` from the resume**: name, email, phone, location, school, degree,
   major, graduation, GPA, LinkedIn, GitHub, site. Then **show every extracted value and have the
   user confirm or correct each one.** If the resume does not state something, leave it empty and
   ask. Never infer an address, a GPA, or a graduation date.
4. **Ask EVERY remaining question in ONE numbered list. This is the only question you get to ask.**
   Not one batch about them and a second batch about targeting later; both go in the same list. A
   user who cannot see how many rounds are left assumes it is endless and quits partway, and a
   second list after they thought they were finished is worse than a long first one. Say the count
   up front ("fifteen questions, then I write the files"), mark the optional ones as optional, give
   the default you will use for anything they skip, and tell them to answer in one message.

   **Build the list by walking `config/profile.example.json` and `config/answers.example.md` key by
   key**, not from memory and not from the topics below. Those files are the checklist. A key you
   forget is exactly how a second round happens, which is the thing this rule exists to prevent.
   Keys that ship with a working default (desired compensation, how they heard about the company,
   notice period) are NOT questions: apply the default, say in one line which defaults you took,
   and move on. `highest_education_completed_answer` is one of these: derive it from the resume as
   the degree in progress with its expected date, never as high school, and state what you wrote.

   Two exceptions to the default-instead-of-question rule. **The three availability answers
   (`work_availability_heavy_hours`, `work_availability_travel_25pct`,
   `work_availability_50pct_support`) get asked as one combined question**, because a default Yes
   silently commits a stranger to nights, weekends, travel, and half their week on support tickets.
   A neutral default like "decline to self-identify" may be assumed; a promise about how someone
   will live may not. The same goes for anything else where the default is a commitment rather than
   a decline.
   - *About them, and this list is the minimum, not a sample:* preferred vs legal first name;
     native-script legal name, asked for verbatim (`name_native_language`) and never
     transliterated; **a personal non-`.edu` email, because a resume usually lists only the school
     one and some ATS reject `.edu`**; mailing address; work authorization and whether they need
     sponsorship; citizenship, for the export-control question; **`college_start_date`, the month
     and year they started, which is almost never on a resume**; **`high_school_name` and
     `high_school_grad_year`, optional but required by some forms**; earliest start date; GPA and
     whether to fill it when optional; transcript path; pronouns; and all four EEO answers listed
     one by one, race, gender, veteran status, and disability (offer "decline to self-identify" as
     the default for each). Never infer any of the four from a name, a photo, or a resume, and
     never collapse them into a single "EEO answers" question, which is how gender ends up unset.
   - *About targeting:* roles and titles; internship, new-grad, or both; locations plus whether
     remote counts; full-time compensation floor; internship hourly floor; their quality bar in
     their own words (`prestige_note`); companies to never apply to. Say that the annual floor does
     not apply to internships, since that surprises people.

   Follow up ONLY on an answer that came back blank, self-contradictory, or unusable, and say that
   it is the last of it. **A field you forgot to ask about is not grounds for a second round.**
   Take the template's default, name the default you took in one line, and let them correct it if
   they care. A second list, arriving after the user thought they were done, is the failure this
   whole step is written to prevent.
5. **Draft `config/answers.md`, the file that decides everything, and write `config/settings.json`
   from the targeting answers.** Write the templates from their real work, keeping every number
   exactly as the resume states it. Build the fact sheet with one line per job, project, and
   result. Then **read the templates back and get explicit confirmation.** If a bullet is vague
   ("improved performance"), ask for the number instead of inventing one. This is the step that
   makes their runs work, so do not rush it.

   **Before you read the templates back, check every number and every job title in them against
   the resume, one at a time.** A figure that is close but not equal is a fabrication on a real
   application. Carrying over an illustrative number from the example template is the specific
   mistake to watch for: `config/answers.example.md` ships with no example numbers precisely
   because they get copied. Titles are facts too: Co-founder is not CTO, intern is not engineer.

   **Ask for the confirmation in concrete terms, never as "do these read as yours?"** That phrasing
   gives the user nothing to check against, so they skim and approve. Ask for the two specific
   things instead, and name the figures you want them to verify:
   > "Two things to check. Does this sound like you rather than like a brochure, and are these
   > numbers right: 90% acceptance, two weeks down to two days, Co-founder. Change anything that is
   > off and I will rewrite it."
   Quote the actual figures from their drafts, not these. The point is that they are checking
   claims they can verify, not judging prose.
6. **Offer to install the schedule**, explain the cadence, and if they say yes run
   `./scripts/schedule.sh install` for them rather than printing it for them to run.
6b. **Mention the optional add-ons in one short list, and do not push them.** Each needs a step only the
   user can take, and none blocks the first run. See README "Optional add-ons":
   - Company portals that need an account: they sign in once in Chrome, you add the host to
     `channels.signed_in_portals`. You never create an account or log in.
   - Emailed verification codes: they create a Gmail app password and store it with
     `security add-generic-password -s jobapply-gmail-imap -a <gmail> -w` **in their own Terminal**
     (Windows: `cmdkey /generic:jobapply-gmail-imap /user:<gmail> /pass` in their own PowerShell). Tell them
     never to paste it into the chat. Then run `python3 scripts/code_broker.py check` for them.
   - Interview tracker: set `run.interview_tracker_path` to their note, companies as `[[wikilinks]]`.
7. **Run the first application yourself, supervised.** Setup ends with the user having watched you
   work, so ending on homework is the wrong last impression. **Never offer a run that cannot
   submit.** A run that fills a form and then throws it away is a demo, and the user came here to
   apply to jobs, so it wastes the one posting it touched and teaches them nothing they could not
   learn from the checkpoint. Ask one question: do it now, or not yet.
   - **Now (recommend this).** Source one real posting, fill every field, screenshot it, write the
     log and the per-application doc, then **stop and show them everything before clicking
     submit**. On their yes, submit for real. On their no, close the tab and send nothing. A real
     application with a checkpoint.
   - **Not yet.** Give them `./run.sh 1` and move on.

   Do it in this session; you do not need `./run.sh`. Read `config/settings.json` and obey it
   directly. When it finishes, name the posting and point at the `applications/` doc and the
   screenshot.

   **Preflight the browser before you start, and never make the user guess what is wrong.** Call
   `list_connected_browsers`. Installing the extension cannot be automated: it is a Chrome Web
   Store install, a sign-in, and per-site permission grants, all user gestures by design. So detect
   the state and give the exact next step:
   - *Empty list on the first call* → the extension is not connected. Tell them to install it from
     https://claude.ai/chrome, sign in with the SAME account as this Claude Code session, and say
     when it is done. Then re-check. Do not start a run and discover it mid-form.
   - *Connected but every page action returns "Couldn't determine which page this action targets"*
     → a different failure, usually transient. Wait and retry; it clears in 3-15 minutes.
   - *Connected but the ATS domain is not permitted* → the extension grants access per site. Tell
     them which domain to allow in the extension's settings.

   **Say plainly what happens after the first one**, because it is the thing users get wrong:
   scheduled runs submit on their own. There is no per-application checkpoint once the schedule is
   installed. The supervised checkpoint exists for the first run, so they can see the quality
   before handing over the wheel. `./run.sh` cannot offer one either: it launches a headless
   `claude -p` session with nobody there to approve. If they want a checkpoint on every
   application, the answer is to ask you for a run inside an interactive session and say "stop
   before submitting", not a flag.
   - The same rule holds for the schedule in step 6 and for anything else the setup could do
     itself. Offer to run it, get a yes, run it. A command in a code block is the fallback for
     when they decline, not the default.

### Rules during onboarding
- **Never invent a fact to fill a field.** An empty value that becomes a question later is correct;
  a plausible guess is not. This is the whole premise of the project.
- Confirm before writing each file, and say what you wrote.
- Tell the user that `profile.json`, `answers.md`, `settings.json`, and everything under
  `applications/ logs/ screenshots/ state/` are gitignored, so their data never leaves the machine.
- If they ask you to skip the confirmation step, still show the values once before writing.


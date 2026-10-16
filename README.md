# EasyApplyJobsBot

A Python + Selenium bot that applies to jobs automatically on **Dice**, **ZipRecruiter** and **Wellfound**.
Unanswered application questions are collected, answered by an LLM, and reused on every later run.

> Forked from [wodsuz/EasyApplyJobsBot](https://github.com/wodsuz/EasyApplyJobsBot) — see [Credits](#credits--support) at the bottom.

---

## Table of contents

- [What runs what](#what-runs-what)
- [1. Install](#1-install)
- [2. Configure config.py](#2-configure-configpy)
- [3. Configure .env (the AI model)](#3-configure-env-the-ai-model)
- [4. Run it](#4-run-it)
- [How the AI answering works](#how-the-ai-answering-works)
- [The question feedback loop](#the-question-feedback-loop)
- [Answering questions by hand (before you run)](#answering-questions-by-hand-before-you-run)
- [Output files](#output-files)
- [Switching AI providers](#switching-ai-providers)
- [Docker](#docker)
- [Troubleshooting](#troubleshooting)
- [Security](#security)
- [Credits & support](#credits--support)

---

## What runs what

| File | Purpose |
| --- | --- |
| [main.py](main.py) | Entry point. Runs whichever of Dice / ZipRecruiter / Wellfound you enable. |
| [config.py](config.py) | All behaviour: credentials, search filters, your profile answers. |
| [.env](env.example) | LLM provider, model and API key only. |
| [jobsite.py](jobsite.py) | Shared browser + form-filling engine for all three sites. |
| [dice.py](dice.py) / [ziprecruiter.py](ziprecruiter.py) / [wellfound.py](wellfound.py) | Per-site search and apply logic. |
| [answer_generator.py](answer_generator.py) | Answers unknown questions (mappings → LLM → defaults). |
| [process_pending_to_yaml.py](process_pending_to_yaml.py) | Turns `pendingQuestions.yaml` into saved answers. |
| [process_manual_answers.py](process_manual_answers.py) | Seeds questions from the manual CSV into the answer bank for you to fill in. |
| [llm.py](llm.py) | OpenAI-compatible LLM client (auth, retries, model quirks). |
| [retry_failed.py](retry_failed.py) | Retries jobs that previously failed. |
| [linkedin.py](linkedin.py) | LinkedIn bot. **Not** wired into `main.py`; run directly if you want it. |

---

## 1. Install

**Prerequisites:** Python 3.9+ and Google Chrome. ChromeDriver is **not** a manual step — `webdriver_manager` downloads the matching driver automatically on first run.

### Windows (PowerShell)

```powershell
cd e:\Work\EasyApplyJobsBot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If activation is blocked:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### macOS / Linux

```bash
cd EasyApplyJobsBot
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### What gets installed

[requirements.txt](requirements.txt) — `selenium`, `webdriver_manager`, `selenium-stealth`, `pyyaml`, `requests`, `python-dotenv`, `PyPDF2`.

The last three matter: `requests` + `python-dotenv` are required by [llm.py](llm.py), and `PyPDF2` is needed only if your profile is a PDF rather than a `.txt`.

> `requirements.yaml` is a leftover from upstream and lists only the original three packages. Always install from `requirements.txt`.

### Verify

```powershell
python -c "import selenium, yaml, requests, dotenv; print('deps OK')"
```

---

## 2. Configure config.py

Everything except the LLM lives in [config.py](config.py). Edit it directly — it's plain Python.

### Pick your sites and sign-ins

```python
runDice         = True       # config.py:10
runZipRecruiter = False      # config.py:11
runWellfound    = False      # config.py:12

diceEmail           = "you@example.com"
dicePassword        = "..."
zipRecruiterEmail   = ""
zipRecruiterPassword = ""
wellfoundEmail      = ""
wellfoundPassword   = ""
```

`main.py` prints an error and exits if all three are `False`.

If you leave a password blank, the bot opens the login page and waits `manualLoginWaitSeconds` (default 300) for you to sign in by hand. The session is then cached in `cookies/`, so later runs skip the login.

### Point at your résumé

```python
resumePath = r"data/Full-stack.pdf"   # config.py:23 — relative to the project root
```

A **relative path is resolved against the project root**, so it works no matter which directory you launch from, and an absolute path still works if you prefer one.

This one file does double duty:

1. **Uploaded** to applications that ask for a résumé ([dice.py:137](dice.py#L137)).
2. **Read as the profile the AI answers from** — the text is extracted with `PyPDF2` and sent with every question, so answers are grounded in your actual résumé rather than guesses.

On startup you'll see which file was picked up:

```
✓ Resume loaded: data\Full-stack.pdf (9486 chars)
```

If the résumé is missing or is a scanned image with no extractable text, you get an explicit `⚠ ... - AI answers disabled` instead of silent fallback to generic answers. The search order is `config.resumePath` → `profile.txt` → `resume.pdf`, so a plain-text `profile.txt` is an easy way to give the AI more context than the PDF contains.

> ⚠️ Keep `config.py`'s `yearsOfExperience` consistent with the résumé. The deterministic answers use `config.py`, while AI answers read the résumé — your résumé currently supports `8+ years` on some questions while `yearsOfExperience = 6`.

### Search filters

```python
searchLocations   = ["United States"]   # config.py:19
maxPagesPerSearch = 5                   # config.py:20
keywords          = [...]               # config.py:171 — job titles to search
experienceLevels  = ["Entry level", "Associate", "Mid-Senior level"]
datePosted        = ["Past Month"]
jobType           = ["Full-time", "Part-time", "Contract"]
remote            = ["Remote"]
salary            = ["$40,000+"]
blacklistCompanies = []                 # companies to skip
blackListTitles    = [...]              # title keywords to skip
```

### Your profile (used to answer questions)

Lines 117–156 hold the facts the bot and the LLM answer from: `yearsOfExperience`, `currentJobTitle`, `currentEmployer`, `educationLevel`, `school`, `skillsSummary`, `city`/`state`/`country`, `desiredPay`, `availabilityAnswer`, `aboutMeAnswer`, `whyCompanyAnswer`, and more. Fill these in accurately — wrong values here produce wrong applications.

### Behaviour flags

| Setting | Line | Meaning |
| --- | --- | --- |
| `dryRun` | 397 | **Set `True` for your first run.** Fills forms but never clicks final submit. |
| `headless` | 159 | Run Chrome with no visible window. |
| `techBlacklist` | 305 | Skip jobs whose stack is blacklisted in [techblacklist.py](techblacklist.py). |
| `outputSkippedQuestions` | 312 | Write unanswered questions to `pendingQuestions.yaml`. Keep `True`. |
| `autoLearnAnswers` | 313 | Reuse saved answers on later runs. |
| `followCompanies` | 307 | Follow the company after applying. |
| `useAiAutocomplete` | 315 | Legacy upstream flag — **read by nothing**, leave it alone. |

---

## 3. Configure .env (the AI model)

`.env` holds **only** the LLM settings. Create it from the template:

```powershell
Copy-Item env.example .env
```

### Active setup: OpenAI, cheapest model

```ini
LLM_URL=https://api.openai.com/v1
LLM_MODEL=gpt-6-luna
OPENAI_API_KEY=sk-proj-...
LLM_TIMEOUT=600
```

`gpt-6-luna` is OpenAI's cheapest text model at **$0.10 per 1M input / $0.50 per 1M output tokens**.

**Only four variables are read by any code**, all in [llm.py](llm.py):

| Variable | Required | Notes |
| --- | --- | --- |
| `LLM_URL` | yes | Any OpenAI-compatible `/v1` base URL. |
| `LLM_MODEL` | yes | Model ID. |
| `LLM_API_KEY` | remote only | **Checked first**, then `OPENAI_API_KEY`. If both are set, `LLM_API_KEY` wins. |
| `LLM_TIMEOUT` | no | Seconds per request, default 90. |

Everything else in `env.example` (`GEMINI_API_KEY`, `CAPSOLVER_API_KEY`, `CHROME_PROFILE`, `APPLY_*`) has **no reader anywhere in this codebase** — those lines are aspirational, not wired up.

### Get an API key

An API key is **not** the same thing as a ChatGPT Plus/Pro subscription. API usage is billed separately:

1. Go to [platform.openai.com/api-keys](https://platform.openai.com/api-keys) and create a key.
2. Add credit under **Billing** (a few dollars lasts a very long time here).
3. Paste it as `OPENAI_API_KEY` in `.env`.

### Verify your key works

```powershell
python -c "from llm import LLMClient; c=LLMClient.fromEnv(); print(c.model, '->', c.check() or 'OK')"
```

`OK` means the key is valid, the endpoint answered, and your model is available to the account. This call is free — it only lists models.

### What it costs

Roughly **1,400 input + 80 output tokens per question ≈ $0.0002**. Ten dollars covers about **50,000 questions**. Your profile text is placed at the start of every prompt, so OpenAI's automatic prefix caching applies its much cheaper cached-input rate on repeat calls.

---

## 4. Run it

Always start with `dryRun = True` in [config.py:397](config.py#L397).

```powershell
.\.venv\Scripts\Activate.ps1
python main.py
```

Chrome opens, logs in (or waits for you), searches each keyword × location, and walks each job's apply flow. Watch the console: `🧪 DRY RUN - Would apply to this job: ...` means the form was filled but nothing was submitted.

When the output looks right, set `dryRun = False` and run again.

### Other entry points

```powershell
python process_pending_to_yaml.py   # answer collected questions via the LLM
python answer_generator.py          # same, with a detailed report
python retry_failed.py              # retry jobs that failed earlier
python linkedin.py                  # LinkedIn bot (separate from main.py)
```

---

## How the AI answering works

When a form field has no saved answer, [answer_generator.py](answer_generator.py) resolves it in a strict order — this is what keeps cost and risk down:

```
1. Keyword mapping      → free, deterministic   (name, email, phone, LinkedIn, visa, consent…)
2. Sensitive guard      → free, never asks AI   (see below)
3. LLM call             → ~$0.0002              (open-ended questions only)
4. Generic default      → free                  (if the model declines)
```

**1 — Keyword mapping.** Known facts answer themselves. `"What is your first name?"` → `Paula`, no API call. Mappings live in `get_mapped_answer` ([answer_generator.py:129](answer_generator.py#L129)).

On a multiple-choice field, a mapped value that matches none of the offered options is discarded and the question goes to the model instead — otherwise a dropdown asking for a range would be answered with the unusable string `5+ years`.

**2 — Sensitive guard.** Questions matching `SENSITIVE_PATTERN` ([llm.py:16](llm.py#L16)) — gender, race, veteran status, disability, date of birth, criminal history, salary, citizenship, bank details — are **never sent to the model**. On multiple-choice fields the bot takes the opt-out option, and where none exists it refuses rather than guessing:

| Question | Result |
| --- | --- |
| What is your gender? | `Prefer not to disclose` |
| Please select your race/ethnicity | `I do not wish to answer` |
| Are you a protected veteran? | `Decline to self-identify` |
| What is your current base salary? | `UNKNOWN` → left for you |

**3 — LLM call.** Open-ended questions get your profile text plus the question. The model answers only from your profile and replies `UNKNOWN` rather than inventing employers, degrees or metrics. For proficiency and level questions it infers the level from the years and projects your profile shows:

| Question (Beginner / Intermediate / Advanced / Expert) | Answer |
| --- | --- |
| Rate your proficiency with React | `Advanced` |
| Rate your proficiency with Python | `Intermediate` |
| Years building REST APIs (`0-1` / `2-4` / `5-7` / `8+`) | `5-7 years` |
| Rate your proficiency with COBOL on IBM mainframes | `UNKNOWN` → left for you |

**4 — Fallback.** Free-text questions get a neutral blurb. Multiple-choice questions take `Yes` when it is one of the options, and otherwise return `UNKNOWN` — the bot will not pick an arbitrary option, because guessing on an unordered scale risks claiming skill you don't have. `UNKNOWN` answers are **not** written to your answer bank; they stay in `pendingQuestions.yaml` for you to answer.

> ⚠️ Free-text sensitive questions (date of birth, felony convictions) fall through to the generic experience blurb, which is not a real answer. Review those in `additionalQuestions.yaml` by hand.

To change how levels are judged, edit the option prompt at [answer_generator.py:107-114](answer_generator.py#L107-L114).

---

## The question feedback loop

The bot gets better every run because it remembers answers:

```
main.py applies to jobs
      │
      ├─ unknown question  →  pendingQuestions.yaml        (jobsite.py:463)
      │
      ▼
process_pending_to_yaml.py  →  mapping / LLM / default
      │
      ▼
additionalQuestions.yaml    →  reused automatically next run
```

- **Wellfound runs this automatically** after each session ([wellfound.py:162](wellfound.py#L162)).
- **Dice and ZipRecruiter do not** — run `python process_pending_to_yaml.py` yourself after a session.

Questions the model refuses (`UNKNOWN`) stay in `pendingQuestions.yaml` — see the next section for answering those by hand.

---

## Answering questions by hand (before you run)

Three files are involved. Only one of them holds your answers:

| File | Role | You edit it? |
| --- | --- | --- |
| `additionalQuestions.yaml` | **The answer bank.** The only file the bot reads answers from. | ✅ Yes — this is where answers go. |
| `pendingQuestions.yaml` | Queue of questions with no answer yet, plus their options. | Rarely — it's an inbox. |
| `data/Manual Answer Questions.csv` | Audit log of questions that needed attention, with company, job title and link. | No — it has **no answer column**. |

### The answer bank format

```yaml
inputField:
  First Name: Paula
  Phone Number: '6871072627'
radio:
  Are you comfortable with W2 role?: Yes
dropdown:
  Highest level of education: Bachelor's Degree
checkbox:
  I agree to the privacy policy: Yes
```

Three rules that matter when writing these by hand:

1. **Keys are keyword matches, not exact questions.** A key matches if it appears in the question as a whole word, or if the key is 12+ characters and appears inside the normalized question ([jobsite.py:432](jobsite.py#L432)). So `email` answers *"What is your work email address?"*. Matching is case-insensitive.
2. **The longest matching key wins** ([jobsite.py:445](jobsite.py#L445)). Add a specific long key to override a short generic one.
3. **An empty answer means "ask me, don't guess".** A key with a blank or `null` value is registered as a *manual* question: the bot flags it `🚩 Needs manual answer` and does not auto-fill it ([jobsite.py:149-161](jobsite.py#L149-L161)). You can also be explicit:

```yaml
inputField:
  What is your expected salary?: ""          # flagged, never auto-answered
  Describe your biggest project: { answer: "…", manual: false }
```

The bot **re-reads this file while running** ([jobsite.py:167](jobsite.py#L167)) and prints `🔄 additionalQuestions.yaml changed, reloaded saved answers` — you can fix an answer mid-session without restarting.

### The recommended order before a run

```powershell
# 1. Pull every question that still needs a human into the answer bank as blank entries.
python process_manual_answers.py

# 2. Open additionalQuestions.yaml and fill in the blanks you care about.

# 3. Optional: let the AI answer whatever is queued in pendingQuestions.yaml.
python process_pending_to_yaml.py

# 4. Run the bot (dryRun = True first).
python main.py
```

**Step 1** reads `data/Manual Answer Questions.csv`, takes rows whose `Status` is `Unanswered` or blank, and adds any question not already in the bank with an empty or guessed answer ([process_manual_answers.py:85](process_manual_answers.py#L85)). It **does not read answers from the CSV** — the CSV has no answer column, so its only job is to seed the question keys for you to fill in. Your file currently holds **1,154 unanswered rows** out of 1,311.

**Step 3** answers the `pendingQuestions.yaml` queue using mappings → AI → fallback, writes results into the bank, and removes what it answered. Entries it can't justify stay queued.

### Answering a pending question manually instead

`pendingQuestions.yaml` stores the *options*, not an answer — `null` means a free-text field:

```yaml
radio:
  What is your current US visa status?: US Citizen|Green Card|H1B|OPT/CPT|Other
inputField:
  what cost estimating software have you used?: null
```

To answer one by hand, copy the question into the matching section of `additionalQuestions.yaml` with your answer — picking one of the pipe-separated options verbatim for choice fields — and delete it from `pendingQuestions.yaml`.

> ⚠️ Two different code paths append to `Manual Answer Questions.csv` with **different column 8 meanings** — `saveUnansweredQuestion` writes the section name ([jobsite.py:496](jobsite.py#L496)), while `logQuestionList` writes the saved answer ([jobsite.py:1658](jobsite.py#L1658)). Your CSV contains both shapes, so `process_manual_answers.py` mis-reads the section on some rows and defaults them to `inputField`. Check the section of anything it adds.

---

## Output files

| Path | Contents |
| --- | --- |
| `data/Applied Jobs DATA - YYYYMMDD.txt` | Per-day log of every job, with a session summary. |
| `data/Manual Answer Questions.csv` | Questions needing a human answer. |
| `pendingQuestions.yaml` | Questions awaiting an answer. |
| `additionalQuestions.yaml` | Your answer bank, reused on every run. |
| `cookies/` | Cached logins, so you don't re-authenticate each run. |

---

## Switching AI providers

Change two lines in `.env` — no code edits. [llm.py](llm.py) handles auth, retries and per-provider parameter quirks.

**Local Ollama (free, no API cost):**

```ini
LLM_URL=http://localhost:11434/v1
LLM_MODEL=qwen3:8b
```

Needs [Ollama](https://ollama.com) installed plus `ollama pull qwen3:8b`. No API key required — local URLs skip the key check.

**DeepSeek (cheaper than OpenAI):**

```ini
LLM_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
LLM_API_KEY=sk-...
```

**No LLM at all:** delete or comment out `LLM_URL` and `LLM_MODEL`. The bot prints `⚠ No LLM_URL/LLM_MODEL in .env - using smart defaults` and runs on keyword mappings and defaults only, at zero cost.

---

## Docker

```bash
docker-compose up --build        # foreground
docker-compose up -d --build     # background
docker-compose logs -f
docker-compose down
```

[docker-compose.yml](docker-compose.yml) mounts `config.py`, `.env`, `additionalQuestions.yaml`, `data/` and `cookies/` from the host, so you can edit configuration without rebuilding. `.env` is mounted rather than copied — secrets never go into the image.

---

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `⚠ No LLM_URL/LLM_MODEL in .env` | No `.env`, or those two keys are commented out. |
| `rejected the API key (HTTP 401)` | Bad or revoked key. Regenerate at platform.openai.com. |
| `returned HTTP 429` | No credit balance, or rate limited. Check Billing. |
| `Model X is not available` | Model retired or not enabled for your account. `gpt-4o-mini` and the GPT-5 line are gone; use `gpt-6-luna`. |
| `is not reachable (ReadTimeout)` | Transient. The preflight retries once; `chat()` retries 3×. Raise `LLM_TIMEOUT` if persistent. |
| `Ollama is not reachable` | Ollama isn't running, or the model isn't pulled. |
| Resume upload fails | `resumePath` in `config.py` points at a file that doesn't exist. |
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| ChromeDriver / version mismatch | Update Chrome; `webdriver_manager` re-downloads the matching driver. |
| Bot exits immediately | All of `runDice` / `runZipRecruiter` / `runWellfound` are `False`. |
| Logged out every run | Delete `cookies/` and sign in again. |

---

## Security

- `.env` and `cookies/` are gitignored ([.gitignore:123](.gitignore#L123)). Keep it that way.
- `config.py` **is** tracked and holds your passwords once you fill it in. Don't commit it after editing — `git update-index --skip-worktree config.py` helps.
- API keys and ATS passwords sit in `.env` in plaintext. If that file has ever been shared or synced, rotate the keys.
- Sensitive personal questions are never sent to the LLM — see [the guard](#how-the-ai-answering-works).

---

## Credits & support

This is a fork of **[wodsuz/EasyApplyJobsBot](https://github.com/wodsuz/EasyApplyJobsBot)**, now part of the Apllie ecosystem (formerly automated-bots.com).

- Website: [apllie.com](https://www.apllie.com/)
- Chrome extension: [Apllie — Smart Application Tracker](https://chromewebstore.google.com/detail/apllie-smart-application/imiidglhhjloioihlhmnojbopkgccijc?hl=en&authuser=1)
- Support: **help@apllie.com**
- [**Donate & support the original project**](https://commerce.coinbase.com/checkout/923b8005-792f-4874-9a14-2992d0b30685)

Paid tutorials and setup support from the original author:

- [Tech support — Windows](https://commerce.coinbase.com/checkout/bfc45949-3719-4cac-8fc9-f9111b47a009) · [Linux](https://commerce.coinbase.com/checkout/c27538b8-ddee-4c68-a0eb-da43e6014043) · [macOS](https://commerce.coinbase.com/checkout/52472ffa-1653-4f56-b92b-60983e627e7c)
- [Documentation — Windows](https://commerce.coinbase.com/checkout/03546cb2-8691-4837-91ec-a86cae1cb25d) · [Linux](https://commerce.coinbase.com/checkout/b6ec4e61-cded-4845-a9b8-f87079482e7f) · [macOS](https://commerce.coinbase.com/checkout/effe4a67-895f-4862-ad77-954217d752e6)

Beware of forks using scam or phishing donation links — verify you are on www.apllie.com before paying.

The pro version (Firefox support, multi-CV selection, CSV/PDF export, additional filters) is available from [apllie.com](https://www.apllie.com/). Flags marked `PRO FEATURE!` in `config.py` do nothing in this free version.

See [LICENSE](LICENSE) for terms. The previous README is preserved in git history (`git show HEAD:README.md`).

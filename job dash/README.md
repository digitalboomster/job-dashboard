# Daily job dashboard

Static site (`index.html`) that loads [`jobs.json`](jobs.json), produced by [`scraper/scrape.py`](scraper/scrape.py) from Lever and Greenhouse sources defined in [`scraper/sources.py`](scraper/sources.py).

## Prerequisites

- Python **3.11+** (3.12 recommended)
- Network access for ATS APIs

## Run locally

From this directory (`job dash/`):

```bash
pip install -r scraper/requirements.txt
```

**Scrape only (placeholder match scores 50, no API cost):**

```bash
export SKIP_SCORING=1
python scraper/scrape.py
```

**Full run with Claude Haiku scoring:**

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
# optional: pin model (default claude-haiku-4-5)
export ANTHROPIC_MODEL="claude-haiku-4-5"
# optional: score only first N jobs (testing)
export MAX_SCORE_JOBS=5
python scraper/scrape.py
```

Keep [`cv.txt`](cv.txt) up to date; it is injected into the Claude system prompt together with the rules in [`scraper/prompts.py`](scraper/prompts.py).

If `ANTHROPIC_API_KEY` is unset, the scraper still writes `jobs.json` with placeholder scores and a short notice on stderr.

**View the dashboard:** Browsers block `fetch()` on `file://`. Serve the folder over HTTP:

```bash
python -m http.server 8000
```

Open [http://localhost:8000/](http://localhost:8000/).

## GitHub Actions

Workflow: [`.github/workflows/daily.yml`](../.github/workflows/daily.yml) (repo root is the parent of this folder).

- Runs **daily at 07:00 UTC** and on **workflow_dispatch**.
- Executes the scraper from `job dash/`, then commits **`job dash/jobs.json`** with message `Daily scrape YYYY-MM-DD` when there are changes.

### Repository secret

1. GitHub repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**
2. Name: `ANTHROPIC_API_KEY`
3. Value: your Anthropic API key

Optional: under **Variables**, add `ANTHROPIC_MODEL` (e.g. `claude-haiku-4-5-20251001`) to override the default.

### Pushing from Actions

The workflow uses `permissions: contents: write` and the default `GITHUB_TOKEN`. If **branch protection** blocks the bot, use a personal access token with `contents: write`, store it as a secret (e.g. `GH_PUSH_TOKEN`), and replace the push step with a checkout that uses that token (not covered here).

## Deploy on Vercel

1. Import the **Git repository** (root should contain both `.github/` and `job dash/`).
2. **Root Directory:** set to `job dash` (the folder that contains `index.html` and `jobs.json`).
3. Framework preset: **Other** (static). No build command. Output directory: `.` (default).
4. Each push that updates `jobs.json` on the tracked branch triggers a new deployment.

## Troubleshooting

| Issue | What to check |
|--------|----------------|
| Empty or tiny `jobs.json` | Filters in `scraper/scrape.py` (keyword + junior signals + title exclusions). Loosen carefully. |
| `fetch` fails in the browser | Serve over `http://`, not `file://`. |
| Claude errors / `Score unavailable.` | API key, model name, network; see Action logs. Partial failures keep score 50 for that row. |
| Workflow does not commit | No diff on `jobs.json`, or token/branch protection blocking push. |

## Environment reference

| Variable | Effect |
|----------|--------|
| `ANTHROPIC_API_KEY` | Enables Claude scoring when set (and `SKIP_SCORING` is not set). |
| `SKIP_SCORING` | If `1` / `true` / `yes`, skip API calls even if the key is set. |
| `ANTHROPIC_MODEL` | Model id (default `claude-haiku-4-5`). |
| `MAX_SCORE_JOBS` | If set to a positive integer, only the first N jobs are scored (cost control). |

# Agent Instructions

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> This file is mirrored across CLAUDE.md, Agents.md, and GEMINI.md so the same instructions load in any AI environment. If you edit one, edit all three identically.

This repo (`automation-EGF`) is the content-automation system for **Easy Gluten Free** (easygluten-free.com), written by "Claire's" voice. It researches topics live from reliable sources across 10 editorial lanes, generates blog posts / recipes / Pinterest pins / newsletter copy from that research, and publishes them to WordPress and Pinterest.

## The 3-Layer Architecture

LLMs are probabilistic; most business logic needs to be deterministic. This system separates the two:

**Layer 1: Directive (`directives/`)** — SOPs in Markdown. Define goals, inputs, which `execution/` scripts to call, outputs, and edge cases. Treat them like instructions for a mid-level employee.

**Layer 2: Orchestration (you)** — Intelligent routing. Read the relevant directive, call execution tools in the right order, handle errors, ask for clarification, update directives with learnings. You don't research a topic yourself — you read `directives/editorial_intelligence_pipeline.md` and run `execution/editorial/lane_discovery.py`.

**Layer 3: Execution (`execution/`)** — Deterministic Python scripts. API calls, data processing, file I/O, database interactions. Secrets live in `.env` (never in code or commits).

### Operating principles

1. **Check `execution/` before writing a script.** Only add a new script if the directive's table doesn't already list one that does the job.
2. **Self-anneal when things break**: read the error/stack trace, fix the script and re-test it (check with the user first if the fix would use paid tokens/credits), then update the directive with what you learned (API limits, timing quirks, edge cases).
3. **Directives are living documents you keep in sync with reality** — update them when you discover new constraints or flows. Don't create or overwrite a directive without asking, unless explicitly told to; they're the durable instruction set, not scratch notes.
4. **Never auto-publish.** Every content pipeline in this repo ends in a review/approval gate (dashboard approval, `pending_review` status, `SANDBOX_MODE`) before anything goes live on WordPress, Pinterest, or is treated as a verified fact. Preserve that gate when adding new pipelines.

## Commands

There is no build step, linter, or test suite configured in this repo (no `pytest`/lint config present) — validate changes by running the relevant script directly and checking logs/dashboard output.

```bash
# Setup (Windows, from project root)
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
# then create .env (see Configuration below) and place credentials.json/token.json if using Google OAuth

# Run the dashboard (Flask UI + API, primary way to review/approve/publish content)
python execution\dashboard.py
# or:
start-dashboard.bat

# Run automated lane-rotation content generation (covers N lanes, default 6; see
# directives/editorial_intelligence_pipeline.md). Schedulable via Task Scheduler/cron.
python -m execution.pipeline_runner --count 6

# Run the scheduled-publish sweep (health check + publish any due pins/blogs; optional --
# Content Studio's Publish/Post buttons publish directly and don't need this)
python -m execution.publish_runner

# Research pipeline (source-backed content briefs, see directives/editorial_intelligence_pipeline.md)
python -m execution.research.research_runner "<topic>" --lane <lane_key> --platform <blog|newsletter|pinterest|app>
python -m execution.research.draft_generator "<topic>" --lane <lane_key> --platform <platform>
python -m execution.editorial.lane_discovery <lane_key>   # grounded idea generation for one lane, no topic needed
python -m execution.research.priority_source_importer path/to/priority_sources.md --approved-by user

# Diagnostics / maintenance (tools/)
python -m tools.db_status               # dump recent pins/blogs/schedule status
python -m tools.verify_credentials      # check all configured API keys/connections
python -m tools.reset_failed_schedules  # reset failed publish_schedule rows to pending and re-run
python -m execution.utils.pinterest_oauth  # one-time interactive Pinterest OAuth setup

# Docker (alternative to venv; drops into a shell, run scripts manually inside)
docker-compose up -d
docker-compose exec automation bash
```

## Configuration

All secrets/config come from a `.env` file at the project root (gitignored, no template committed — see `execution/config.py` for the full list of keys it reads). Key ones:

- `OPENAI_API_KEY`, `OPENAI_IMAGE_API_KEY`, `GOOGLE_API_KEY` — LLM/image generation (`IMAGE_GENERATION_PROVIDER=openai|gemini` selects which image API is used)
- `BRAVE_SEARCH_API_KEY` — Brave Web Search API, used by the `web_search` research collector for live source discovery outside the lanes with fixed official APIs. Without it the collector no-ops with a `status=failed` record rather than crashing. (Google Custom Search JSON API was the original choice but is closed to new customers as of 2026, and Google Programmable Search no longer offers whole-web search to new engines — capped to a fixed domain list instead — so Brave is used here.)
- `WP_BASE_URL`, `WP_USERNAME`, `WP_APP_PASSWORD` — WordPress REST API (Application Password, not the login password)
- `PINTEREST_ACCESS_TOKEN`, `PINTEREST_BOARD_ID` — Pinterest API v5 (OAuth2; see `execution/utils/pinterest_oauth.py` / `execution/utils/token_manager.py` for refresh handling)
- `AMAZON_ASSOCIATE_TAG` — appended to direct Amazon product links in blog posts
- `SANDBOX_MODE` — **defaults to `True`**. Must be explicitly set `SANDBOX_MODE=False` for real WordPress/Pinterest posts to go out. If content isn't actually publishing, check this first.
- `DB_PATH` — SQLite file path, defaults to `execution/data/egf.db`
- `LANE_ROTATION_COUNT` — number of editorial lanes the automated rotation covers per run, defaults to `6`

`credentials.json` / `token.json` (Google OAuth) are also required, gitignored files expected at the project root.

## Architecture

### Data layer: three schemas share one SQLite file

`DB_PATH` (`execution/data/egf.db`) is accessed through **three separate, uncoordinated code paths** — know which one owns which tables before touching data:

- `execution/db.py` — raw `sqlite3`, `init_db()` creates the core content-pipeline tables (`recipes`, `content_ideas`, `generated_pins`, `posted_pins`, `blogs`, `publish_schedule`, `amazon_products`, `generated_recipes`, ...). Most `execution/content/*` scripts use `get_connection()` from here.
- `execution/database.py` — SQLAlchemy models (`GeneratedPin`, `Blog`, ...) mirroring a subset of the same tables. `DATABASE_URL` env var can point this at Postgres later; today it points at the same SQLite file as `db.py`.
- `execution/research/schema.py` (+ `execution/editorial/schema.py`) — the newer research/editorial layer's own `CREATE TABLE` statements (`source_registry`, `source_notifications`, `research_queries`, `research_sources`, `research_facts`, `content_briefs`, `content_drafts`).

When adding a table or column, add it in the schema file that already owns that table's domain rather than introducing a fourth pattern.

### Content pipeline: one research-driven engine, two ways to trigger it

`directives/editorial_intelligence_pipeline.md` governs the whole thing. There used to be a second, Reddit/PubMed-trend-scrape-based pipeline plus a separate broad (non-lane-scoped) idea pipeline; both were retired 2026-08-29 because they produced content from a title + short caption with no real source text behind it. Everything now goes through research first:

```
Topic discovery (grounded, not brainstormed):
  execution/editorial/lane_discovery.py -> runs research collectors across a lane's source
    mix (execution/research/planner.py's LANE_SOURCE_TYPES) -> LLM turns real discovered
    signals into content_ideas, each tied to the source URL(s) it's based on

Content generation (per idea, any platform):
  execution/research/research_runner.py -> plans + dispatches collectors -> gates new
    sources through source_registry approval -> execution/research/platform_packager.py
    reshapes the resulting brief per platform
  -> blog:  execution/research/blog_draft_generator.py (source-cited, fills locked
            Blog-Template.md, saves to `blogs`)
  -> pinterest/newsletter/app: execution/research/draft_generator.py (saves to
            `content_drafts`, status=pending_review)
```

Two ways to trigger generation, both hitting the same machinery above:
- **Automated lane rotation** — `execution/pipeline_runner.py::run_lane_rotation()`, picks the least-recently-covered lanes and generates a full blog+pin+newsletter bundle per lane. Schedulable via Task Scheduler/cron; also triggerable from the dashboard's Content Studio tab ("Run Lane Rotation").
- **Manual** — Content Studio's per-lane "Generate Lane Ideas" (same discovery-grounded flow, scoped to one lane) or Editorial Lab's direct topic-entry draft generator.

Every topic gets tagged with a `content_lane` (10 lanes — laws_labeling, product_watch, comparison, restaurants_travel, gadgets_tools, apps_digital, organization_life, recipe_experiments, science_health, community_questions) and an `angle_type` format, scored across freshness/novelty/usefulness/lane-diversity/SEO/brand-fit (`execution/editorial/scoring.py`). New sources discovered by collectors (including the `web_search` collector — Google Programmable Search) are inserted as `approval_status='pending_approval', enabled=FALSE` and require dashboard/API approval before they can back auto-generated content — only user-supplied priority-source lists (`priority_source_importer.py`) skip the gate. The pipeline is platform-neutral by design: research/briefs produce facts once, then `platform_packager.py` / `editorial/platforms.py` reshape a brief per output (blog/newsletter/Pinterest/app) — don't bake blog-specific assumptions into the research code.

Recipes follow a separate, parallel path (`execution/content/recipe_generator.py` -> `recipe_wp_publisher.py`) and **must** publish through WP Recipe Maker routes, never through the generic blog publish path — recipe posts intentionally land on `/product/` URLs (WooCommerce/WPRM behavior, not a bug).

Everything converges on the same dashboard (`execution/dashboard.py`, a single ~3000-line Flask app serving both the API and the inline HTML/JS UI) for human review/approval before anything publishes. Automation produces drafts; nothing publishes on its own.

### Cross-cutting utilities (`execution/utils/`)

- `llm_client.py` — shared OpenAI/Gemini call wrapper
- `cost_tracker.py` — token/cost logging for LLM calls
- `logger.py` — `setup_logger(name)` used by every script, writes to `execution/execution/logs/pipeline_<date>.log`
- `token_manager.py` — Pinterest OAuth token refresh (rotating refresh tokens; both `access_token` and `refresh_token` get rewritten to `.env` on each use)

### Prompts (`execution/prompts/`)

Plain-text prompt templates (`blog_generation.txt`, `recipe_generation.txt`, `lane_discovery_generation.txt`, `platform_draft_generation.txt`, `brand_system_prompt.txt`, ...) loaded by the corresponding generator script. `blog_generation.txt` and `platform_draft_generation.txt` both require claims to come from the collected sources passed into the prompt — don't relax that when editing them. `Blog-Template.md` is the **locked** HTML template blog posts are filled into — don't rename its CSS classes or add/remove sections without updating `wordpress_publisher.py` accordingly.

## Known constraints (learned the hard way — see directive "Learnings" tables for the full, dated log)

- Pinterest API v5 requires a publicly reachable image URL for pin creation — pin images are uploaded to WP Media Library first, then that URL is used.
- Pinterest **Trial Access** (API error code 29) can read boards/pins but cannot create them; **Standard Access** must be requested from the Pinterest developer dashboard before pin posting works.
- WordPress Application Passwords (not the account login password) are required for REST API auth over HTTPS.
- PubMed E-utilities: don't call more than 3 requests/second; `execution/research/collectors/pubmed_collector.py` already sleeps between detail fetches.
- The `web_search` collector (Google Programmable Search) still routes every result through the normal source-approval gate — a first-time domain won't back auto-generated content until approved in the dashboard, even though the collector assigns it a credibility score. Don't bypass `is_source_approved`/`propose_source` to "fix" thin research results.
- If a WP/Pinterest publish step fails partway, don't blindly retry the whole chain — check `publish_schedule.status` and whether the blog already went live before re-running (see `directives/generate_and_publish_blog.md` § Error Handling).

# Directive: Editorial Intelligence Pipeline

## Purpose

This directive governs the **sole** topic discovery and content-generation engine for Easy Gluten Free.
It replaced the old Reddit/PubMed trend-scrape pipeline (`reddit_scraper.py`, `medical_articles_scraper.py`,
`trend_analyzer.py`, `trend_synthesizer.py`, the `trend_topics`/`trendy_topics` tables, and the dashboard's
old "Trends & Blog Gen" / "Pending Review" / "Publish Queue" tabs) and the old broad, non-lane-scoped idea
pipeline (`idea_generator.py`, `idea_scorer.py`, `pin_assembler.py`) — both retired 2026-08-29 because they
produced blog posts from a title and a 160-character caption with no real source text behind them, despite
claiming to be "sourced from Reddit and the GF community."

The goal is to produce blog/pin/newsletter ideas and content that are:

- timely
- specific
- useful
- conversational
- funny in Claire's voice
- varied across editorial lanes
- grounded in sources that can be verified before publishing, discovered live rather than pre-written

This directive supersedes `generate_and_publish_blog.md`'s blog-generation section — publishing mechanics
(WordPress/Pinterest API calls) documented there still apply; how the blog/pin content itself gets written
does not.

The same topic intelligence should feed multiple platforms:

- blog posts
- newsletter issues or newsletter sections
- Pinterest pins
- future app cards, recommendations, and searchable topic pages

---

## Core Principle

Do not generate a blog directly from raw scraped text.

First create a strong editorial brief:

1. What lane is this topic in?
2. Why is it fresh or worth covering now?
3. What source should verify it?
4. What format should the blog use?
5. Why would a real gluten-free reader care?
6. How is this different from recent EGF content?

Only then generate the blog.

The reusable unit is the `content_brief`, not the blog draft. A content brief can be repackaged for any platform.

---

## Editorial Lanes

Every topic or idea should be assigned one lane:

| Lane key | Use for |
|---|---|
| `laws_labeling` | FDA rules, packaging claims, certification, recalls, allergen labeling |
| `product_watch` | New or popular grocery products, snacks, frozen meals, flour blends |
| `comparison` | Side-by-side products, breads, pastas, apps, restaurants, or tools |
| `restaurants_travel` | Restaurant chatter, allergen menus, travel, airports, hotels |
| `gadgets_tools` | Air fryers, toaster bags, lunch boxes, storage, cross-contact tools |
| `apps_digital` | Scanner apps, restaurant finder apps, meal planning tools |
| `organization_life` | Pantry systems, shared kitchens, school lunches, freezer prep |
| `recipe_experiments` | Specific new recipes, copycats, seasonal ideas, practical experiments |
| `science_health` | Research, oats, cross-contact, celiac studies, evidence-led explainers |
| `community_questions` | Reddit dilemmas, etiquette, family issues, recurring frustrations |

Avoid letting `recipe_experiments`, bread, baking basics, or beginner guides dominate.

---

## Blog Formats

Choose one format before writing:

- `comparison`
- `explainer`
- `product_roundup`
- `field_guide`
- `review_test`
- `trend_reaction`
- `recipe_story`
- `checklist`

Examples:

- "Which Gluten-Free Bread Actually Survives a Sandwich?"
- "What the New Gluten-Free Labeling Rules Mean at the Grocery Store"
- "I Tried 3 Gluten-Free Scanner Apps. Here Is What Was Actually Useful."
- "The Shared Kitchen Setup That Prevents Crumb-Based Betrayal"

---

## Scoring

Topic selection should weigh:

- freshness
- novelty versus recent EGF titles
- usefulness
- entertainment/conversation value
- lane diversity
- SEO value
- brand fit

The current implementation stores these signals through:

- `execution/editorial/taxonomy.py`
- `execution/editorial/memory.py`
- `execution/editorial/scoring.py`
- `execution/editorial/schema.py`
- `execution/editorial/platforms.py`
- `execution/research/source_registry.py`
- `execution/research/planner.py`
- `execution/research/brief_builder.py`

---

## Current Implementation

### Discovery-grounded idea generation

`execution/editorial/lane_discovery.py::discover_lane_topics(lane_key, ...)` is the only idea-generation path.
Unlike the retired `idea_generator.py`, it does not brainstorm from the lane taxonomy alone: it first runs
real research collectors across the lane's normal source mix (`discover_lane_signals`, reusing the same
collector dispatch as single-topic research) to gather current raw signals — recalls, product/brand pages,
restaurant/app pages, science papers, or live web search results — then asks the LLM to turn those specific
signals into ideas via `execution/prompts/lane_discovery_generation.txt`. Each idea asks for:

- `content_lane`
- `angle_type`
- `freshness_hook`
- `source_hint`
- `grounded_source_urls` — the real discovered URL(s) the idea is actually based on; empty only when no live
  signals were collected, in which case the idea must say so plainly rather than inventing a source

These fields are saved to `content_ideas`.

### Scoring

`execution/editorial/scoring.py::EditorialScorer` boosts:

- freshness
- novelty
- usefulness
- entertainment value
- lane diversity

`execution/pipeline_runner.py::run_lane_rotation` (see "Automated Lane Rotation" below) uses this scorer to
pick the top idea per lane it covers.

---

## Writing Rules

A blog should feel like a smart gluten-free friend did the homework.

Use this structure:

1. Specific hook: scene, funny frustration, or sharp question.
2. Real-world problem: why this matters to gluten-free people.
3. Useful answer: practical checks, steps, comparisons, or decisions.
4. Claire's take: opinionated but fair.
5. What to do next: clear action plan.

Avoid:

- generic beginner intros
- "ultimate guide"
- "game changer"
- broad wellness-brochure language
- repeating bread/flour/baking topics without a new angle
- unsourced medical or legal claims

---

## Source Expectations

Before publishing topics in sensitive lanes:

- Laws/labeling: verify with FDA, USDA, certification bodies, or official recall pages.
- Science/health: verify with PubMed or recognized celiac organizations.
- Restaurants: verify with official allergen menus where possible.
- Products: verify with brand/product pages and current retailer listings.
- Apps: verify with app store listings, official sites, and review patterns.

If a source cannot be verified, mark the idea for review rather than publishing confidently.

---

## Modular Research Architecture

Research happens between topic discovery and writing:

```text
Topic Candidate
  -> Research Planner
  -> Source Registry
  -> Source Collectors
  -> Source Ranker
  -> Fact Extractor
  -> Content Brief
  -> Platform Packager
```

Current foundation:

| Module | Purpose |
|---|---|
| `execution/research/source_registry.py` | Defines fixed and dynamic sources by lane |
| `execution/research/planner.py` | Creates deterministic research tasks for a topic |
| `execution/research/brief_builder.py` | Builds reusable briefs for blog/newsletter/Pinterest/app |
| `execution/research/research_runner.py` | Runs implemented collectors and persists source-backed briefs |
| `execution/research/platform_packager.py` | Converts a research brief into blog/newsletter/Pinterest/app sections |
| `execution/research/collectors/openfda_food_collector.py` | Collects structured openFDA food enforcement records |
| `execution/research/collectors/official_page_collectors.py` | Collects conservative FDA/USDA official recall page links |
| `execution/research/collectors/approved_source_page_collector.py` | Collects approved priority brand, retailer, restaurant, tool, and app pages |
| `execution/editorial/platforms.py` | Defines platform-specific required sections |

The LLM may suggest sources, websites, accounts, or search directions, but deterministic code should decide:

- whether the source type is allowed
- whether the source is authoritative enough
- whether it needs verification from a stronger source
- which claims may be used in published content

Community/social sources are useful for language, pain points, and trend discovery. They are not enough for factual claims about laws, recalls, medical issues, allergen safety, or product ingredients.

---

## Research Tables

The research layer persists reusable data in:

| Table | Purpose |
|---|---|
| `source_registry` | Known monitored sources and dynamic source categories |
| `research_queries` | Planned searches/API checks for a topic |
| `research_sources` | URLs or source records found/fetched for a topic |
| `research_facts` | Extracted claims with evidence and confidence |
| `content_briefs` | Portable editorial briefs for any output platform |
| `source_notifications` | Review notifications when new sources need approval |
| `knowledge_entities` | Normalized brands, products, restaurants, apps, laws, studies, and community themes |
| `knowledge_entries` | Quality-gated reusable facts, sentiments, product mentions, warnings, tips, and recurring questions |
| `knowledge_evidence` | Evidence snippets and source URLs supporting knowledge entries |
| `knowledge_usage` | Records which generated assets reused a knowledge entry |

---

## Knowledge Database

The Knowledge DB is the reusable memory layer for the intelligence engine. It copies and normalizes accumulated data from research tables, drafts, and trend tables without deleting the original records.

Use the ingestion service to populate or refresh it:

```bash
python -c "from execution.knowledge.service import ingest_current_intelligence; print(ingest_current_intelligence())"
```

Knowledge entries do not require manual approval before reuse when deterministic quality checks pass. Auto-reuse requires:

- an intelligence-engine origin
- evidence or structured source data
- enough confidence/credibility for the lane
- non-stale and non-blocked status

Sensitive lanes such as labeling, recalls, medical/science, allergen safety, and restaurant procedures use stricter source checks. Community data may be reused as `community_sentiment` or `recurring_question` for tone, pain points, and framing; it must not be treated as verified factual evidence.

Dashboard/API endpoints:

```text
GET  /api/knowledge/stats
GET  /api/knowledge/entries
GET  /api/knowledge/entries/<entry_id>
POST /api/knowledge/ingest
POST /api/knowledge/entries/<entry_id>/block
POST /api/knowledge/entries/<entry_id>/restore
POST /api/knowledge/entries/<entry_id>/mark-stale
```

Generation code should retrieve reusable entries with:

```python
retrieve_reusable_knowledge(topic_title, lane, limit=10)
```

Whenever generated content uses KB context, log the relationship in `knowledge_usage`.

---

## Platform Packaging

Supported platform targets are defined in `execution/editorial/platforms.py`.

Each platform consumes the same research brief differently:

| Platform | Output style |
|---|---|
| Blog | Long-form SEO article with sourced context and Claire's take |
| Newsletter | Shorter personal note, quick hits, and one clear action |
| Pinterest | Pin title, description, and visual concept |
| Future App | Structured card with summary, tags, source confidence, and action items |

Do not hard-code blog assumptions inside research code. Research should produce platform-neutral facts and briefs.

---

## Running Source Research

Use the research runner to create a brief and fetch implemented official sources:

```bash
python -m execution.research.research_runner "undeclared wheat recalls" --lane laws_labeling --platform newsletter
```

Current implemented collectors:

- `official_api`: openFDA food enforcement API
- `official_recall_page`: FDA recalls page and USDA FSIS recalls page
- `certification_body`: GFCO site search
- `gluten_free_organization`: Celiac Disease Foundation and Beyond Celiac site search
- `medical_research`: PubMed E-utilities search/fetch
- `brand_product_page`: approved brand/product pages
- `retailer_product_page`: approved retailer/store pages
- `restaurant_allergen_page`: approved restaurant/travel allergen pages
- `tool_product_page`: approved kitchen tool/product pages
- `app_review_page`: approved app/digital tool pages
- `trend_planning_tool`: approved trend-planning tools
- `web_search`: live discovery via the Brave Web Search API (`BraveSearchCollector`,
  `execution/research/collectors/web_search_collector.py`). This is what lets product_watch, comparison,
  restaurants_travel, gadgets_tools, apps_digital, organization_life, recipe_experiments, and
  community_questions find brand-new pages instead of depending entirely on a manually pre-approved priority
  list. Requires `BRAVE_SEARCH_API_KEY` in `.env`; without it the collector returns a single `status=failed`
  record explaining what to configure, so the rest of the pipeline degrades gracefully rather than crashing.
  Every result still passes through the normal `is_source_approved` / `propose_source` gate — a first-time
  domain still requires human approval in the dashboard before its facts are trusted, regardless of the
  domain-tier credibility heuristic the collector assigns it.
  **Why Brave, not Google**: Google Custom Search JSON API is closed to new customers as of 2026, and
  Google Programmable Search no longer offers whole-web search to newly created engines (capped to a fixed
  list of domains specified at creation) — see the 2026-08-29 Learnings entry below. Brave's Web Search API
  still does true open web search with no domain list required. It no longer has a fully free tier either
  (as of Feb 2026): sign-up requires a card on file, ~$5/month in credits (roughly 1,000 queries), then
  billed per query — comfortably covers this project's low volume (a handful of lane-rotation runs/week).
  Requests are biased by `LANE_FRESHNESS` (a per-lane recency window passed as Brave's `freshness` param —
  `pw`/`pm`/`py`, or unfiltered for evergreen lanes) and by problem/advice-leaning query phrasing
  (`planner._web_search_query`) rather than generic "review" language, so results skew toward what's current
  and toward complaints/advice rather than marketing copy.
- `community_discussion`: also `BraveSearchCollector`, same class, different query — scoped with
  `site:reddit.com` plus a hard `("gluten free" OR "gluten-free" OR celiac)` requirement (tested: without
  that requirement, a loosely-matched query returned a completely unrelated sports thread). Reddit's own API
  was the original plan for this but is not viable: unauthenticated `.json` access was blocked in May 2026
  and OAuth is now restricted to approved applications only. Brave still works because it's one of the few
  engines Reddit hasn't blocked from crawling — it runs its own independent index rather than relicensing
  another engine's, unlike Bing/DuckDuckGo which now return near-empty Reddit results. Credibility is capped
  at 0.45 regardless of domain (`CREDIBILITY_COMMUNITY`) — excellent for pain points and language, never a
  sole factual source, same rule the lane's own `community_discussion` source-registry entry has always
  stated. Wired into every lane except `laws_labeling` and `science_health`, where facts should stay
  official-source-led.

Collectors save normalized records into `research_sources`.
When a fetched source has a usable snippet, the runner creates a conservative `research_facts` entry using the source title and snippet as evidence.
The runner also returns a `platform_package` with sections tailored to the requested platform.

---

## Draft Generation

Research-backed drafts are generated after the source package exists:

```bash
python -m execution.research.draft_generator "new gluten-free bread products" --lane product_watch --platform newsletter
```

Draft generation:

1. Runs the research runner.
2. Builds a platform package.
3. Calls the LLM using `execution/prompts/platform_draft_generation.txt`.
4. Saves the result to `content_drafts`.
5. Marks the draft as `pending_review`.

Drafts must not publish or schedule automatically.

Review endpoints:

```text
GET  /api/content-drafts
GET  /api/content-drafts?status=pending_review
POST /api/content-drafts/generate
POST /api/content-drafts/<draft_id>/approve
POST /api/content-drafts/<draft_id>/reject
```

The `content_drafts` table stores:

- platform
- lane
- angle type
- title
- dek
- structured content JSON
- source URLs
- status
- approval metadata

Future collectors should implement the `SourceCollector` protocol in `execution/research/collectors/base.py` and return `CollectedSource` objects.

---

## Lane-Level Idea and Content Endpoints

The dashboard exposes lane-scoped API endpoints so automations can create ideas or reviewable content for any editorial lane without hard-coding lane logic in the frontend.

```text
GET  /api/editorial/lanes
GET  /api/editorial/lanes/<lane>/ideas?limit=20
POST /api/editorial/lanes/<lane>/ideas
POST /api/editorial/lanes/<lane>/content
GET  /api/editorial/assets
POST /api/editorial/ideas/<idea_id>/assets
POST /api/blogs/<blog_id>/publish/wp
POST /api/pins/<pin_id>/post/pinterest
GET  /api/pins/<pin_id>/copy
GET  /api/newsletters/<draft_id>/copy
```

Implementation:

- `execution/editorial/lane_content_service.py`
- `execution/editorial/content_asset_service.py`
- `execution/prompts/lane_idea_generation.txt`

`POST /api/editorial/lanes/<lane>/ideas` accepts:

- `idea_count`: number of ideas to create, capped by the service
- `topic_hint`: optional narrowing angle
- `sample`: if true, creates deterministic no-token ideas
- `persist`: if true, saves ideas to `content_ideas`

Content Studio should expose `idea_count` as an explicit user choice, including a one-idea option for focused ideation while preserving the three-idea batch option.

`POST /api/editorial/lanes/<lane>/content` accepts:

- `topic_title`: topic to turn into content
- `platform`: `blog`, `newsletter`, `pinterest`, or `app`
- `angle_type`: optional editorial format
- `topic_hint`: fallback hint if no title is supplied
- `limit_per_task`: research collector limit
- `sample`: if true, creates deterministic no-token sample content
- `persist`: if true, saves generated drafts to `content_drafts`

Sample mode is for UI and contract testing only. Non-sample content creation may call OpenAI and source collectors, so it should remain review-gated and never publish or schedule automatically.

`POST /api/editorial/ideas/<idea_id>/assets` turns an approved or recent idea into selected reviewable assets:

- `pin`: creates/updates a `generated_pins` row with title, description, keywords, and image
- `blog`: creates a `blogs` row linked to the pin
- `newsletter`: creates a text-only `content_drafts` row with `platform = 'newsletter'`

Reviewable Content Studio assets must be complete reader-facing deliverables, not outlines, prompts, placeholders, or sample records. Sample asset generation may be used only for non-persisted testing; persisted `pin`, `blog`, and `newsletter` records must be final drafts ready for human review.

Generated assets are intentionally separated in the dashboard:

- Website content is published through `POST /api/blogs/<blog_id>/publish/wp`.
- Pinterest content is posted through `POST /api/pins/<pin_id>/post/pinterest` after the website/blog has a destination URL.
- Newsletter text is copied from `GET /api/newsletters/<draft_id>/copy`.

Recipe publishing remains separate. Generated recipes must publish to WordPress through WP Recipe Maker routes only, not through the normal blog asset pipeline.

---

## Source Approval Gate

Known system-seeded sources are approved by default.

Any newly discovered source should be inserted into `source_registry` with:

- `approval_status = 'pending_approval'`
- `enabled = FALSE`
- `added_by = 'research_runner'` or the collector name

The system then creates a `source_notifications` row with:

- `notification_type = 'source_approval_required'`
- `status = 'unread'`

Only approved and enabled sources may be used automatically for content generation and scheduling.

Dashboard/API review endpoints:

```text
GET  /api/sources
GET  /api/sources?status=pending_approval
GET  /api/source-notifications
POST /api/sources/<source_id>/approve
POST /api/sources/<source_id>/reject
```

Recommended operating rule:

- Approved source + generated draft: allowed.
- Pending source: collect for review only.
- Rejected source: never use automatically.

---

## Priority Source Lists

User-curated priority sources can be imported from Markdown tables with:

```bash
python -m execution.research.priority_source_importer path/to/priority_sources.md --approved-by user
```

The importer expects sections such as:

- `Product Watch`
- `Bread Wars and Comparisons`
- `Restaurant and Travel Buzz`
- `Kitchen Gadget Lab`
- `Apps and Digital Tools`
- `Organization and Real Life Systems`
- `Recipe Experiments`

Imported user-priority sources are marked:

- `approval_status = 'approved'`
- `enabled = TRUE`
- `priority_tier = 'priority'`
- `added_by = 'user_priority_list'`

This is intentional: a source list explicitly supplied by the user is treated as trusted. Future discovered sources still go through the notification and approval gate.

---

## Research-Backed Blog Generation

Blog generation is source-cited, the same way newsletter/pinterest/app drafts already are.
`execution/research/blog_draft_generator.py`:

- `generate_blog_content(topic_title, ...)` runs `run_research(..., platform="blog")` for a real brief +
  collected sources, picks the Amazon product, and calls the LLM with `execution/prompts/blog_generation.txt`
  (rewritten to require facts to come from the collected sources, mirroring `platform_draft_generation.txt`'s
  discipline) — returns content, the chosen product, and the filled locked `Blog-Template.md` HTML.
- `generate_research_backed_blog(pin_id, ...)` wraps the above for a real pin and saves the result into the
  `blogs` table — the drop-in replacement for the old, ungrounded `execution.content.blog_generator.generate_blog()`.

`BlogGenerationResponse` (`execution/models.py`) carries `source_notes`, `verification_notes`, and
`status_recommendation` (`ready_for_review` / `needs_more_sources` / `do_not_publish_yet`) so a reviewer sees
a sourcing-confidence flag in the dashboard before clicking Publish — the same signal the research pipeline
already surfaces for newsletter/pinterest drafts.

`execution/content/blog_generator.py` still exists but only for its reusable utilities (`get_relevant_product`,
`mark_product_used`, `load_html_template`, `fill_template`) — it no longer has a standalone generation entrypoint.

---

## Automated Lane Rotation

`execution/pipeline_runner.py::run_lane_rotation(count)` is the automated content-generation mode (the manual
Content Studio / Editorial Lab paths above stay available alongside it, not replaced by it):

```text
pick `count` lanes, favoring the least-recently-covered (execution.editorial.memory)
  -> for each lane: lane_discovery.discover_lane_topics(lane_key)
  -> score the resulting ideas with EditorialScorer, take the top one per lane
  -> content_asset_service.create_assets_from_idea(idea_id, assets=["blog","pin","newsletter"])
  -> everything lands in the normal review queues (pending_review / generated)
```

Run it directly:

```bash
python -m execution.pipeline_runner --count 6
```

It's a plain script — schedule it with Windows Task Scheduler (or cron) for unattended, hands-off operation.
It can also be triggered from the dashboard's Content Studio tab ("Run Lane Rotation" button, backed by
`POST /api/editorial/rotation/run` + `GET /api/editorial/rotation/status`, same background-thread/poll
pattern the old Trends scrape button used).

Nothing in this pipeline publishes automatically — content lands as `pending_review`/`generated` rows and is
reviewed and published manually from Content Studio, exactly like manually-generated content.

---

## Learnings / Updates Log

| Date | Learning |
|---|---|
| 2026-08-29 | Retired the Reddit/PubMed trend-scrape pipeline (`reddit_scraper.py`, `medical_articles_scraper.py`, `trend_analyzer.py`, `trend_synthesizer.py`, `trend_topics`/`trendy_topics` tables) and the old broad idea pipeline (`idea_generator.py`, `idea_scorer.py`, `pin_assembler.py`) — both produced content from a title/caption with no real source text behind it, despite claiming otherwise. Replaced by `lane_discovery.py` (research-grounded idea generation) and `pipeline_runner.py::run_lane_rotation` (automated lane rotation), both feeding the same `content_asset_service`/dashboard review flow manual generation already used. |
| 2026-08-29 | Added a `web_search` collector (Google Programmable Search) so lanes without a fixed official API/page (product_watch, comparison, restaurants_travel, gadgets_tools, apps_digital, organization_life, recipe_experiments, community_questions) can discover new sources live instead of depending entirely on a manually pre-curated priority list. Still gated by the existing source-approval flow. |
| 2026-08-29 | Blog generation is now research-backed (`execution/research/blog_draft_generator.py`), closing the gap where blog text was written from a title + 160-character Pinterest caption with no source grounding, unlike the newsletter/pinterest paths. |
| 2026-08-29 | Google was the original choice for the `web_search` collector but turned out to be a dead end: Google's Custom Search JSON API is closed to new customers (Google's own docs: "not available for new customers"), and Google Programmable Search Engine no longer offers whole-web search to newly created engines at all — new engines are capped to a fixed list of domains specified at creation (no more "search the entire web" toggle). Switched to the Brave Web Search API instead, which still does true open web search. Also note: Brave dropped its fully-free, no-card tier in Feb 2026 — it now requires a card on file, ~$5/month credit (~1,000 queries), then billed per query. |
| 2026-08-29 | Added freshness biasing (Brave's `freshness` param, per-lane) and problem/advice-leaning query phrasing to the `web_search` collector, and brought `community_discussion` back to life via a `site:reddit.com`-scoped Brave query (capped credibility) since a dedicated Reddit API collector is not viable — Reddit blocked unauthenticated `.json` access in May 2026 and restricted OAuth to approved apps only, but Brave is one of the few engines Reddit still lets crawl it. First test of the untightened Reddit query returned one completely unrelated result (a sports thread); added a hard `("gluten free" OR "gluten-free" OR celiac)` requirement to the query and confirmed the fix on a re-run. |
| 2026-08-29 | `requirements.txt` was missing `SQLAlchemy` despite `execution/database.py` requiring it — a fresh `pip install -r requirements.txt` would fail on first dashboard import. Fixed. |

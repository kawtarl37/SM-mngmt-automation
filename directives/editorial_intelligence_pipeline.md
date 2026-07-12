# Directive: Editorial Intelligence Pipeline

## Purpose

This directive governs the upgraded topic and blog ideation system for Easy Gluten Free.
The goal is to stop repetitive generic topics and produce blog ideas that are:

- timely
- specific
- useful
- conversational
- funny in Claire's voice
- varied across editorial lanes
- grounded in sources that can be verified before publishing

This pipeline complements `scrape_and_synthesize_trends.md` and `generate_and_publish_blog.md`.

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

### Generation inputs

`execution/intelligence/idea_generator.py` now sends the LLM:

- current editorial month
- recent trend context
- existing recipe titles
- recent generated/published topic memory
- the editorial lane taxonomy

### Trend synthesis

`execution/intelligence/trend_synthesizer.py` now asks for:

- `content_lane`
- `angle_type`
- `freshness_hook`

These fields are saved to `trendy_topics`.

### Idea generation

`execution/intelligence/idea_generator.py` now asks for:

- `content_lane`
- `angle_type`
- `freshness_hook`
- `source_hint`

These fields are saved to `content_ideas`.

### Scoring

`execution/intelligence/idea_scorer.py` now boosts:

- freshness
- novelty
- usefulness
- entertainment value
- lane diversity

It also selects diverse top ideas where possible.

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

Collectors save normalized records into `research_sources`.
When a fetched source has a usable snippet, the runner creates a conservative `research_facts` entry using the source title and snippet as evidence.
The runner also returns a `platform_package` with sections tailored to the requested platform.

Future collectors should implement the `SourceCollector` protocol in `execution/research/collectors/base.py` and return `CollectedSource` objects.

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

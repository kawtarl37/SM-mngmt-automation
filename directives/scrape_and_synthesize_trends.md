# Directive: Scrape and Synthesize Trends for Content Ideas

## Purpose
This directive governs the automated pipeline that:
1. Scrapes raw gluten-free community discussions (from Reddit) and scientific publications (from PubMed).
2. Scores and ranks raw topics by their relevance to the Easy Gluten Free brand.
3. Synthesizes these raw inputs into high-level, human-readable "Trendy Topics" using AI.
4. Presents these trends to the user on the dashboard for approval and direct blog generation.

---

## The Pipeline Flow

```
[Trigger Scrape & Synthesize]
              ↓
  [reddit_scraper.py] & [medical_articles_scraper.py]
    → Collect top daily posts from r/glutenfree, r/celiac, etc.
    → Collect top 10 celiac & gluten-free medical papers from PubMed
              ↓
      [trend_analyzer.py]
    → Score all newly fetched raw topics based on keyword density, 
      social engagement, recency, and source credibility
              ↓
     [trend_synthesizer.py]
    → Read top raw trends
    → Use GPT-4o-mini to group inputs into 5–8 coherent topics
    → Write details for each topic in Claire's brand voice
    → Save to the trendy_topics table (status: pending)
              ↓
  [Dashboard: Trends Tab]
    → User reviews "Discovered Trends"
    → User approves topics of interest, moving them to "Approved Topics"
    → User clicks "Generate Blog & Pin" on an approved topic
              ↓
 [Auto-Approve, Image Gen & Schedule]
    → Generate a Pinterest Pin (title, description, keywords, alt)
    → Generate vertical 9:16 layout cover image using the configured image provider
    → Generate WordPress blog post based on the topic details
    → Schedule pin and blog post to the next available queue slot
```

---

## Scripts & Tools

| Script | Location | Purpose |
|---|---|---|
| Reddit Scraper | `execution/scrapers/reddit_scraper.py` | Crawl top daily Reddit posts from GF subreddits |
| PubMed Scraper | `execution/scrapers/medical_articles_scraper.py` | Query PubMed E-utilities API for scientific articles |
| Trend Scorer | `execution/intelligence/trend_analyzer.py` | Compute relevance score for raw trends |
| Trend Synthesizer | `execution/intelligence/trend_synthesizer.py` | Group raw trends and output cohesive topics via LLM |
| Dashboard API & UI | `execution/dashboard.py` | Backend routes + HTML/CSS/JS frontend for review & generation |

---

## Operation & Maintenance

### Running Scrape & Synthesize via CLI
You can run the entire sequence sequentially from the project root:
```bash
# 1. Scrape Reddit
python -m execution.scrapers.reddit_scraper

# 2. Scrape PubMed
python -m execution.scrapers.medical_articles_scraper

# 3. Score Raw Trends
python -m execution.intelligence.trend_analyzer

# 4. Synthesize Cohesive Topics
python -m execution.intelligence.trend_synthesizer
```

### Database Tables
1. `trend_topics`: Stores raw scraped Reddit posts and PubMed article abstracts.
2. `trendy_topics`: Stores synthesized AI-learned trends with titles, details, sources, and status (`pending`, `approved`, `rejected`, `generated`).

### Blog & Pin Generation Details
When a user clicks "Generate Blog & Pin" on an approved topic:
- The system generates a corresponding `GeneratedPin` record in `status = 'approved'` (to bypass manual pin review).
- The approved `trendy_topics.title` is the locked blog title. Do not let blog generation silently rewrite it. Use the dashboard "Suggest Another Title" button before generation if a different title is desired.
- The configured image provider is invoked to generate the cover image. Use `IMAGE_GENERATION_PROVIDER=openai` for OpenAI GPT Image 2 or `IMAGE_GENERATION_PROVIDER=gemini` to switch back to Gemini/Imagen.
- `blog_generator.py` is invoked to write a complete blog using the HTML template and next rotated Amazon product.
- `publish_scheduler.py` is called to slot the pin + blog package into the next available slot on the calendar (8 AM, 12 PM, or 4 PM EST).
- The trend's status in `trendy_topics` updates to `'generated'`.

---

## Learnings & Troubleshooting
- **No Raw Trends Found**: If `trend_synthesizer.py` logs that no raw trends are found, verify that the Reddit and PubMed scrapers completed successfully and populated the `trend_topics` table.
- **PubMed Rate Limits**: Do not call `medical_articles_scraper.py` more than 3 times per second. The script includes a 1-second pause before fetching XML details to comply with NCBI rules.

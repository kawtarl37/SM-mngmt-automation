# Directive: Generate and Publish Blog from Approved Pin

## Purpose
After a Pinterest pin is approved in the dashboard, this directive governs the automated pipeline that:
1. Generates a full SEO-optimized blog post from the pin's topic
2. Publishes the blog (with featured image) to WordPress
3. Posts the pin to Pinterest with the blog URL as the external link

Publishing is scheduled at **3 times per day** — 8 AM, 12 PM, and 4 PM **US Eastern Time**.

---

## Inputs
- An approved `pin_id` from the `generated_pins` table (status = `approved`)
- The pin's `title`, `description`, and `image_path`
- The next Amazon product to rotate (picked by oldest `last_used` date from `amazon_products` table)
- WordPress REST API credentials (`WP_BASE_URL`, `WP_USERNAME`, `WP_APP_PASSWORD` in `.env`)
- Pinterest API access token and board ID in `.env`

---

## Full Pipeline Flow

```
[Dashboard: Pin Approved]
        ↓
[publish_scheduler.py → schedule_approved_pins()]
  → Assign next free time slot (8AM / 12PM / 4PM EST)
  → Insert into publish_schedule table (status: pending)
        ↓
[Cron: every 5 min → run_scheduled_publishes()]
  → Check publish_schedule WHERE scheduled_time <= now AND status = pending
        ↓
[blog_generator.py → generate_blog(pin_id)]
  → Pick Amazon product with oldest last_used
  → Call GPT-4o-mini with blog_generation.txt prompt
  → Fill locked HTML template (Blog-Template.md)
  → Save to blogs table
  → Update product last_used
        ↓
[wordpress_publisher.py → publish_blog_to_wp(blog_id)]
  → Upload pin image to WP Media Library (becomes featured image)
  → POST /wp-json/wp/v2/posts (status: publish)
  → Save wp_post_id and wp_url to blogs table
  → Update generated_pins.destination_url = wp_url
        ↓
[pinterest_publisher.py → post_pin_to_pinterest(pin_id, wp_url, media_url)]
  → POST /v5/pins to Pinterest API
  → Log to posted_pins table
  → Mark generated_pins.status = published
        ↓
[publish_schedule → status: published, completed_at: now]
```

---

## Scripts

| Script | Purpose |
|---|---|
| `execution/content/blog_generator.py` | Generate blog HTML from pin topic |
| `execution/content/wordpress_publisher.py` | Upload image + publish post to WP |
| `execution/content/pinterest_publisher.py` | Post pin with blog link to Pinterest |
| `execution/content/publish_scheduler.py` | Manage time slots and run due publishes |
| `execution/dashboard.py` | Flask UI for review; triggers scheduling on approve |

---

## Scheduling Logic

- **3 slots per day**: 8:00 AM, 12:00 PM, 4:00 PM US/Eastern
- **Stored in UTC** in the `publish_schedule` table
- Slots are assigned sequentially — if today's slots are taken, the next available day is used (up to 7 days ahead)
- The scheduler checks for due entries every time `run_scheduled_publishes()` is called
- **Recommended**: Run `run_scheduled_publishes()` on a cron job every 5 minutes

### Running the Scheduler (Windows Task Scheduler or manual)
```bash
# From the project root, activate venv first
cd c:\Users\HP\Documents\automation-EGF
venv\Scripts\activate
python -m execution.content.publish_scheduler
```

---

## Amazon Product Rotation

- Products are stored in `amazon_products` table (seeded from `db.py`)
- The product with the **oldest `last_used` timestamp** is always selected next
- After use, `last_used` is updated to the current UTC time
- With 5 products and ~3 posts/day, each product rotates roughly every 1–2 days

---

## WordPress Setup Required

1. Log into WordPress Admin → Users → Your Profile
2. Scroll to **Application Passwords**
3. Enter name "EGF Automation" → click **Add New Application Password**
4. Copy the generated password into `.env` as `WP_APP_PASSWORD`
5. Set `WP_USERNAME` to your WordPress username

> **Note:** WordPress must have the REST API enabled (it is by default). Confirm at:
> `https://easygluten-free.com/wp-json/wp/v2/posts`

---

## Error Handling & Self-Annealing

- If blog generation fails → `publish_schedule.status = failed`, error logged
- If WP publish fails → status = failed, blog generation is NOT retried (to avoid duplicate blogs)
- If Pinterest post fails → blog is already live; only the Pinterest step failed
- **Re-running failed slots**: Manually update `publish_schedule.status = 'pending'` to retry
- All errors are logged via the standard logger to timestamped log files

---

## Known Constraints

- Pinterest API v5: image must be a publicly accessible URL (we use WP Media Library for this)
- WP REST API: Application Password auth uses HTTP Basic Auth over HTTPS only
- GPT-4o-mini structured output: blog_generation prompt must stay under ~4000 tokens for input
- The HTML template structure is **locked** — do not rename CSS classes or add sections

---

## Pinterest OAuth 2.0 Setup

Pinterest uses OAuth 2.0 Authorization Code Flow. Tokens must be obtained interactively (user must log in and approve). This is a one-time setup — after that, `token_manager.py` handles refreshes automatically.

### Initial Setup (run once)

**Option A — Via Dashboard (recommended):**
1. Start the dashboard (`.\start-dashboard.bat`)
2. Click the **🔑 Re-auth Pinterest** button in the header
3. A Pinterest login popup opens → log in → click "Give Access"
4. Tokens are saved to `.env` automatically

**Option B — Standalone script:**
```bash
python -m execution.utils.pinterest_oauth
```
Opens the auth URL in your browser, catches the callback on port 8888, saves tokens.

### Registered Redirect URIs (must match exactly in Pinterest Developer app)
- `http://localhost:8888/callback` — used by the standalone script
- `http://localhost:5000/oauth/callback` — used by the dashboard button

### Token Behavior
- Access tokens expire after ~1 hour
- `continuous_refresh=true` was set during first exchange → **refresh tokens rotate** on each use
- `token_manager.py` auto-refreshes when `pinterest_publisher.py` gets a 401/403
- Both new `access_token` AND `refresh_token` are written back to `.env` on each refresh

### Trial Access vs Standard Access
- **Trial Access** (error code 29): Can read boards/pins but CANNOT create pins. Your app starts here.
- **Standard Access**: Required to post pins. Request at https://developers.pinterest.com/apps/ → your app → Request Standard Access
- Without Standard Access, no OAuth fix will allow pin posting.

---

## Learnings / Updates Log

| Date | Learning |
|---|---|
| 2026-04-02 | Initial directive created. Full pipeline built end-to-end. |
| 2026-04-11 | SANDBOX_MODE defaults to True — must set SANDBOX_MODE=False in .env for real posts |
| 2026-04-11 | Pinterest Trial Access (error code 29) blocks all pin creation — Standard Access required |
| 2026-04-11 | OAuth tokens obtained without continuous_refresh=true become one-time-use and expire immediately |
| 2026-04-11 | Dashboard OAuth callback must use port 5000 (dashboard port), not 8888 (standalone script port) |
| 2026-04-27 | Recipe posts land at `/product/` URLs — this is expected WooCommerce/WPRM behaviour; do NOT change post type. Pinterest pin link must use the `/product/` URL that WP returns in `wp_url`. |
| 2026-04-27 | Step images now uploaded to WP Media Library and attached to WPRM instruction steps via `image_id`. Recipe generator saves step images to `step_image_1/2/3` columns; publisher reads and uploads all three. |
| 2026-04-27 | Notes section restructured: `substitutions` field added to model → rendered as HTML `<ul>` under "Substitutions & Variations"; `notes` → "Claire's Gluten-Free Baking Notes"; `tips` → "Tips". Matches live recipe page format. |
| 2026-06-10 | Dashboard recipe cards now expose downloads for generated recipe images (`cover.jpg`, `step-1.jpg`, `step-2.jpg`, `step-3.jpg`) and a clean WPRM REST JSON payload (`title`, `status`, `recipe`) for manual import/testing. |
| 2026-06-15 | Recipe WordPress posts now include explicit inline step-by-step HTML after the WPRM shortcode: each uploaded step image URL is rendered immediately after the matching instruction step. This is a fallback for cases where WPRM ignores `instructions_flat[].image_id`. Recipe generation now includes `kcal_per_serving`; older recipes fall back to a rough ingredient-based kcal estimate in the post's Nutrition Facts block. |

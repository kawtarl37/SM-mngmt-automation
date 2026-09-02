import sqlite3
from typing import Optional, List, Dict
from pathlib import Path
from execution.config import DB_PATH

def get_connection():
    """Establish a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize the database schema if it doesn't exist."""
    db_file = Path(DB_PATH)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Recipes table (crawled and generated)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS recipes (
            recipe_id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            title_normalized TEXT NOT NULL,
            cuisine TEXT,
            cooking_method TEXT,
            ingredients TEXT,
            source TEXT DEFAULT 'generated',
            url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        # Trends table (from public Reddit JSON / blogs)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS trend_topics (
            topic_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            subreddit TEXT,
            title TEXT NOT NULL,
            body TEXT,
            score INTEGER DEFAULT 0,
            comment_count INTEGER DEFAULT 0,
            relevance REAL DEFAULT 0.0,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        # Generated ideas (20 per day)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS content_ideas (
            idea_id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content_type TEXT NOT NULL,
            description TEXT,
            content_lane TEXT,
            angle_type TEXT,
            freshness_hook TEXT,
            source_hint TEXT,
            engagement_score REAL DEFAULT 0.0,
            novelty_score REAL DEFAULT 0.0,
            seo_score REAL DEFAULT 0.0,
            brand_score REAL DEFAULT 0.0,
            total_score REAL DEFAULT 0.0,
            selected BOOLEAN DEFAULT FALSE,
            batch_date DATE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        # Assembled pins
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS generated_pins (
            pin_id INTEGER PRIMARY KEY AUTOINCREMENT,
            idea_id INTEGER REFERENCES content_ideas(idea_id),
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            seo_keywords TEXT,
            image_path TEXT,
            destination_url TEXT,
            status TEXT DEFAULT 'pending',
            rejection_reason TEXT,
            batch_date DATE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        # Posted pins log
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS posted_pins (
            post_id INTEGER PRIMARY KEY AUTOINCREMENT,
            pin_id INTEGER REFERENCES generated_pins(pin_id),
            pinterest_id TEXT,
            board_id TEXT,
            posted_at TIMESTAMP,
            scheduled_time TIMESTAMP
        )''')
        
        # Generated blogs (linked to pins)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS blogs (
            blog_id INTEGER PRIMARY KEY AUTOINCREMENT,
            pin_id INTEGER REFERENCES generated_pins(pin_id),
            title TEXT NOT NULL,
            html_content TEXT NOT NULL,
            category TEXT,
            product_id INTEGER,
            wp_post_id INTEGER,
            wp_url TEXT,
            wp_featured_image_id INTEGER,
            status TEXT DEFAULT 'generated',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            published_at TIMESTAMP
        )''')
        
        # Amazon products (selected by topic relevance, then rotation)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS amazon_products (
            product_id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            url TEXT NOT NULL,
            image_url TEXT NOT NULL,
            keywords TEXT,
            content_lanes TEXT,
            price_tier TEXT DEFAULT 'affordable',
            priority_score REAL DEFAULT 1.0,
            solution_tags TEXT,
            problem_tags TEXT,
            source_type TEXT DEFAULT 'manual',
            media_status TEXT DEFAULT 'complete',
            auto_created INTEGER DEFAULT 0,
            needs_manual_image INTEGER DEFAULT 0,
            evidence_notes TEXT,
            match_notes TEXT,
            active INTEGER DEFAULT 1,
            last_used TIMESTAMP
        )''')

        cursor.execute("PRAGMA table_info(amazon_products)")
        amazon_columns = {row[1] for row in cursor.fetchall()}
        if "keywords" not in amazon_columns:
            cursor.execute("ALTER TABLE amazon_products ADD COLUMN keywords TEXT")
        if "content_lanes" not in amazon_columns:
            cursor.execute("ALTER TABLE amazon_products ADD COLUMN content_lanes TEXT")
        if "price_tier" not in amazon_columns:
            cursor.execute("ALTER TABLE amazon_products ADD COLUMN price_tier TEXT DEFAULT 'affordable'")
        if "priority_score" not in amazon_columns:
            cursor.execute("ALTER TABLE amazon_products ADD COLUMN priority_score REAL DEFAULT 1.0")
        if "active" not in amazon_columns:
            cursor.execute("ALTER TABLE amazon_products ADD COLUMN active INTEGER DEFAULT 1")
        if "solution_tags" not in amazon_columns:
            cursor.execute("ALTER TABLE amazon_products ADD COLUMN solution_tags TEXT")
        if "problem_tags" not in amazon_columns:
            cursor.execute("ALTER TABLE amazon_products ADD COLUMN problem_tags TEXT")
        if "source_type" not in amazon_columns:
            cursor.execute("ALTER TABLE amazon_products ADD COLUMN source_type TEXT DEFAULT 'manual'")
        if "media_status" not in amazon_columns:
            cursor.execute("ALTER TABLE amazon_products ADD COLUMN media_status TEXT DEFAULT 'complete'")
        if "auto_created" not in amazon_columns:
            cursor.execute("ALTER TABLE amazon_products ADD COLUMN auto_created INTEGER DEFAULT 0")
        if "needs_manual_image" not in amazon_columns:
            cursor.execute("ALTER TABLE amazon_products ADD COLUMN needs_manual_image INTEGER DEFAULT 0")
        if "evidence_notes" not in amazon_columns:
            cursor.execute("ALTER TABLE amazon_products ADD COLUMN evidence_notes TEXT")
        if "match_notes" not in amazon_columns:
            cursor.execute("ALTER TABLE amazon_products ADD COLUMN match_notes TEXT")
        
        # Publish schedule (3 slots per day, US Eastern)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS publish_schedule (
            schedule_id INTEGER PRIMARY KEY AUTOINCREMENT,
            pin_id INTEGER REFERENCES generated_pins(pin_id),
            blog_id INTEGER,
            scheduled_time TIMESTAMP NOT NULL,
            status TEXT DEFAULT 'pending',
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )''')
        
        # Generated recipes (WP Recipe Maker compatible)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS generated_recipes (
            recipe_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            title          TEXT NOT NULL,
            category       TEXT NOT NULL,
            recipe_json    TEXT NOT NULL,
            cover_image    TEXT,
            pinterest_image TEXT,
            step_image_1   TEXT,
            step_image_2   TEXT,
            step_image_3   TEXT,
            status         TEXT DEFAULT \'pending\',
            wp_post_id     INTEGER,
            wp_url         TEXT,
            pinterest_id   TEXT,
            created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        cursor.execute("PRAGMA table_info(generated_recipes)")
        recipe_columns = {row[1] for row in cursor.fetchall()}
        if "pinterest_image" not in recipe_columns:
            cursor.execute("ALTER TABLE generated_recipes ADD COLUMN pinterest_image TEXT")
        if "recipe_idea_id" not in recipe_columns:
            cursor.execute("ALTER TABLE generated_recipes ADD COLUMN recipe_idea_id INTEGER")

        # Recipe title ideas (reviewed before full recipe/image generation)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS recipe_ideas (
            idea_id INTEGER PRIMARY KEY AUTOINCREMENT,
            mode TEXT NOT NULL,
            category TEXT NOT NULL,
            dish_request TEXT,
            suggested_title TEXT NOT NULL,
            rationale TEXT,
            duplicate_score REAL DEFAULT 0.0,
            duplicate_warning TEXT,
            status TEXT DEFAULT 'pending_review',
            generated_recipe_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        # API Cost tracking
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS api_usage (
            usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0.0,
            task TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        # Discovered trendy topics (AI synthesized/medical articles)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS trendy_topics (
            topic_id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            details TEXT NOT NULL,
            source TEXT NOT NULL,
            relevance_score REAL DEFAULT 0.0,
            content_lane TEXT,
            angle_type TEXT,
            freshness_hook TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        cursor.execute("PRAGMA table_info(content_ideas)")
        idea_columns = {row[1] for row in cursor.fetchall()}
        for column_name, column_type in {
            "content_lane": "TEXT",
            "angle_type": "TEXT",
            "freshness_hook": "TEXT",
            "source_hint": "TEXT",
        }.items():
            if column_name not in idea_columns:
                cursor.execute(f"ALTER TABLE content_ideas ADD COLUMN {column_name} {column_type}")

        cursor.execute("PRAGMA table_info(trendy_topics)")
        trendy_columns = {row[1] for row in cursor.fetchall()}
        for column_name, column_type in {
            "content_lane": "TEXT",
            "angle_type": "TEXT",
            "freshness_hook": "TEXT",
        }.items():
            if column_name not in trendy_columns:
                cursor.execute(f"ALTER TABLE trendy_topics ADD COLUMN {column_name} {column_type}")

        # Research/source intelligence tables for reusable blog/newsletter/app briefs
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS source_registry (
            source_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            source_type TEXT NOT NULL,
            base_url TEXT NOT NULL,
            lane TEXT NOT NULL,
            credibility_score REAL DEFAULT 0.0,
            monitor_frequency TEXT,
            notes TEXT,
            enabled BOOLEAN DEFAULT TRUE,
            approval_status TEXT DEFAULT 'pending_approval',
            added_by TEXT DEFAULT 'system',
            approved_at TIMESTAMP,
            approved_by TEXT,
            content_angle TEXT,
            best_home TEXT,
            fact_check_required BOOLEAN DEFAULT TRUE,
            priority_tier TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        cursor.execute("PRAGMA table_info(source_registry)")
        source_columns = {row[1] for row in cursor.fetchall()}
        for column_name, column_type in {
            "approval_status": "TEXT DEFAULT 'pending_approval'",
            "added_by": "TEXT DEFAULT 'system'",
            "approved_at": "TIMESTAMP",
            "approved_by": "TEXT",
            "content_angle": "TEXT",
            "best_home": "TEXT",
            "fact_check_required": "BOOLEAN DEFAULT TRUE",
            "priority_tier": "TEXT",
        }.items():
            if column_name not in source_columns:
                cursor.execute(f"ALTER TABLE source_registry ADD COLUMN {column_name} {column_type}")

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS source_notifications (
            notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER,
            notification_type TEXT NOT NULL,
            message TEXT NOT NULL,
            status TEXT DEFAULT 'unread',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP,
            FOREIGN KEY(source_id) REFERENCES source_registry(source_id)
        )''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS research_queries (
            query_id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_title TEXT NOT NULL,
            lane TEXT NOT NULL,
            angle_type TEXT,
            platform TEXT NOT NULL,
            source_type TEXT NOT NULL,
            query_text TEXT NOT NULL,
            priority INTEGER DEFAULT 1,
            reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS research_sources (
            research_source_id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_title TEXT NOT NULL,
            lane TEXT NOT NULL,
            source_type TEXT NOT NULL,
            url TEXT NOT NULL,
            title TEXT,
            credibility_score REAL DEFAULT 0.0,
            fetched_at TIMESTAMP,
            status TEXT DEFAULT 'planned',
            notes TEXT,
            snippet TEXT,
            published_at TIMESTAMP,
            external_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS research_facts (
            fact_id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_title TEXT NOT NULL,
            source_url TEXT NOT NULL,
            claim TEXT NOT NULL,
            evidence_text TEXT,
            confidence_score REAL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS content_briefs (
            brief_id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_title TEXT NOT NULL,
            lane TEXT NOT NULL,
            angle_type TEXT,
            platform TEXT NOT NULL,
            reader_problem TEXT,
            thesis TEXT,
            source_plan_json TEXT NOT NULL,
            source_candidates_json TEXT NOT NULL,
            platform_sections_json TEXT NOT NULL,
            status TEXT DEFAULT 'planned',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS content_drafts (
            draft_id INTEGER PRIMARY KEY AUTOINCREMENT,
            brief_id INTEGER,
            topic_title TEXT NOT NULL,
            lane TEXT NOT NULL,
            angle_type TEXT,
            platform TEXT NOT NULL,
            title TEXT NOT NULL,
            dek TEXT,
            content_json TEXT NOT NULL,
            source_urls_json TEXT NOT NULL,
            status TEXT DEFAULT 'pending_review',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            approved_at TIMESTAMP,
            approved_by TEXT,
            rejection_reason TEXT,
            FOREIGN KEY(brief_id) REFERENCES content_briefs(brief_id)
        )''')
        
        conn.commit()


def seed_amazon_products_legacy():
    """Seed the amazon_products table with the 5 initial products if empty."""
    products = [
        {
            "title": "Snack BOX Gluten Free Healthy Care Package",
            "description": "This box is basically \"emergency gluten-free social survival\" in one package. It's packed with individually wrapped snacks you can throw into your bag, keep at the office, bring to movie nights, or stash in your car so you don't end up nibbling sad plain lettuce while everyone else has chips. Great for sharing, hosting, travel, or just living your best snack-gremlin life — gluten free.",
            "url": "https://amzn.to/4fykY6E",
            "image_url": "https://easygluten-free.com/wp-content/uploads/2025/12/81C3QPKYRaL._SL1500_-1.webp",
            "last_used": "2026-03-17T09:02:55.962Z"
        },
        {
            "title": "Bentgo Chill Max Lunch Box",
            "description": "it's perfect for anyone who wants cute, organized, Instagram-able gluten-free lunches. The built-in ice pack keeps things fresh, the compartments are perfect for snacks, dips, and small portions, and it's leak-proof (so your hummus doesn't redecorate your tote bag). Ideal for school, work, picnics, travel days, or long study sessions.",
            "url": "https://amzn.to/4xkVjF2",
            "image_url": "https://easygluten-free.com/wp-content/uploads/2025/12/810iRItuBPL._AC_SL1500_-1.webp",
            "last_used": "2026-03-18T09:02:42.911Z"
        },
        {
            "title": "Premium Silicone Reusable Food Storage Bags",
            "description": "These are the \"I have my life together\" bags. Perfect for packing gluten-free snacks, leftovers from brunch, veggie sticks for road trips, or even freezer prep for busy weeks. They're reusable, dishwasher-safe, plastic-free, and look aesthetically pleasing in your fridge and your IG stories. Great anchor product for any article about sustainability, meal prep, hosting, or on-the-go GF living.",
            "url": "https://amzn.to/4ukEU0o",
            "image_url": "https://easygluten-free.com/wp-content/uploads/2025/12/71vgltzzXwL._AC_SL1500_.webp",
            "last_used": "2026-03-19T09:03:05.777Z"
        },
        {
            "title": "Bob's Red Mill Gluten Free 1 to 1 Baking Flour",
            "description": "This is the gold-standard gluten-free all-purpose flour. It behaves beautifully in pancakes, muffins, cookies, quick breads — and it's the ideal flour to recommend in ANY practical baking guide. Reliable, consistent, and approved by thousands of gluten-free home bakers. Perfect for articles about technique, substitutions, and baking success.",
            "url": "https://amzn.to/49LV9w8",
            "image_url": "https://easygluten-free.com/wp-content/uploads/2025/12/bobs.webp",
            "last_used": "2026-03-20T09:02:53.225Z"
        }
    ]
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM amazon_products")
        count = cursor.fetchone()[0]
        
        if count == 0:
            for p in products:
                cursor.execute(
                    """INSERT INTO amazon_products (title, description, url, image_url, last_used)
                       VALUES (?, ?, ?, ?, ?)""",
                    (p["title"], p["description"], p["url"], p["image_url"], p["last_used"])
                )
            conn.commit()
            print(f"Seeded {len(products)} Amazon products into DB.")
        else:
            print(f"Amazon products table already has {count} entries. Skipping seed.")


def seed_amazon_products():
    """Seed or enrich the approved Amazon product catalog."""
    products = [
        {
            "title": "Snack BOX Gluten Free Healthy Care Package",
            "description": "A practical gluten-free snack stash for travel days, offices, school bags, movie nights, road trips, and emergency backup food when safe options are hard to find.",
            "url": "https://amzn.to/4fykY6E",
            "image_url": "https://easygluten-free.com/wp-content/uploads/2025/12/81C3QPKYRaL._SL1500_-1.webp",
            "keywords": "snacks snack box travel road trip office school emergency backup pantry individually wrapped hosting social",
            "content_lanes": "product_watch,restaurant_travel_buzz,organization_life",
            "price_tier": "affordable",
            "priority_score": 1.15,
            "last_used": "2026-03-17T09:02:55.962Z",
        },
        {
            "title": "Bentgo Chill Max Lunch Box",
            "description": "A compartment lunch box with a built-in chill layer for organized gluten-free lunches, safe snacks, dips, school days, work meals, picnics, and travel days.",
            "url": "https://amzn.to/4xkVjF2",
            "image_url": "https://easygluten-free.com/wp-content/uploads/2025/12/810iRItuBPL._AC_SL1500_-1.webp",
            "keywords": "lunch box meal prep school work office travel picnic compartments snacks dips cold pack organized",
            "content_lanes": "kitchen_gadget_lab,organization_life,restaurant_travel_buzz,product_watch",
            "price_tier": "affordable",
            "priority_score": 1.25,
            "last_used": "2026-03-18T09:02:42.911Z",
        },
        {
            "title": "Premium Silicone Reusable Food Storage Bags",
            "description": "Reusable silicone bags for gluten-free snacks, leftovers, road trips, freezer prep, pantry organization, and low-waste kitchen systems.",
            "url": "https://amzn.to/4ukEU0o",
            "image_url": "https://easygluten-free.com/wp-content/uploads/2025/12/71vgltzzXwL._AC_SL1500_.webp",
            "keywords": "storage bags reusable silicone freezer meal prep leftovers snacks pantry organization kitchen travel dishwasher safe",
            "content_lanes": "organization_life,kitchen_gadget_lab,recipe_experiments,restaurant_travel_buzz",
            "price_tier": "affordable",
            "priority_score": 1.1,
            "last_used": "2026-03-19T09:03:05.777Z",
        },
        {
            "title": "Bob's Red Mill Gluten Free 1 to 1 Baking Flour",
            "description": "A reliable gluten-free all-purpose flour for pancakes, muffins, cookies, quick breads, copycat recipes, substitutions, and practical baking experiments.",
            "url": "https://amzn.to/49LV9w8",
            "image_url": "https://easygluten-free.com/wp-content/uploads/2025/12/bobs.webp",
            "keywords": "flour baking pancakes muffins cookies bread quick bread copycat recipe substitution gluten free flour blend",
            "content_lanes": "recipe_experiments,bread_wars,product_watch,science_without_boring",
            "price_tier": "affordable",
            "priority_score": 1.2,
            "last_used": "2026-03-20T09:02:53.225Z",
        },
    ]

    with get_connection() as conn:
        cursor = conn.cursor()
        inserted = 0
        enriched = 0

        for product in products:
            cursor.execute(
                """
                SELECT product_id
                FROM amazon_products
                WHERE lower(trim(title)) = lower(trim(?))
                LIMIT 1
                """,
                (product["title"],),
            )
            existing = cursor.fetchone()

            if existing:
                cursor.execute(
                    """
                    UPDATE amazon_products
                    SET keywords = ?,
                        content_lanes = ?,
                        price_tier = ?,
                        priority_score = ?
                    WHERE product_id = ?
                    """,
                    (
                        product["keywords"],
                        product["content_lanes"],
                        product["price_tier"],
                        product["priority_score"],
                        existing["product_id"],
                    ),
                )
                enriched += 1
                continue

            cursor.execute(
                """
                INSERT INTO amazon_products (
                    title,
                    description,
                    url,
                    image_url,
                    keywords,
                    content_lanes,
                    price_tier,
                    priority_score,
                    last_used
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product["title"],
                    product["description"],
                    product["url"],
                    product["image_url"],
                    product["keywords"],
                    product["content_lanes"],
                    product["price_tier"],
                    product["priority_score"],
                    product["last_used"],
                ),
            )
            inserted += 1

        conn.commit()
        print(f"Amazon products ready. Inserted {inserted}, enriched {enriched}.")


if __name__ == "__main__":
    init_db()
    seed_amazon_products()
    print(f"Database initialized at {DB_PATH}")

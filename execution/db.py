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
        
        # Amazon products (rotated by oldest last_used)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS amazon_products (
            product_id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            url TEXT NOT NULL,
            image_url TEXT NOT NULL,
            last_used TIMESTAMP
        )''')
        
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
            step_image_1   TEXT,
            step_image_2   TEXT,
            step_image_3   TEXT,
            status         TEXT DEFAULT \'pending\',
            wp_post_id     INTEGER,
            wp_url         TEXT,
            pinterest_id   TEXT,
            created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        conn.commit()


def seed_amazon_products():
    """Seed the amazon_products table with the 5 initial products if empty."""
    products = [
        {
            "title": "Nima gluten sensor test",
            "description": "These single-use capsules pair with the Nima Sensor to help users test foods for gluten on the spot. Perfect for travelers, researchers of their own digestive reactions, or anyone who just doesn't trust that café's \"gluten-free… we think?\" answer. A reliable, quick-gluten-detection option that empowers people who want data—not guesswork.",
            "url": "https://www.amazon.com/Check-Body-Health-Bioresonance-Sensitivities/dp/B08FRR5N9S/ref=sr_1_3?crid=RE8HFF2C3SO6&dib=eyJ2IjoiMSJ9.VZtv4K3j2aXYd4oj8JQLLAvyYW-o6t5kOFT9yjoCn7PnQE50k0b2TCFhoZqseUXyDdoIfWBIcQb5ojvttPwWFw.F52SlMGDBbGhtN4BAUEpy7DDRqNvGZQ59GFjJoUv7A4&dib_tag=se&keywords=nima+gluten+sensor+test&qid=1765458358&sprefix=nima+gluten+sensor+test%2Caps%2C1336&sr=8-3",
            "image_url": "https://easygluten-free.com/wp-content/uploads/2025/12/61v5G1T8YRL._AC_SL1500_-1-e1766570288924.webp",
            "last_used": "2026-03-22T08:02:17.344Z"
        },
        {
            "title": "Snack BOX Gluten Free Healthy Care Package",
            "description": "This box is basically \"emergency gluten-free social survival\" in one package. It's packed with individually wrapped snacks you can throw into your bag, keep at the office, bring to movie nights, or stash in your car so you don't end up nibbling sad plain lettuce while everyone else has chips. Great for sharing, hosting, travel, or just living your best snack-gremlin life — gluten free.",
            "url": "https://www.amazon.com/SnackBOX-Healthy-Students-Military-Valentines/dp/B07G5ML7LD/ref=sr_1_3?sr=8-3",
            "image_url": "https://easygluten-free.com/wp-content/uploads/2025/12/81C3QPKYRaL._SL1500_-1.webp",
            "last_used": "2026-03-17T09:02:55.962Z"
        },
        {
            "title": "Bentgo Chill Max Lunch Box",
            "description": "it's perfect for anyone who wants cute, organized, Instagram-able gluten-free lunches. The built-in ice pack keeps things fresh, the compartments are perfect for snacks, dips, and small portions, and it's leak-proof (so your hummus doesn't redecorate your tote bag). Ideal for school, work, picnics, travel days, or long study sessions.",
            "url": "https://www.amazon.com/Bentgo-Chill-Max-Leak-Proof-Lunch/dp/B0DWD47BW7/ref=sr_1_4?crid=LTGUF0WOTYDI&dib=eyJ2IjoiMSJ9.u0iF7nRzBcAiCXIMlgmy59B2nTDHEnhvH9WydJO0qoPiIRPq1lcMn9Ok7rwqKC3CYnzl8WzzfvST06ncjsu3CFLFaCd0gqjfnUPWp4GLJNuXc4a19y_QpC0YcAamxjeuK-IthDKeYvab_pIs7kcI-e2Y5LatHojmoD1bPAc7Ltk_8MNLktQyB_vU4BMqkNKUjncoPaEZbyDpLKNtCNMvCQSmK6lGHaBRDndFbEaFgteWRRBh1uOXpN1hl0Lsd9QDANpgiQkj_2kmgkgDFZMbNX9iHDs5sOzTx7AFOKyCPnc.sd6hQGNyP-NVs7m8F_06yDoQFL7qrNM60cSEUef21zs&dib_tag=se&keywords=Bentgo%2BChill%2BKids%2BLeak-Proof%2BLunch%2BBox&qid=1765467027&sprefix=bentgo%2Bchill%2Bkids%2Bleak-proof%2Blunch%2Bbox%2Caps%2C498&sr=8-4&th=1",
            "image_url": "https://easygluten-free.com/wp-content/uploads/2025/12/810iRItuBPL._AC_SL1500_-1.webp",
            "last_used": "2026-03-18T09:02:42.911Z"
        },
        {
            "title": "Premium Silicone Reusable Food Storage Bags",
            "description": "These are the \"I have my life together\" bags. Perfect for packing gluten-free snacks, leftovers from brunch, veggie sticks for road trips, or even freezer prep for busy weeks. They're reusable, dishwasher-safe, plastic-free, and look aesthetically pleasing in your fridge and your IG stories. Great anchor product for any article about sustainability, meal prep, hosting, or on-the-go GF living.",
            "url": "https://www.amazon.com/Stasher-Bag-Leakproof-Dishwasher-Safe-Eco-friendly/dp/B087XBR564/ref=sr_1_1?sr=8-1&th=1",
            "image_url": "https://easygluten-free.com/wp-content/uploads/2025/12/71vgltzzXwL._AC_SL1500_.webp",
            "last_used": "2026-03-19T09:03:05.777Z"
        },
        {
            "title": "Bob's Red Mill Gluten Free 1 to 1 Baking Flour",
            "description": "This is the gold-standard gluten-free all-purpose flour. It behaves beautifully in pancakes, muffins, cookies, quick breads — and it's the ideal flour to recommend in ANY practical baking guide. Reliable, consistent, and approved by thousands of gluten-free home bakers. Perfect for articles about technique, substitutions, and baking success.",
            "url": "https://www.amazon.com/Bobs-Red-Mill-Baking-Gluten/dp/B07FXYJ5NT/ref=sr_1_2?nsdOptOutParam=true&sr=8-2&th=1",
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


if __name__ == "__main__":
    init_db()
    seed_amazon_products()
    print(f"Database initialized at {DB_PATH}")

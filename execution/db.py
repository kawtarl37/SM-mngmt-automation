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
        
        conn.commit()

if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")

import requests
import re
from execution.config import WORDPRESS_URL
from execution.db import get_connection
from execution.utils.logger import setup_logger

logger = setup_logger("wordpress_crawler")

def normalize_title(title: str) -> str:
    """Normalize a title for strict deduplication matching."""
    stop_words = {"best", "easy", "simple", "fluffy", "perfect", "quick", "the", "a", "an", "how", "to", "make"}
    words = title.lower().replace("-", " ").replace("|", " ").split()
    # Strip non-alphanumeric chars
    words = [re.sub(r'[^a-z0-9]', '', w) for w in words]
    return " ".join(w for w in words if w and w not in stop_words)

def fetch_wp_posts(page: int = 1, per_page: int = 100):
    """Fetch posts from the WordPress REST API."""
    url = f"{WORDPRESS_URL.rstrip('/')}/wp-json/wp/v2/posts"
    params = {
        "page": page,
        "per_page": per_page,
        "status": "publish",
        "_fields": "id,title,link"
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json(), int(response.headers.get("X-WP-TotalPages", 1))
    except Exception as e:
        logger.error(f"Failed to fetch WP posts page {page}: {e}")
        return [], 0

def run_crawler():
    """Main entrypoint: crawl the WP API to build the existing recipes database."""
    logger.info("Starting WordPress crawler...")
    
    page = 1
    total_pages = 1
    total_saved = 0
    
    with get_connection() as conn:
        cursor = conn.cursor()
        
        while page <= total_pages:
            logger.info(f"Fetching WP page {page}/{total_pages}...")
            posts, parsed_total_pages = fetch_wp_posts(page)
            
            if page == 1:
                total_pages = parsed_total_pages
                
            for post in posts:
                # Raw title often comes with HTML entities like &#8211;
                raw_title = post.get("title", {}).get("rendered", "")
                
                # Basic entity decoding (WordPress API usually uses numeric entities for dashes)
                title = raw_title.replace("&#8211;", "-").replace("&#8217;", "'").replace("&#038;", "&")
                normalized = normalize_title(title)
                url = post.get("link", "")
                
                # Insert or ignore (using a basic check to prevent duplicates if crawler runs multiple times)
                cursor.execute(
                    "SELECT recipe_id FROM recipes WHERE url = ?", (url,)
                )
                if not cursor.fetchone():
                    cursor.execute(
                        """INSERT INTO recipes 
                           (title, title_normalized, source, url)
                           VALUES (?, ?, ?, ?)""",
                        (title, normalized, "wordpress", url)
                    )
                    total_saved += 1
            
            page += 1
            
        conn.commit()
        
    logger.info(f"WordPress crawler completed. Newly saved recipes/posts: {total_saved}")
    return total_saved

if __name__ == "__main__":
    run_crawler()

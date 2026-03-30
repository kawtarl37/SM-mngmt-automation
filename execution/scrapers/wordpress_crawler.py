import requests
from bs4 import BeautifulSoup
import re
from execution.config import WORDPRESS_URL
from execution.db import get_connection
from execution.utils.logger import setup_logger

logger = setup_logger("wordpress_crawler")

def normalize_title(title: str) -> str:
    """Normalize a title for strict deduplication matching."""
    stop_words = {"best", "easy", "simple", "fluffy", "perfect", "quick", "the", "a", "an", "how", "to", "make"}
    words = title.lower().replace("-", " ").replace("|", " ").split()
    words = [re.sub(r'[^a-z0-9]', '', w) for w in words]
    return " ".join(w for w in words if w and w not in stop_words)

def run_crawler():
    """Main entrypoint: crawl the provided recipes HTML page to build the existing recipes database."""
    logger.info(f"Starting HTML crawler on {WORDPRESS_URL}...")
    
    total_saved = 0
    try:
        response = requests.get(WORDPRESS_URL, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        articles = soup.find_all('article')
        logger.info(f"Found {len(articles)} articles/recipes on page.")
        
        with get_connection() as conn:
            cursor = conn.cursor()
            
            for index, article in enumerate(articles):
                # Try to find a link to the recipe
                link_tag = article.find('a')
                if not link_tag or not link_tag.get('href'):
                    continue
                url = link_tag['href']
                
                # Try to find the title, usually in an h2 or h3, or use link text
                title_tag = article.find(['h2', 'h3'])
                if title_tag:
                    raw_title = title_tag.text.strip()
                elif link_tag.text.strip():
                    raw_title = link_tag.text.strip()
                else:
                    raw_title = f"Recipe {index+1}"
                
                # Basic entity decoding
                title = raw_title.replace("&#8211;", "-").replace("&#8217;", "'").replace("&#038;", "&")
                normalized = normalize_title(title)
                
                # Insert or ignore based on URL
                cursor.execute(
                    "SELECT recipe_id FROM recipes WHERE url = ?", (url,)
                )
                if not cursor.fetchone():
                    cursor.execute(
                        """INSERT INTO recipes 
                           (title, title_normalized, source, url)
                           VALUES (?, ?, ?, ?)""",
                        (title, normalized, "wordpress_html", url)
                    )
                    total_saved += 1
            
            conn.commit()
            
        logger.info(f"HTML crawler completed. Newly saved recipes: {total_saved}")
        
    except Exception as e:
        logger.error(f"Failed to crawl {WORDPRESS_URL}: {e}")
        
    return total_saved

if __name__ == "__main__":
    run_crawler()


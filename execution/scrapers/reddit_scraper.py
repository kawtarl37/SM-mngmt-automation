import requests
import time
from execution.config import REDDIT_USER_AGENT, SUBREDDITS
from execution.db import get_connection
from execution.utils.logger import setup_logger

logger = setup_logger("reddit_scraper")

def fetch_subreddit_top_json(subreddit: str, limit: int = 50):
    """
    Fetch the top posts of the day using Reddit's public JSON feed.
    Bypasses the need for OAuth/PRAW.
    """
    url = f"https://www.reddit.com/r/{subreddit}/top.json?t=day&limit={limit}"
    headers = {"User-Agent": REDDIT_USER_AGENT}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch r/{subreddit}: {e}")
        return None

def save_trends_to_db(posts: list, subreddit: str):
    """Save parsed Reddit JSON posts into the trend_topics table."""
    saved_count = 0
    with get_connection() as conn:
        cursor = conn.cursor()
        for post in posts:
            data = post.get("data", {})
            title = data.get("title")
            
            if not title:
                continue
                
            cursor.execute(
                """INSERT INTO trend_topics
                   (source, subreddit, title, body, score, comment_count)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    "reddit",
                    subreddit,
                    title,
                    data.get("selftext", ""),
                    data.get("score", 0),
                    data.get("num_comments", 0)
                )
            )
            saved_count += 1
        conn.commit()
    return saved_count

def run_scraper():
    """Main entrypoint: scrape all configured subreddits."""
    logger.info("Starting Reddit public JSON scraper...")
    
    total_saved = 0
    for sub in SUBREDDITS:
        logger.info(f"Fetching r/{sub}...")
        
        # Be polite to the public API
        time.sleep(2) 
        
        json_data = fetch_subreddit_top_json(sub)
        if json_data and "data" in json_data and "children" in json_data["data"]:
            posts = json_data["data"]["children"]
            saved = save_trends_to_db(posts, sub)
            total_saved += saved
            logger.info(f"Saved {saved} posts from r/{sub}")
            
    logger.info(f"Reddit scraper completed. Total posts saved: {total_saved}")
    return total_saved

if __name__ == "__main__":
    run_scraper()

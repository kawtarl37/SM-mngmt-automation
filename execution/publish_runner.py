import os
import sys
from pathlib import Path
import requests
# Imports from the execution package

from execution.config import (
    GOOGLE_API_KEY,
    IMAGE_GENERATION_PROVIDER,
    OPENAI_API_KEY,
    OPENAI_IMAGE_API_KEY,
    PINTEREST_ACCESS_TOKEN,
    WP_APP_PASSWORD,
    WP_BASE_URL,
    DB_PATH
)
from execution.content.publish_scheduler import run_scheduled_publishes
from execution.utils.logger import setup_logger

logger = setup_logger("publish_runner")

def check_system_health():
    """Verify all required API keys and connections are active."""
    logger.info("🔍 Running System Health Check...")
    
    missing = []
    if not OPENAI_API_KEY: missing.append("OPENAI_API_KEY")
    if IMAGE_GENERATION_PROVIDER == "openai" and not OPENAI_IMAGE_API_KEY:
        missing.append("OPENAI_IMAGE_API_KEY or OPENAI_API_KEY")
    if IMAGE_GENERATION_PROVIDER == "gemini" and not GOOGLE_API_KEY:
        missing.append("GOOGLE_API_KEY")
    if not PINTEREST_ACCESS_TOKEN: missing.append("PINTEREST_ACCESS_TOKEN")
    if not WP_APP_PASSWORD: missing.append("WP_APP_PASSWORD")
    
    if missing:
        logger.error(f"❌ Missing environment variables: {', '.join(missing)}")
        return False

    # Check Database
    if not Path(DB_PATH).exists():
        logger.error(f"❌ Database not found at {DB_PATH}")
        return False
    
    # Check WordPress REST API
    try:
        wp_test_url = f"{WP_BASE_URL}/wp-json/wp/v2/posts?per_page=1"
        resp = requests.get(wp_test_url, timeout=10)
        if resp.status_code != 200:
            logger.warning(f"⚠️ WordPress API returned status {resp.status_code}. Public access might be restricted.")
    except Exception as e:
        logger.error(f"❌ Could not connect to WordPress API: {e}")
        return False

    logger.info("✅ System Health Check Passed!")
    return True

def main():
    """Main entry point for the publishing runner."""
    logger.info("🚀 Starting EGF Publish Runner...")
    
    if not check_system_health():
        logger.error("❌ Health check failed. Aborting run.")
        sys.exit(1)
        
    try:
        run_scheduled_publishes()
        logger.info("✅ Publish runner finished successfully.")
    except Exception as e:
        logger.error(f"❌ Publish runner failed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()

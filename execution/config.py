import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from the .env file
BASE_DIR = Path(__file__).resolve().parent.parent
env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=env_path)

# Database
DB_PATH = os.getenv("DB_PATH", "execution/data/egf.db")

# API Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# Pinterest
PINTEREST_ACCESS_TOKEN = os.getenv("PINTEREST_ACCESS_TOKEN")
PINTEREST_BOARD_ID = os.getenv("PINTEREST_BOARD_ID")

# Reddit Scraping
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "EGF-Automation/1.0 (Contact: user@easygluten-free.com)")
SUBREDDITS = [
    "glutenfree",
    "glutenfreebaking",
    "glutenfreecooking",
    "glutenfreerecipes",
    "celiac"
]

# WordPress (recipe crawling)
WORDPRESS_URL = os.getenv("WORDPRESS_URL", "https://easygluten-free.com/")

# WordPress API (blog publishing)
WP_BASE_URL = os.getenv("WP_BASE_URL", "https://easygluten-free.com")
WP_USERNAME = os.getenv("WP_USERNAME")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD")

# Settings
DAILY_PIN_COUNT = 3
DAILY_IDEA_GENERATION_COUNT = 20
TEXT_PREFERENCE_MODEL = "gpt-4o-mini"  # Primary model
IMAGE_GENERATION_MODEL = "imagen-4.0-generate-001"  # Imagen 4.0 Approved

# Scheduling (3 pins/day, spaced 4 hours apart in US Eastern)
PUBLISH_TIMEZONE = os.getenv("PUBLISH_TIMEZONE", "US/Eastern")
DAILY_PUBLISH_COUNT = 3
PUBLISH_INTERVAL_HOURS = 4  # Gap between each publish
PUBLISH_START_HOUR = 8      # First post at 8 AM local time

# Directories
PROMPTS_DIR = BASE_DIR / "execution" / "prompts"
TMP_PINS_DIR = BASE_DIR / ".tmp" / "pins"
BLOG_TEMPLATE_PATH = BASE_DIR / "Blog-Template.md"

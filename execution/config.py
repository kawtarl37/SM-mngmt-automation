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
OPENAI_IMAGE_API_KEY = os.getenv("OPENAI_IMAGE_API_KEY") or OPENAI_API_KEY
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# Pinterest
PINTEREST_ACCESS_TOKEN = os.getenv("PINTEREST_ACCESS_TOKEN")
PINTEREST_BOARD_ID = os.getenv("PINTEREST_BOARD_ID")

# Pinterest Sandbox (for API access review demo)
PINTEREST_SANDBOX_TOKEN = os.getenv("PINTEREST_SANDBOX_TOKEN") or os.getenv("PINTEREST_ACCESS_TOKEN")
PINTEREST_SANDBOX_BOARD_ID = os.getenv("PINTEREST_SANDBOX_BOARD_ID") or os.getenv("PINTEREST_BOARD_ID")

# Brave Search API (web-search research collector)
BRAVE_SEARCH_API_KEY = os.getenv("BRAVE_SEARCH_API_KEY")

# WordPress (recipe crawling)
WORDPRESS_URL = os.getenv("WORDPRESS_URL", "https://easygluten-free.com/")

# WordPress API (blog publishing)
WP_BASE_URL = os.getenv("WP_BASE_URL", "https://easygluten-free.com")
WP_USERNAME = os.getenv("WP_USERNAME")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD")

# Affiliate links
AMAZON_ASSOCIATE_TAG = os.getenv("AMAZON_ASSOCIATE_TAG", "").strip()

# Settings
SANDBOX_MODE = os.getenv("SANDBOX_MODE", "True").lower() == "true"
LANE_ROTATION_COUNT = int(os.getenv("LANE_ROTATION_COUNT", "6"))  # Lanes covered per automated rotation run
TEXT_PREFERENCE_MODEL = "gpt-4o-mini"  # Primary model
IMAGE_GENERATION_PROVIDER = os.getenv("IMAGE_GENERATION_PROVIDER", "openai").lower()
IMAGE_GENERATION_MODEL = os.getenv("IMAGE_GENERATION_MODEL", "gpt-image-2")
IMAGE_GENERATION_QUALITY = os.getenv("IMAGE_GENERATION_QUALITY", "medium")
IMAGE_GENERATION_FORMAT = os.getenv("IMAGE_GENERATION_FORMAT", "jpeg")
GEMINI_IMAGE_GENERATION_MODEL = os.getenv("GEMINI_IMAGE_GENERATION_MODEL", "imagen-4.0-generate-001")
PIN_IMAGE_GENERATION_SIZE = os.getenv("PIN_IMAGE_GENERATION_SIZE", "1024x1536")
STEP_IMAGE_GENERATION_SIZE = os.getenv("STEP_IMAGE_GENERATION_SIZE", "1024x1024")

# Scheduling (3 pins/day, spaced 4 hours apart in US Eastern)
PUBLISH_TIMEZONE = os.getenv("PUBLISH_TIMEZONE", "US/Eastern")
DAILY_PUBLISH_COUNT = 3
PUBLISH_INTERVAL_HOURS = 4  # Gap between each publish
PUBLISH_START_HOUR = 8      # First post at 8 AM local time

# Directories
PROMPTS_DIR = BASE_DIR / "execution" / "prompts"
TMP_PINS_DIR = BASE_DIR / ".tmp" / "pins"
BLOG_TEMPLATE_PATH = BASE_DIR / "Blog-Template.md"

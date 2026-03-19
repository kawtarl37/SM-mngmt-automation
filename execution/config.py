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

# WordPress
WORDPRESS_URL = os.getenv("WORDPRESS_URL", "https://easygluten-free.com/")

# Settings
DAILY_PIN_COUNT = 3
DAILY_IDEA_GENERATION_COUNT = 20
TEXT_PREFERENCE_MODEL = "gpt-4o-mini" # Primary model
IMAGE_GENERATION_MODEL = "gemini-2.0-flash-exp" # Nano Banana

# Directories
PROMPTS_DIR = BASE_DIR / "execution" / "prompts"
TMP_PINS_DIR = BASE_DIR / ".tmp" / "pins"

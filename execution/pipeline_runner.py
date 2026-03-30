import sys
from pathlib import Path

# Add the project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from execution.scrapers.reddit_scraper import run_scraper
from execution.scrapers.wordpress_crawler import run_crawler
from execution.intelligence.trend_analyzer import rank_trends
from execution.intelligence.idea_generator import generate_ideas
from execution.intelligence.idea_scorer import score_and_select_ideas
from execution.content.pin_assembler import assemble_pins
from execution.utils.logger import setup_logger

logger = setup_logger("pipeline_runner")

def run_full_pipeline():
    """
    Orchestrate the full daily pipeline as per PRD Step 4.1.
    """
    logger.info("🚀 Starting Daily Content Pipeline...")

    try:
        # 1. Collect data (Reddit)
        logger.info("Step 1: Collecting data from Reddit...")
        run_scraper()

        # 2. Analyze trending topics (Ranking)
        logger.info("Step 2: Ranking trending topics...")
        rank_trends()

        # 3. Generate content ideas & Score them
        logger.info("Step 3: Generating and scoring content ideas...")
        generate_ideas()
        score_and_select_ideas()

        # 4. Assemble pins (Captions + Images)
        logger.info("Step 4: Assembling pins (Captions and Imagen 4.0 images)...")
        assemble_pins()

        logger.info("✅ Daily pipeline execution completed successfully!")
        logger.info("Pending pins are now ready for review in the dashboard.")

    except Exception as e:
        logger.error(f"❌ Pipeline failed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    run_full_pipeline()

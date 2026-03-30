from execution.content.caption_generator import generate_captions
from execution.content.image_generator import generate_all_pending_images
from execution.utils.logger import setup_logger

logger = setup_logger("pin_assembler")

def assemble_pins():
    """
    Run the content production sequence:
    1. Generate captions for the top ideas.
    2. Generate images for those pins.
    Both steps update the SQLite DB directly.
    """
    logger.info("Starting pin assembly sequence...")
    
    generate_captions()
    generate_all_pending_images()
    
    logger.info("Pin assembly sequence complete. Pins are now stored in the DB as 'pending' review.")

if __name__ == "__main__":
    assemble_pins()

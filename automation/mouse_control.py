"""
Mouse movement and clicking automation.
"""
import pyautogui
from utils.logger import get_logger

logger = get_logger(__name__)

def click_element(x: int, y: int):
    """
    Move mouse to coordinates and click.
    """
    logger.debug("Clicking at {}, {}", x, y)
    # TODO: Implement smooth mouse movement and click
    pass

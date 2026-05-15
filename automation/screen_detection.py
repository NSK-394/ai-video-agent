"""
Computer vision for locating UI elements on screen.
"""
import cv2
from utils.logger import get_logger

logger = get_logger(__name__)

def find_ui_element(template_path: str) -> tuple:
    """
    Find coordinates of a UI element on screen using template matching.
    """
    logger.info("Searching for UI element: {}", template_path)
    # TODO: Take screenshot and use cv2.matchTemplate
    return (0, 0)

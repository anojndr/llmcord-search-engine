"""
Constants Module

This module defines constants used throughout the application.
"""

import logging
from typing import Tuple

import discord

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Models that support vision capabilities
VISION_MODEL_TAGS: Tuple[str, ...] = (
    "gpt-4o",
    "claude-3",
    "gemini",
    "pixtral",
    "llava",
    "vision",
    "vl",
    "grok",
)
logger.debug(f"Vision model tags defined: {VISION_MODEL_TAGS}")

# Providers that support usernames in messages
PROVIDERS_SUPPORTING_USERNAMES: Tuple[str, ...] = (
    "openai", 
)
logger.debug(f"Providers supporting usernames defined: {PROVIDERS_SUPPORTING_USERNAMES}")

# Allowed file types for attachments
ALLOWED_FILE_TYPES: Tuple[str, ...] = (
    "image", 
    "text", 
    "application", 
    "audio"
)
logger.debug(f"Allowed file types defined: {ALLOWED_FILE_TYPES}")

# Discord embed colors
EMBED_COLOR_COMPLETE: discord.Color = discord.Color.dark_green()
EMBED_COLOR_INCOMPLETE: discord.Color = discord.Color.orange()
logger.debug("Embed colors defined")

# Streaming response indicator for incomplete messages
STREAMING_INDICATOR: str = " ⚪"
logger.debug(f"Streaming indicator defined: {STREAMING_INDICATOR}")

# Delay between edits to prevent rate limiting
EDIT_DELAY_SECONDS: int = 1
logger.debug(f"Edit delay defined: {EDIT_DELAY_SECONDS} seconds")

# Maximum number of message nodes to store in memory
MAX_MESSAGE_NODES: int = 100
logger.debug(f"Maximum message nodes defined: {MAX_MESSAGE_NODES}")

logger.info("Constants module initialized successfully")
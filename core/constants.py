"""
Constants Module

This module defines constants used throughout the application.
"""

from typing import Tuple
import discord

# Models that support vision capabilities
VISION_MODEL_TAGS: Tuple[str, ...] = (
    "gpt-4o",
    "claude-3",
    "gemini",
    "pixtral",
    "llava",
    "vision",
    "vl",
)

# Providers that support usernames in messages
PROVIDERS_SUPPORTING_USERNAMES: Tuple[str, ...] = ("openai", "x-ai")

# Allowed file types for attachments
ALLOWED_FILE_TYPES: Tuple[str, ...] = ("image", "text")

# Discord embed colors
EMBED_COLOR_COMPLETE: discord.Color = discord.Color.dark_green()
EMBED_COLOR_INCOMPLETE: discord.Color = discord.Color.orange()

# Streaming response indicator for incomplete messages
STREAMING_INDICATOR: str = " ⚪"

# Delay between edits to prevent rate limiting
EDIT_DELAY_SECONDS: int = 1

# Maximum number of message nodes to store in memory
MAX_MESSAGE_NODES: int = 100
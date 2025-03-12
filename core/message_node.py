"""
Message Node Module

This module defines the MsgNode dataclass used for storing and managing
Discord message data and state during conversations.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Literal

from discord import Message, File

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@dataclass
class MsgNode:
    """
    Data class representing a message node in a conversation chain.
    
    Attributes:
        text: Message text content
        images: List of image data for vision models
        role: Role of the message sender (user or assistant)
        user_id: Discord user ID
        next_msg: Next message in the conversation chain
        has_bad_attachments: Flag for unsupported attachments
        fetch_next_failed: Flag for failed fetch attempts
        lock: Asyncio lock for thread safety
        serper_queries: Search queries used for the message
        image_files: Discord File objects for images
        image_urls: URLs for images that couldn't be downloaded
        internet_used: Flag indicating if internet search was used
    """
    text: Optional[str] = None
    images: List[Dict[str, Any]] = field(default_factory=list)
    role: Literal["user", "assistant"] = "assistant"
    user_id: Optional[int] = None
    next_msg: Optional[Message] = None
    has_bad_attachments: bool = False
    fetch_next_failed: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    serper_queries: Optional[List[str]] = None
    image_files: Optional[Dict[str, List[File]]] = None
    image_urls: Optional[Dict[str, List[str]]] = None
    internet_used: bool = False
    
    def __post_init__(self):
        """Runs after initialization to log message creation."""
        logger.debug(
            f"Created MsgNode: role={self.role}, user_id={self.user_id}, "
            f"has_bad_attachments={self.has_bad_attachments}, "
            f"internet_used={self.internet_used}"
        )
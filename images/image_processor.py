"""
Image Processor Module

This module handles image fetching and processing for Discord messages.
It provides functions to fetch images for search queries and update message views.
"""

import logging
import asyncio
from typing import Dict, List, Optional
import httpx
from discord import File, Message

from config.api_key_manager import APIKeyManager
from core.message_node import MsgNode
from core.discord_ui import OutputView
from images.searxng_image_handler import fetch_images

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

async def fetch_images_and_update_views(
    split_queries: List[str],
    user_msg_id: int,
    response_msgs: List[Message],
    api_key_manager: APIKeyManager,
    httpx_client: httpx.AsyncClient,
    msg_nodes: Dict[int, MsgNode]
) -> None:
    """
    Fetch images for search queries and update Discord message views.
    
    This function runs as a background task after the initial response is sent.
    It fetches images for each search query, updates the message node with the results,
    and updates all response messages with the new view containing image buttons.
    
    Args:
        split_queries: List of search queries
        user_msg_id: ID of the user message
        response_msgs: List of response messages to update
        api_key_manager: API key manager instance
        httpx_client: HTTP client
        msg_nodes: Dictionary of message nodes
    """
    try:
        image_files_dict: Dict[str, List[File]]
        image_urls_dict: Dict[str, List[str]]
        image_files_dict, image_urls_dict = await fetch_images(split_queries, 5, api_key_manager, httpx_client)

        # Update the user message node with the fetched images
        if user_msg_id in msg_nodes:
            async with msg_nodes[user_msg_id].lock:
                msg_nodes[user_msg_id].image_files = image_files_dict
                msg_nodes[user_msg_id].image_urls = image_urls_dict

            # Update all response messages with the new view containing image buttons
            for response_msg in response_msgs:
                if response_msg.id in msg_nodes:
                    new_view: OutputView = OutputView(
                        contents=msg_nodes[response_msg.id].text,
                        query=msg_nodes[user_msg_id].text,
                        serper_queries=split_queries,
                        image_files=image_files_dict,
                        image_urls=image_urls_dict
                    )
                    try:
                        await response_msg.edit(view=new_view)
                    except Exception as edit_error:
                        logger.error(f"Error updating message {response_msg.id} with images: {edit_error}")
    except Exception as e:
        logger.error(f"Error in image fetch background task: {e}")
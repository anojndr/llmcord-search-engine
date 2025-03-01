"""
Image Processor Module

This module handles image fetching and processing for Discord messages.
It provides functions to fetch images for search queries and update message views.
"""

import asyncio
import logging
from typing import Dict, List, Optional

import httpx
from discord import File, Message

from config.api_key_manager import APIKeyManager
from core.discord_ui import OutputView
from core.message_node import MsgNode
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
        logger.info(
            f"Fetching images for {len(split_queries)} queries: "
            f"{', '.join(split_queries)}"
        )
        
        # Fetch images for all queries
        image_files_dict: Dict[str, List[File]]
        image_urls_dict: Dict[str, List[str]]
        image_files_dict, image_urls_dict = await fetch_images(
            split_queries, 5, api_key_manager, httpx_client
        )
        
        total_images = sum(len(files) for files in image_files_dict.values())
        total_urls = sum(len(urls) for urls in image_urls_dict.values())
        logger.info(
            f"Fetched {total_images} images and {total_urls} image URLs"
        )

        # Update the user message node with the fetched images
        if user_msg_id in msg_nodes:
            await _update_message_node_with_images(
                user_msg_id, 
                msg_nodes, 
                image_files_dict, 
                image_urls_dict
            )

            # Update all response messages with the new view
            await _update_response_messages_with_image_views(
                response_msgs,
                msg_nodes,
                user_msg_id,
                split_queries,
                image_files_dict,
                image_urls_dict
            )
        else:
            logger.warning(
                f"User message ID {user_msg_id} not found in msg_nodes when "
                f"updating images"
            )
    except Exception as e:
        logger.error(f"Error in image fetch background task: {e}", exc_info=True)


async def _update_message_node_with_images(
    user_msg_id: int,
    msg_nodes: Dict[int, MsgNode],
    image_files_dict: Dict[str, List[File]],
    image_urls_dict: Dict[str, List[str]]
) -> None:
    """
    Update the user message node with fetched images.
    
    Args:
        user_msg_id: ID of the user message
        msg_nodes: Dictionary of message nodes
        image_files_dict: Dictionary of image files
        image_urls_dict: Dictionary of image URLs
    """
    async with msg_nodes[user_msg_id].lock:
        msg_nodes[user_msg_id].image_files = image_files_dict
        msg_nodes[user_msg_id].image_urls = image_urls_dict
    logger.info(
        f"Updated user message node {user_msg_id} with image data"
    )


async def _update_response_messages_with_image_views(
    response_msgs: List[Message],
    msg_nodes: Dict[int, MsgNode],
    user_msg_id: int,
    split_queries: List[str],
    image_files_dict: Dict[str, List[File]],
    image_urls_dict: Dict[str, List[str]]
) -> None:
    """
    Update all response messages with new views containing image buttons.
    
    Args:
        response_msgs: List of response messages
        msg_nodes: Dictionary of message nodes
        user_msg_id: ID of the user message
        split_queries: List of search queries
        image_files_dict: Dictionary of image files
        image_urls_dict: Dictionary of image URLs
    """
    for response_msg in response_msgs:
        if response_msg.id in msg_nodes:
            # Create a new view with image data
            new_view = OutputView(
                contents=msg_nodes[response_msg.id].text,
                query=msg_nodes[user_msg_id].text,
                serper_queries=split_queries,
                image_files=image_files_dict,
                image_urls=image_urls_dict
            )
            
            try:
                # Update the message with the new view
                await response_msg.edit(view=new_view)
                logger.debug(
                    f"Updated message {response_msg.id} with image buttons"
                )
            except Exception as edit_error:
                logger.error(
                    f"Error updating message {response_msg.id} with images: "
                    f"{edit_error}", 
                    exc_info=True
                )
        else:
            logger.warning(
                f"Response message ID {response_msg.id} not found in msg_nodes "
                f"when updating images"
            )
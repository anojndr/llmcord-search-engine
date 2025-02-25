"""
Bot Client Module

This module defines the Discord bot client class that handles message events
and coordinates the different components of the application.
"""

import re
import logging
import asyncio
from datetime import datetime as dt
from typing import Dict, Any, List, Optional, Set, Tuple

import discord
import httpx
from discord import Message, AllowedMentions
from litellm import acompletion

from config.api_key_manager import APIKeyManager
from config.config_manager import get_config
from core.message_node import MsgNode
from core.message_processor import (
    build_conversation_context,
    handle_lens_sauce_commands,
    handle_regular_message
)
from images.image_processor import fetch_images_and_update_views
from core.response_handler import ResponseHandler
from core.discord_ui import OutputView
from llm.llm_service import LLMService
from core.constants import (
    ALLOWED_FILE_TYPES, 
    MAX_MESSAGE_NODES,
    STREAMING_INDICATOR,
    EDIT_DELAY_SECONDS
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class BotClient(discord.Client):
    """
    Discord bot client.
    
    This class extends discord.Client to handle message events
    and coordinate the bot's functionality.
    """
    
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.httpx_client = httpx.AsyncClient(http2=True)
        self.msg_nodes: Dict[int, MsgNode] = {}
        self.api_key_manager: Optional[APIKeyManager] = None
        self.last_task_time: Optional[float] = None
        self.initialize_resources()
    
    def initialize_resources(self) -> None:
        """Initialize bot resources such as API key manager."""
        cfg = get_config()
        self.api_key_manager = APIKeyManager(cfg)
        
        # Log bot invite URL if client_id is available
        if client_id := cfg.get("client_id"):
            logger.info(
                f"\n\nBOT INVITE URL:\nhttps://discord.com/api/oauth2/authorize?client_id={client_id}&permissions=412317273088&scope=bot\n"
            )
    
    async def close(self) -> None:
        """Close the bot client and all resources."""
        if self.httpx_client:
            await self.httpx_client.aclose()
        await super().close()
    
    def should_process_message(self, message: Message) -> bool:
        """
        Determine if a message should be processed by the bot.
        
        Args:
            message: The Discord message
            
        Returns:
            True if the message should be processed, False otherwise
        """
        # Ignore bot messages
        if message.author.bot:
            return False
        
        is_dm = message.channel.type == discord.ChannelType.private
        
        # Check for "at ai" or bot mention in non-DM channels
        at_ai_pattern = r'\bat ai\b'
        if (not is_dm and 
            not re.search(at_ai_pattern, message.content, re.IGNORECASE) and 
            self.user not in message.mentions):
            return False
        
        return True
    
    def check_permissions(self, message: Message) -> bool:
        """
        Check if the user and channel have permission to use the bot.
        
        Args:
            message: The Discord message
            
        Returns:
            True if the user and channel have permission, False otherwise
        """
        cfg = get_config()
        is_dm = message.channel.type == discord.ChannelType.private
        
        allow_dms = cfg["allow_dms"]
        allowed_channel_ids = cfg["allowed_channel_ids"]
        allowed_role_ids = cfg["allowed_role_ids"]
        blocked_user_ids = cfg["blocked_user_ids"]
        
        # Get all relevant channel IDs (current channel, parent, category)
        channel_ids: Tuple[int, ...] = tuple(
            id
            for id in (
                message.channel.id,
                getattr(message.channel, "parent_id", None),
                getattr(message.channel, "category_id", None),
            )
            if id
        )
        
        # Check if channel is allowed
        is_bad_channel = (is_dm and not allow_dms) or (
            not is_dm
            and allowed_channel_ids
            and not any(id in allowed_channel_ids for id in channel_ids)
        )
        
        # Check if user is allowed
        is_bad_user = message.author.id in blocked_user_ids or (
            allowed_role_ids
            and not any(
                role.id in allowed_role_ids for role in getattr(message.author, "roles", [])
            )
        )
        
        return not (is_bad_channel or is_bad_user)
    
    def clean_message_content(self, message: Message) -> None:
        """
        Clean the message content by removing bot mentions and 'at ai'.
        
        Args:
            message: The Discord message to clean
        """
        # Remove "at ai" text
        at_ai_pattern = r'\bat ai\b'
        content_without_at_ai = re.sub(at_ai_pattern, '', message.content, flags=re.IGNORECASE)
        
        # Remove bot mention
        content_without_mentions = content_without_at_ai.replace(self.user.mention, '').lstrip()
        
        # Update message content
        message.content = content_without_mentions
    
    def is_special_command(self, message: Message) -> Optional[str]:
        """
        Check if the message is a special command.
        
        Args:
            message: The Discord message
            
        Returns:
            Command type or None
        """
        if message.content.lower().startswith('lens'):
            return "lens"
        elif message.content.lower().startswith('sauce'):
            return "sauce"
        return None
    
    async def on_message(self, new_msg: Message) -> None:
        """
        Handle incoming Discord messages.
        
        Args:
            new_msg: The new Discord message
        """
        # Check if we should process this message
        if not self.should_process_message(new_msg):
            return
        
        # Clean message content
        self.clean_message_content(new_msg)
        
        # Check permissions
        if not self.check_permissions(new_msg):
            return
        
        cfg = get_config()
        allowed_mentions = AllowedMentions.none()
        
        # Send initial progress message
        progress_message: Message = await new_msg.reply(
            "Processing your request...",
            mention_author=False,
            allowed_mentions=allowed_mentions
        )
        
        try:
            # Get API key
            api_key: str = await self.api_key_manager.get_next_api_key(cfg["provider"])
            if not api_key:
                api_key = 'sk-no-key-required'
            
            # Calculate message limits
            use_plain_responses: bool = cfg["use_plain_responses"]
            max_message_length: int = (
                2000 if use_plain_responses else (4096 - len(STREAMING_INDICATOR))
            )
            
            # Build conversation context
            messages, user_warnings = await build_conversation_context(
                new_msg,
                self.user,
                self.msg_nodes,
                cfg,
                self.httpx_client,
                ALLOWED_FILE_TYPES
            )
            
            # Initialize user message node internet flag
            self.msg_nodes[new_msg.id].internet_used = False
            
            # Check for special commands
            cmd_type = self.is_special_command(new_msg)
            if cmd_type in ("lens", "sauce"):
                error = await handle_lens_sauce_commands(
                    new_msg,
                    cmd_type,
                    self.msg_nodes,
                    messages,
                    self.api_key_manager,
                    self.httpx_client,
                    cfg
                )
                if error:
                    await progress_message.edit(content=error, allowed_mentions=allowed_mentions)
                    return
            else:
                # Process regular message
                await handle_regular_message(
                    new_msg,
                    self.msg_nodes,
                    messages,
                    self.api_key_manager,
                    self.httpx_client,
                    cfg
                )
            
            # Prepare "Searched for" text if applicable
            serper_queries = getattr(self.msg_nodes[new_msg.id], 'serper_queries', None)
            if serper_queries:
                search_queries_text = ', '.join(f'"{q}"' for q in serper_queries)
                searched_for_text = f"Searched for: {search_queries_text}\n\n"
            else:
                searched_for_text = ''
            
            # Get LLM response
            success, stream = await LLMService.get_completion(messages, cfg, api_key)
            if not success:
                await progress_message.edit(
                    content="An error occurred while processing your request (rate limit exceeded).",
                    allowed_mentions=allowed_mentions
                )
                return
            
            # Handle the response
            if use_plain_responses:
                # Handle plain text response (non-streaming)
                response_contents = []
                prev_chunk = None
                
                async for curr_chunk in stream:
                    prev_content = (prev_chunk.choices[0].delta.content
                                  if (prev_chunk is not None and prev_chunk.choices[0].delta.content)
                                  else "")
                    curr_content = curr_chunk.choices[0].delta.content or ""
                    
                    if response_contents or prev_content:
                        if response_contents == [] or len(response_contents[-1] + prev_content) > max_message_length:
                            response_contents.append("")
                        response_contents[-1] += prev_content
                    
                    prev_chunk = curr_chunk
                
                response_msgs = await ResponseHandler.handle_plain_text_response(
                    response_contents,
                    progress_message,
                    new_msg.content,
                    self.msg_nodes,
                    allowed_mentions,
                    new_msg,
                    serper_queries
                )
            else:
                # Handle streaming response
                response_msgs = await ResponseHandler.handle_streaming_response(
                    stream,
                    progress_message,
                    new_msg.content,
                    new_msg.id,
                    self.msg_nodes,
                    user_warnings,
                    cfg,
                    allowed_mentions,
                    new_msg,
                    max_message_length,
                    serper_queries,
                    searched_for_text
                )
            
            # Manage message node cache size
            if (num_nodes := len(self.msg_nodes)) > MAX_MESSAGE_NODES:
                for msg_id in sorted(self.msg_nodes.keys())[: num_nodes - MAX_MESSAGE_NODES]:
                    async with self.msg_nodes.setdefault(msg_id, MsgNode()).lock:
                        self.msg_nodes.pop(msg_id, None)
            
            # Start background task to fetch images if serper queries exist
            user_msg_node = self.msg_nodes.get(new_msg.id)
            if user_msg_node and user_msg_node.serper_queries:
                asyncio.create_task(
                    fetch_images_and_update_views(
                        user_msg_node.serper_queries,
                        new_msg.id,
                        response_msgs,
                        self.api_key_manager,
                        self.httpx_client,
                        self.msg_nodes
                    )
                )
                
        except Exception as e:
            logger.exception("Error in on_message handler")
            await progress_message.edit(
                content=f"An error occurred while processing your request: {str(e)}",
                allowed_mentions=allowed_mentions
            )
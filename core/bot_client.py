"""
Bot Client Module

This module defines the Discord bot client class that handles message events
and coordinates the different components of the application.
"""

import asyncio
import logging
import re
from datetime import datetime as dt
from typing import Dict, Any, List, Optional, Set, Tuple, AsyncGenerator

import discord
import httpx
from discord import Message, AllowedMentions
from litellm import acompletion

from commands.setup import setup_commands
from config.api_key_manager import APIKeyManager
from config.config_manager import get_config
from core.constants import (
    ALLOWED_FILE_TYPES,
    MAX_MESSAGE_NODES,
    STREAMING_INDICATOR,
    EDIT_DELAY_SECONDS
)
from core.discord_ui import OutputView
from core.message_node import MsgNode
from core.message_processor import (
    build_conversation_context,
    handle_lens_sauce_commands,
    handle_regular_message
)
from core.response_handler import ResponseHandler
from images.image_processor import fetch_images_and_update_views
from llm.llm_service import LLMService

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class BotClient(discord.Client):
    """
    Discord bot client.
    
    This class extends discord.Client to handle message events
    and coordinate the bot's functionality.
    """
    
    def __init__(self, *args, **kwargs) -> None:
        """
        Initialize the Discord bot client.
        
        Args:
            *args: Variable length argument list for parent class
            **kwargs: Arbitrary keyword arguments for parent class
        """
        super().__init__(*args, **kwargs)
        logger.info("Initializing BotClient")
        self.httpx_client = httpx.AsyncClient(http2=True)
        self.msg_nodes: Dict[int, MsgNode] = {}
        self.command_manager = None
        self.api_key_manager: Optional[APIKeyManager] = None
        self.last_task_time: Optional[float] = None
        self.initialize_resources()
    
    def initialize_resources(self) -> None:
        """Initialize bot resources such as API key manager."""
        # Initialize API key manager
        logger.info("Initializing bot resources")
        cfg = get_config()
        self.api_key_manager = APIKeyManager(cfg)
        
        # Log bot invite URL if client_id is available
        if client_id := cfg.get("client_id"):
            logger.info(
                f"\n\nBOT INVITE URL:\n"
                f"https://discord.com/api/oauth2/authorize?client_id="
                f"{client_id}&permissions=412317273088&scope=bot\n"
            )
        else:
            logger.warning(
                "No client_id found in config, can't generate invite URL"
            )

        # Set up slash commands
        self.command_manager = setup_commands(self, self.api_key_manager)
    
    async def setup_hook(self) -> None:
        """
        Async setup hook that runs before the bot starts.
        This is used to sync slash commands.
        """
        try:
            # Sync commands after the bot is connected
            if self.command_manager:
                await self.command_manager.sync_commands()
                logger.info("Slash commands synchronized successfully")
            else:
                logger.error(
                    "Command manager is not initialized, can't sync commands"
                )
        except Exception as e:
            logger.error(f"Error syncing commands: {e}", exc_info=True)
    
    async def close(self) -> None:
        """Close the bot client and all resources."""
        logger.info("Closing bot client and resources")
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
    
    def check_permissions(self, message: Message, cfg: Dict[str, Any] = None) -> bool:
        """
        Check if the user and channel have permission to use the bot.
        
        Args:
            message: The Discord message
            cfg: Optional pre-loaded configuration dictionary
            
        Returns:
            True if the user and channel have permission, False otherwise
        """
        if cfg is None:
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
                role.id in allowed_role_ids 
                for role in getattr(message.author, "roles", [])
            )
        )
        
        if is_bad_channel:
            logger.warning(
                f"Message from {message.author.name} ({message.author.id}) "
                f"in channel {message.channel.id} rejected - channel not allowed"
            )
        
        if is_bad_user:
            logger.warning(
                f"Message from {message.author.name} ({message.author.id}) "
                f"rejected - user not allowed or blocked"
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
        content_without_at_ai = re.sub(
            at_ai_pattern, '', message.content, flags=re.IGNORECASE
        )
        
        # Remove bot mention
        content_without_mentions = (
            content_without_at_ai.replace(self.user.mention, '').lstrip()
        )
        
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
        
        logger.info(
            f"Processing message from {new_msg.author.name} "
            f"({new_msg.author.id}) in channel {new_msg.channel.id}"
        )
        
        # Clean message content
        self.clean_message_content(new_msg)
        
        # Get configuration once
        cfg = get_config()
        
        # Check permissions using the loaded config
        if not self.check_permissions(new_msg, cfg):
            return
        
        allowed_mentions = AllowedMentions.none()
        
        # Send initial progress message
        progress_message = await new_msg.reply(
            "Processing your request...",
            mention_author=False,
            allowed_mentions=allowed_mentions
        )
        
        try:
            # Process the message
            await self._process_message(
                new_msg, 
                progress_message, 
                cfg, 
                allowed_mentions
            )
                
        except Exception as e:
            logger.exception(
                f"Error in on_message handler for message {new_msg.id}: {str(e)}"
            )
            await progress_message.edit(
                content=f"An error occurred while processing your request: {str(e)}",
                allowed_mentions=allowed_mentions
            )
    
    async def _process_message(
        self, 
        new_msg: Message, 
        progress_message: Message,
        cfg: Dict[str, Any],
        allowed_mentions: AllowedMentions
    ) -> None:
        """
        Process a message and generate a response.
        
        Args:
            new_msg: The user's message
            progress_message: The initial progress message
            cfg: Configuration dictionary
            allowed_mentions: Allowed mentions settings
        """
        # Get API key
        api_key = await self.api_key_manager.get_next_api_key(cfg["provider"])
        if not api_key:
            logger.warning(
                f"No API key available for provider '{cfg['provider']}', "
                f"using placeholder"
            )
            api_key = 'sk-no-key-required'
        
        # Calculate message limits
        use_plain_responses = cfg["use_plain_responses"]
        
        # For plain text, Discord has a 2000 character limit
        if use_plain_responses:
            max_message_length = 2000
        else:
            # For embeds, Discord has a 4096 character limit for the description field
            # We let the ResponseHandler dynamically calculate content limits 
            # based on searched_for_text and streaming indicator
            max_message_length = 4096  # This is just a reference value now
        
        # Build conversation context
        logger.info(f"Building conversation context for message {new_msg.id}")
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
            await self._handle_special_command(
                new_msg,
                cmd_type,
                progress_message,
                messages,
                cfg,
                allowed_mentions
            )
        else:
            # Process regular message
            await self._handle_regular_message(
                new_msg,
                progress_message,
                messages,
                cfg,
                max_message_length,
                api_key,
                user_warnings,
                allowed_mentions
            )
        
        # Manage message node cache size
        await self._manage_message_cache()
    
    async def _handle_special_command(
        self,
        new_msg: Message,
        cmd_type: str,
        progress_message: Message,
        messages: List[Dict[str, Any]],
        cfg: Dict[str, Any],
        allowed_mentions: AllowedMentions
    ) -> None:
        """
        Handle special commands like lens and sauce.
        
        Args:
            new_msg: The user's message
            cmd_type: Command type ("lens" or "sauce")
            progress_message: The initial progress message
            messages: List of message objects
            cfg: Configuration dictionary
            allowed_mentions: Allowed mentions settings
        """
        logger.info(f"Handling {cmd_type} command for message {new_msg.id}")
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
            logger.warning(f"Error handling {cmd_type} command: {error}")
            await progress_message.edit(
                content=error, 
                allowed_mentions=allowed_mentions
            )
            return
        
        # Get API key for LLM
        api_key = await self.api_key_manager.get_next_api_key(cfg["provider"])
        if not api_key:
            logger.warning(
                f"No API key available for provider '{cfg['provider']}', "
                f"using placeholder"
            )
            api_key = 'sk-no-key-required'
        
        # Get LLM response for special command
        await self._get_and_process_llm_response(
            new_msg,
            progress_message,
            messages,
            cfg,
            api_key,
            set(),  # No warnings for special commands
            allowed_mentions,
            2000 if cfg["use_plain_responses"] else (4096 - len(STREAMING_INDICATOR)),
            None,  # No serper queries for lens/sauce
            ""  # No searched_for text for lens/sauce
        )
    
    async def _handle_regular_message(
        self,
        new_msg: Message,
        progress_message: Message,
        messages: List[Dict[str, Any]],
        cfg: Dict[str, Any],
        max_message_length: int,
        api_key: str,
        user_warnings: Set[str],
        allowed_mentions: AllowedMentions
    ) -> None:
        """
        Handle regular message (not a special command).
        
        Args:
            new_msg: The user's message
            progress_message: The initial progress message
            messages: List of message objects
            cfg: Configuration dictionary
            max_message_length: Maximum message length
            api_key: API key to use
            user_warnings: Set of user warnings
            allowed_mentions: Allowed mentions settings
        """
        logger.info(f"Handling regular message for message {new_msg.id}")
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
        searched_for_text = ""
        if serper_queries:
            search_queries_text = ', '.join(f'"{q}"' for q in serper_queries)
            searched_for_text = f"Searched for: {search_queries_text}\n\n"
            logger.info(f"Searched for: {search_queries_text}")
        
        # Get and process LLM response
        await self._get_and_process_llm_response(
            new_msg,
            progress_message,
            messages,
            cfg,
            api_key,
            user_warnings,
            allowed_mentions,
            max_message_length,
            serper_queries,
            searched_for_text
        )
    
    async def _get_and_process_llm_response(
        self,
        new_msg: Message,
        progress_message: Message,
        messages: List[Dict[str, Any]],
        cfg: Dict[str, Any],
        api_key: str,
        user_warnings: Set[str],
        allowed_mentions: AllowedMentions,
        max_message_length: int,
        serper_queries: Optional[List[str]],
        searched_for_text: str
    ) -> None:
        """
        Get LLM response and process it.
        
        Args:
            new_msg: The user's message
            progress_message: The initial progress message
            messages: List of message objects
            cfg: Configuration dictionary
            api_key: API key to use
            user_warnings: Set of user warnings
            allowed_mentions: Allowed mentions settings
            max_message_length: Maximum message length
            serper_queries: Search queries (if applicable)
            searched_for_text: Text showing what was searched for
        """
        # Get LLM response
        logger.info(f"Getting LLM completion for message {new_msg.id}")
        success, stream = await LLMService.get_completion(
            messages, cfg, api_key
        )
        
        if not success:
            logger.error(
                "Failed to get LLM completion (likely rate limit exceeded)"
            )
            await progress_message.edit(
                content=(
                    "An error occurred while processing your request "
                    "(rate limit exceeded)."
                ),
                allowed_mentions=allowed_mentions
            )
            return
        
        # Handle the response
        if cfg["use_plain_responses"]:
            # Handle plain text response (non-streaming)
            logger.info(
                f"Handling plain text response for message {new_msg.id}"
            )
            response_msgs = await self._handle_plain_text_response(
                stream,
                progress_message,
                new_msg,
                allowed_mentions,
                max_message_length
            )
        else:
            # Handle streaming response
            logger.info(
                f"Handling streaming response for message {new_msg.id}"
            )
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
        
        # Start background task to fetch images if serper queries exist
        user_msg_node = self.msg_nodes.get(new_msg.id)
        if user_msg_node and user_msg_node.serper_queries:
            logger.info(
                f"Starting background task to fetch images for message {new_msg.id}"
            )
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
    
    async def _handle_plain_text_response(
        self,
        stream: AsyncGenerator[Any, None],
        progress_message: Message,
        new_msg: Message,
        allowed_mentions: AllowedMentions,
        max_message_length: int
    ) -> List[Message]:
        """
        Handle plain text (non-streaming) response.
        
        Args:
            stream: Response stream from the LLM
            progress_message: The initial progress message
            new_msg: The user's message
            allowed_mentions: Allowed mentions settings
            max_message_length: Maximum message length
            
        Returns:
            List of response messages
        """
        # Collect content from the stream
        response_contents = []
        prev_chunk = None
        
        async for curr_chunk in stream:
            prev_content = (
                prev_chunk.choices[0].delta.content
                if (prev_chunk is not None and 
                    prev_chunk.choices[0].delta.content)
                else ""
            )
            curr_content = curr_chunk.choices[0].delta.content or ""
            
            if response_contents or prev_content:
                if (response_contents == [] or 
                        len(response_contents[-1] + prev_content) > max_message_length):
                    response_contents.append("")
                response_contents[-1] += prev_content
            
            prev_chunk = curr_chunk
        
        # Handle the response using the handler
        serper_queries = getattr(
            self.msg_nodes.get(new_msg.id), 'serper_queries', None
        )
        
        return await ResponseHandler.handle_plain_text_response(
            response_contents,
            progress_message,
            new_msg.content,
            self.msg_nodes,
            allowed_mentions,
            new_msg,
            serper_queries
        )
    
    async def _manage_message_cache(self) -> None:
        """
        Manage the message node cache size to prevent memory issues.
        Removes oldest message nodes when the cache exceeds the limit.
        """
        if (num_nodes := len(self.msg_nodes)) > MAX_MESSAGE_NODES:
            logger.info(
                f"Message node cache size ({num_nodes}) exceeds limit "
                f"({MAX_MESSAGE_NODES}), pruning oldest"
            )
            for msg_id in sorted(self.msg_nodes.keys())[
                : num_nodes - MAX_MESSAGE_NODES
            ]:
                async with self.msg_nodes.setdefault(
                    msg_id, MsgNode()
                ).lock:
                    self.msg_nodes.pop(msg_id, None)
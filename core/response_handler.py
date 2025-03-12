"""
Response Handler Module

This module manages the creation and updating of Discord response messages,
handling streaming, edits, and content chunking.
"""

import asyncio
import logging
from datetime import datetime as dt
from typing import Dict, Any, List, Optional, Set, Tuple, AsyncGenerator

import discord
from discord import Message, AllowedMentions

from core.constants import (
    STREAMING_INDICATOR,
    EDIT_DELAY_SECONDS,
    EMBED_COLOR_COMPLETE,
    EMBED_COLOR_INCOMPLETE
)
from core.discord_ui import OutputView
from core.message_node import MsgNode

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class ResponseHandler:
    """
    Handler for Discord response messages.
    
    This class manages creating, updating, and streaming responses to Discord messages.
    """
    
    @staticmethod
    async def create_response_message(
        progress_message: Message,
        embed: discord.Embed,
        view: OutputView,
        allowed_mentions: AllowedMentions,
        msg_nodes: Dict[int, MsgNode],
        new_msg: Message
    ) -> Message:
        """
        Create an initial response message by editing the progress message.
        
        Args:
            progress_message: The initial progress message
            embed: The embed to use
            view: The view to attach
            allowed_mentions: Allowed mentions settings
            msg_nodes: Dictionary of message nodes
            new_msg: The user message being responded to
            
        Returns:
            The created response message
        """
        try:
            logger.info(
                f"Creating initial response message by editing progress "
                f"message {progress_message.id}"
            )
            response_msg = await progress_message.edit(
                content=None,
                embed=embed,
                view=view,
                allowed_mentions=allowed_mentions
            )
            
            msg_nodes[response_msg.id] = MsgNode(
                next_msg=new_msg,
                internet_used=msg_nodes[new_msg.id].internet_used,
            )
            await msg_nodes[response_msg.id].lock.acquire()
            
            return response_msg
        except Exception as e:
            logger.error(f"Error creating response message: {e}", exc_info=True)
            raise
    
    @staticmethod
    async def create_continuation_message(
        prev_msg: Message,
        embed: discord.Embed,
        view: OutputView,
        allowed_mentions: AllowedMentions,
        msg_nodes: Dict[int, MsgNode],
        new_msg: Message
    ) -> Message:
        """
        Create a continuation message (for when response is too long).
        
        Args:
            prev_msg: The previous response message
            embed: The embed to use
            view: The view to attach
            allowed_mentions: Allowed mentions settings
            msg_nodes: Dictionary of message nodes
            new_msg: The user message being responded to
            
        Returns:
            The created continuation message
        """
        try:
            logger.info(
                f"Creating continuation message as reply to message "
                f"{prev_msg.id}"
            )
            response_msg = await prev_msg.reply(
                embed=embed,
                view=view,
                mention_author=False,
                allowed_mentions=allowed_mentions
            )
            
            msg_nodes[response_msg.id] = MsgNode(
                next_msg=new_msg,
                internet_used=msg_nodes[new_msg.id].internet_used,
            )
            await msg_nodes[response_msg.id].lock.acquire()
            
            return response_msg
        except Exception as e:
            logger.error(
                f"Error creating continuation message: {e}", 
                exc_info=True
            )
            raise
    
    @staticmethod
    def prepare_embed(
        content: str,
        user_warnings: Set[str],
        is_complete: bool,
        model_name: str,
        internet_used: bool,
        searched_for_text: str = ""
    ) -> discord.Embed:
        """
        Prepare a Discord embed for a response.
        
        Args:
            content: The text content for the embed
            user_warnings: Set of warning messages to display
            is_complete: Whether the response is complete
            model_name: Name of the model being used
            internet_used: Whether internet search was used
            searched_for_text: Text showing what was searched for (if applicable)
            
        Returns:
            The prepared Discord embed
        """
        # Add streaming indicator for incomplete responses
        content_with_indicator = content
        if not is_complete:
            content_with_indicator += STREAMING_INDICATOR
            
        # Create embed with proper description
        embed_description = searched_for_text + content_with_indicator
        
        embed = discord.Embed(
            description=embed_description,
            color=(
                EMBED_COLOR_COMPLETE if is_complete 
                else EMBED_COLOR_INCOMPLETE
            ),
        )
        
        # Add warnings as fields
        for warning in sorted(user_warnings):
            embed.add_field(name=warning, value="", inline=False)
            
        # Add footer
        # Check if model is grok
        is_grok_model = 'grok' in model_name.lower()
        
        if is_grok_model:
            footer_text = f"Model: {model_name}"
        else:
            footer_text = f"Model: {model_name} | " + (
                "Internet used" if internet_used else "Internet NOT used"
            )
        
        embed.set_footer(text=footer_text)
        
        return embed
    
    @staticmethod
    async def handle_streaming_response(
        stream: AsyncGenerator[Any, None],
        progress_message: Message,
        user_message_content: str,
        user_message_id: int,
        msg_nodes: Dict[int, MsgNode],
        user_warnings: Set[str],
        config: Dict[str, Any],
        allowed_mentions: AllowedMentions,
        new_msg: Message,
        max_message_length: int,
        serper_queries: Optional[List[str]] = None,
        searched_for_text: str = ""
    ) -> List[Message]:
        """
        Handle a streaming response from the LLM.
        
        Args:
            stream: The response stream
            progress_message: The initial progress message
            user_message_content: The user's message content
            user_message_id: The user's message ID
            msg_nodes: Dictionary of message nodes
            user_warnings: Set of user warnings
            config: Configuration dictionary
            allowed_mentions: Allowed mentions settings
            new_msg: The user message
            max_message_length: Maximum message length
            serper_queries: Search queries (if applicable)
            searched_for_text: Text showing what was searched for
            
        Returns:
            List of response messages
        """
        try:
            logger.info(
                f"Handling streaming response for message {user_message_id}"
            )
            response_msgs: List[Message] = []
            response_contents: List[str] = []
            prev_chunk: Any = None
            edit_task: Optional[asyncio.Task] = None
            last_task_time: float = dt.now().timestamp()
            
            # Discord embed limit is 4096 characters - calculate max content length for first message
            # (accounting for searched_for_text and streaming indicator)
            discord_embed_limit = 4096
            first_msg_content_limit = discord_embed_limit - len(searched_for_text) - len(STREAMING_INDICATOR)
            
            # For continuation messages, we don't include searched_for_text
            cont_msg_content_limit = discord_embed_limit - len(STREAMING_INDICATOR)
            
            # Keep track if we've added the searched_for_text
            searched_for_text_added = False
            
            async for curr_chunk in stream:
                prev_content = (
                    prev_chunk.choices[0].delta.content
                    if (prev_chunk is not None and 
                        prev_chunk.choices[0].delta.content)
                    else ""
                )
                curr_content = curr_chunk.choices[0].delta.content or ""
                
                # Process content if we have something to work with
                if response_contents or prev_content:
                    # Check if we need to start a new message
                    if not response_contents:
                        # First message - always create it
                        response_contents.append("")
                        searched_for_text_added = True
                        
                        # Create initial embed for first message
                        initial_embed_description = searched_for_text + STREAMING_INDICATOR
                        
                        initial_embed = discord.Embed(
                            description=initial_embed_description,
                            color=EMBED_COLOR_INCOMPLETE,
                        )
                        
                        for warning in sorted(user_warnings):
                            initial_embed.add_field(name=warning, value="", inline=False)
                        
                        # Check if model is grok
                        is_grok_model = 'grok' in config['model'].lower()
                        if is_grok_model:
                            footer_text = f"Model: {config['model']}"
                        else:
                            footer_text = f"Model: {config['model']} | " + (
                                "Internet used" 
                                if msg_nodes[user_message_id].internet_used 
                                else "Internet NOT used"
                            )
                        initial_embed.set_footer(text=footer_text)
                        
                        view = OutputView(
                            response_contents, user_message_content, serper_queries
                        )
                        
                        # Create first message by editing progress message
                        response_msg = await ResponseHandler.create_response_message(
                            progress_message, initial_embed, view, allowed_mentions, 
                            msg_nodes, new_msg
                        )
                        response_msgs.append(response_msg)
                        last_task_time = dt.now().timestamp()
                        logger.info(f"Created initial response message {response_msg.id}")
                        
                    elif len(response_contents[-1] + prev_content) > (
                            first_msg_content_limit if len(response_contents) == 1 
                            else cont_msg_content_limit
                        ):
                        # Content would exceed Discord limit - start a new message
                        response_contents.append("")
                        
                        # Only proceed if we have at least one message
                        if response_msgs:
                            # Create a new embed for the previous content
                            prev_embed_description = ""
                            if len(response_contents) == 2 and searched_for_text:  # For first message only
                                prev_embed_description = searched_for_text
                            
                            prev_embed_description += response_contents[-2] + STREAMING_INDICATOR
                            
                            prev_embed = discord.Embed(
                                description=prev_embed_description,
                                color=EMBED_COLOR_INCOMPLETE,
                            )
                            
                            for warning in sorted(user_warnings):
                                prev_embed.add_field(name=warning, value="", inline=False)
                            
                            # Check if model is grok
                            is_grok_model = 'grok' in config['model'].lower()
                            if is_grok_model:
                                footer_text = f"Model: {config['model']}"
                            else:
                                footer_text = f"Model: {config['model']} | " + (
                                    "Internet used" 
                                    if msg_nodes[user_message_id].internet_used 
                                    else "Internet NOT used"
                                )
                            prev_embed.set_footer(text=footer_text)
                            
                            view = OutputView(
                                response_contents, user_message_content, serper_queries
                            )
                            
                            # Update the last message before creating a continuation
                            if edit_task is not None and not edit_task.done():
                                await edit_task
                                
                            edit_task = asyncio.create_task(
                                response_msgs[-1].edit(
                                    embed=prev_embed, 
                                    view=view, 
                                    allowed_mentions=allowed_mentions
                                )
                            )
                            await edit_task
                            
                            # Create continuation message
                            continuation_embed = discord.Embed(
                                description=STREAMING_INDICATOR,  # Just indicator initially
                                color=EMBED_COLOR_INCOMPLETE,
                            )
                            
                            for warning in sorted(user_warnings):
                                continuation_embed.add_field(name=warning, value="", inline=False)
                            
                            # Check if model is grok
                            is_grok_model = 'grok' in config['model'].lower()
                            if is_grok_model:
                                footer_text = f"Model: {config['model']}"
                            else:
                                footer_text = f"Model: {config['model']} | " + (
                                    "Internet used" 
                                    if msg_nodes[user_message_id].internet_used 
                                    else "Internet NOT used"
                                )
                            continuation_embed.set_footer(text=footer_text)
                            
                            response_msg = await ResponseHandler.create_continuation_message(
                                response_msgs[-1], continuation_embed, view, allowed_mentions, 
                                msg_nodes, new_msg
                            )
                            response_msgs.append(response_msg)
                            last_task_time = dt.now().timestamp()
                            logger.info(f"Created continuation message {response_msg.id}")
                    
                    # Add content to current message
                    if response_contents:  # Safety check to make sure we have messages
                        response_contents[-1] += prev_content
                    
                    # Check if we need to update the message
                    finish_reason = curr_chunk.choices[0].finish_reason
                    ready_to_edit = (
                        (edit_task is None or edit_task.done())
                        and dt.now().timestamp() - last_task_time >= EDIT_DELAY_SECONDS
                    )
                    
                    # Calculate if we're approaching Discord's limit for this message
                    current_len = len(response_contents[-1] + curr_content) if response_contents else 0
                    limit_for_current_message = (
                        first_msg_content_limit if response_contents and len(response_contents) == 1
                        else cont_msg_content_limit
                    )
                    msg_split_incoming = current_len > limit_for_current_message
                    
                    is_final_edit = finish_reason is not None or msg_split_incoming
                    is_good_finish = (
                        finish_reason is not None and any(
                            finish_reason.lower() == x for x in ("stop", "end_turn")
                        )
                    )
                    
                    # Only attempt to edit if we have at least one message
                    if (ready_to_edit or is_final_edit) and response_msgs:
                        if edit_task is not None and not edit_task.done():
                            await edit_task
                        
                        # Prepare embed description with searched_for_text for first message
                        embed_description = ""
                        if searched_for_text and len(response_msgs) > 0 and response_msgs.index(response_msgs[-1]) == 0:
                            embed_description = searched_for_text
                        
                        # Add the content
                        if response_contents:  # Safety check to ensure we have content
                            embed_description += response_contents[-1]
                        
                        # Add streaming indicator if not final
                        if not is_final_edit:
                            embed_description += STREAMING_INDICATOR
                            
                        # Create embed with appropriate color
                        embed = discord.Embed(
                            description=embed_description,
                            color=(
                                EMBED_COLOR_COMPLETE
                                if msg_split_incoming or is_good_finish
                                else EMBED_COLOR_INCOMPLETE
                            ),
                        )
                        
                        # Add warnings and footer
                        for warning in sorted(user_warnings):
                            embed.add_field(name=warning, value="", inline=False)
                        
                        # Check if model is grok
                        is_grok_model = 'grok' in config['model'].lower()
                        if is_grok_model:
                            footer_text = f"Model: {config['model']}"
                        else:
                            footer_text = f"Model: {config['model']} | " + (
                                "Internet used" 
                                if msg_nodes[user_message_id].internet_used 
                                else "Internet NOT used"
                            )
                        embed.set_footer(text=footer_text)
                        
                        # Create a new view with updated content
                        view = OutputView(
                            response_contents, user_message_content, serper_queries
                        )
                        
                        # Edit the message
                        try:
                            edit_task = asyncio.create_task(
                                response_msgs[-1].edit(
                                    embed=embed, 
                                    view=view, 
                                    allowed_mentions=allowed_mentions
                                )
                            )
                            last_task_time = dt.now().timestamp()
                        except Exception as e:
                            # Avoid nested IndexError in the error handler
                            if response_msgs:
                                logger.error(
                                    f"Error editing message {response_msgs[-1].id}: {e}", 
                                    exc_info=True
                                )
                            else:
                                logger.error(
                                    f"Error editing message (no message ID available): {e}",
                                    exc_info=True
                                )
                
                # Save current chunk for next iteration
                prev_chunk = curr_chunk
            
            # Update message nodes with final text
            for response_msg in response_msgs:
                msg_nodes[response_msg.id].text = "".join(response_contents)
                msg_nodes[response_msg.id].lock.release()
            
            logger.info(
                f"Completed streaming response, created {len(response_msgs)} "
                f"message(s)"
            )
            return response_msgs
            
        except Exception as e:
            logger.error(
                f"Error handling streaming response: {e}", 
                exc_info=True
            )
            # Make sure we properly release any locks
            for response_msg in response_msgs:
                if response_msg.id in msg_nodes:
                    try:
                        msg_nodes[response_msg.id].lock.release()
                    except Exception:
                        pass  # Lock might not be acquired
            raise
    
    @staticmethod
    async def handle_plain_text_response(
        response_contents: List[str],
        progress_message: Message,
        user_message_content: str,
        msg_nodes: Dict[int, MsgNode],
        allowed_mentions: AllowedMentions,
        new_msg: Message,
        serper_queries: Optional[List[str]] = None
    ) -> List[Message]:
        """
        Handle a plain text response (no embeds, not streaming).
        
        Args:
            response_contents: The text contents for the response
            progress_message: The initial progress message
            user_message_content: The user's message content
            msg_nodes: Dictionary of message nodes
            allowed_mentions: Allowed mentions settings
            new_msg: The user message
            serper_queries: Search queries (if applicable)
            
        Returns:
            List of response messages
        """
        try:
            logger.info(f"Handling plain text response for message {new_msg.id}")
            response_msgs: List[Message] = []
            view = OutputView(
                response_contents, user_message_content, serper_queries
            )
            
            for i, content in enumerate(response_contents):
                # Format URLs to prevent embeds
                formatted_content = content
                
                if not response_msgs:
                    # First message - edit the progress message
                    logger.info(
                        f"Creating initial plain text response by editing "
                        f"progress message {progress_message.id}"
                    )
                    response_msg = await progress_message.edit(
                        content=formatted_content,
                        view=view,
                        allowed_mentions=allowed_mentions
                    )
                    msg_nodes[response_msg.id] = MsgNode(next_msg=new_msg)
                    await msg_nodes[response_msg.id].lock.acquire()
                    response_msgs.append(response_msg)
                else:
                    # Continuation message
                    logger.info(
                        f"Creating plain text continuation message as reply "
                        f"to message {response_msgs[-1].id}"
                    )
                    response_msg = await response_msgs[-1].reply(
                        content=formatted_content,
                        view=view,
                        mention_author=False,
                        allowed_mentions=allowed_mentions
                    )
                    msg_nodes[response_msg.id] = MsgNode(next_msg=new_msg)
                    await msg_nodes[response_msg.id].lock.acquire()
                    response_msgs.append(response_msg)
            
            # Update message nodes with final text
            for response_msg in response_msgs:
                msg_nodes[response_msg.id].text = "".join(response_contents)
                msg_nodes[response_msg.id].lock.release()
            
            logger.info(
                f"Completed plain text response, created {len(response_msgs)} "
                f"message(s)"
            )
            return response_msgs
            
        except Exception as e:
            logger.error(
                f"Error handling plain text response: {e}", 
                exc_info=True
            )
            raise
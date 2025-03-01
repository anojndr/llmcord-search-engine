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
        embed_description = searched_for_text + content
        if not is_complete:
            embed_description += STREAMING_INDICATOR
            
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
            searched_for_text_added: bool = False
            
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
                    if (response_contents == [] or 
                            len(response_contents[-1] + prev_content) > max_message_length):
                        response_contents.append("")
                        
                        # Prepare searched_for text for first message only
                        embed_description = ""
                        if not searched_for_text_added and searched_for_text:
                            embed_description = searched_for_text
                            searched_for_text_added = True
                        
                        embed_description += (
                            response_contents[-1] + prev_content + 
                            STREAMING_INDICATOR
                        )
                        
                        embed = discord.Embed(
                            description=embed_description,
                            color=EMBED_COLOR_INCOMPLETE,
                        )
                        
                        for warning in sorted(user_warnings):
                            embed.add_field(name=warning, value="", inline=False)
                        
                        footer_text = f"Model: {config['model']} | " + (
                            "Internet used" 
                            if msg_nodes[user_message_id].internet_used 
                            else "Internet NOT used"
                        )
                        embed.set_footer(text=footer_text)
                        
                        view = OutputView(
                            response_contents, user_message_content, serper_queries
                        )
                        
                        if not response_msgs:
                            # First message - edit the progress message
                            response_msg = await ResponseHandler.create_response_message(
                                progress_message, embed, view, allowed_mentions, 
                                msg_nodes, new_msg
                            )
                            response_msgs.append(response_msg)
                            last_task_time = dt.now().timestamp()
                            logger.info(
                                f"Created initial response message {response_msg.id}"
                            )
                        else:
                            # Continuation message
                            response_msg = await ResponseHandler.create_continuation_message(
                                response_msgs[-1], embed, view, allowed_mentions, 
                                msg_nodes, new_msg
                            )
                            response_msgs.append(response_msg)
                            last_task_time = dt.now().timestamp()
                            logger.info(
                                f"Created continuation message {response_msg.id}"
                            )
                    
                    # Add content to current message
                    response_contents[-1] += prev_content
                    
                    # Check if we need to update the message
                    finish_reason = curr_chunk.choices[0].finish_reason
                    ready_to_edit = (
                        (edit_task is None or edit_task.done())
                        and dt.now().timestamp() - last_task_time >= EDIT_DELAY_SECONDS
                    )
                    msg_split_incoming = (
                        len(response_contents[-1] + curr_content) > max_message_length
                    )
                    is_final_edit = finish_reason is not None or msg_split_incoming
                    is_good_finish = (
                        finish_reason is not None and any(
                            finish_reason.lower() == x for x in ("stop", "end_turn")
                        )
                    )
                    
                    if ready_to_edit or is_final_edit:
                        if edit_task is not None and not edit_task.done():
                            await edit_task
                        
                        # Prepare embed description with searched_for_text for first message
                        embed_description = ""
                        if (searched_for_text and 
                                response_msgs.index(response_msgs[-1]) == 0):
                            embed_description = searched_for_text
                        
                        # Add the content
                        embed_description += (
                            response_contents[-1]
                            if is_final_edit
                            else (response_contents[-1] + STREAMING_INDICATOR)
                        )
                        
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
                        
                        footer_text = f"Model: {config['model']} | " + (
                            "Internet used" 
                            if msg_nodes[user_message_id].internet_used 
                            else "Internet NOT used"
                        )
                        embed.set_footer(text=footer_text)
                        
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
                            logger.error(
                                f"Error editing message {response_msgs[-1].id}: {e}", 
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
                if not response_msgs:
                    # First message - edit the progress message
                    logger.info(
                        f"Creating initial plain text response by editing "
                        f"progress message {progress_message.id}"
                    )
                    response_msg = await progress_message.edit(
                        content=content,
                        view=view,
                        suppress_embeds=True,
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
                        content=content,
                        view=view,
                        suppress_embeds=True,
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
"""
Message Processor Module

This module handles processing of Discord messages, including:
- Extracting content and attachments
- Building conversation context
- Handling special commands (lens, sauce)
- Integrating with search services
"""

import re
import html
import logging
import asyncio
from base64 import b64encode
from datetime import datetime as dt
from typing import Dict, Any, List, Optional, Tuple, Literal
import discord
import httpx
from discord import Message, File, ClientUser

from core.message_node import MsgNode
from config.api_key_manager import APIKeyManager
from llm.rephraser_handler import rephrase_query
from llm.query_splitter_handler import split_query
from search.search_handler import handle_search_queries
from search.url_handler import extract_urls_from_text, fetch_urls_content
from images.google_lens_handler import get_google_lens_results, process_google_lens_results
from images.saucenao_handler import handle_saucenao_query

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

async def process_message_attachments(
    message: Message,
    httpx_client: httpx.AsyncClient,
    allowed_file_types: Tuple[str, ...],
    max_text: int,
    bot_user: ClientUser
) -> Tuple[str, List[Dict[str, Any]], bool]:
    """
    Process attachments in a Discord message.
    
    Args:
        message: Discord message
        httpx_client: HTTP client
        allowed_file_types: Tuple of allowed file types
        max_text: Maximum text length
        bot_user: Bot user object
        
    Returns:
        Tuple containing:
        - Processed text content
        - List of image data
        - Flag indicating if there were unsupported attachments
    """
    good_attachments: Dict[str, List[discord.Attachment]] = {
        type: [
            att
            for att in message.attachments
            if att.content_type and type in att.content_type
        ]
        for type in allowed_file_types
    }
    
    text_content: str = "\n".join(
        ([message.content] if message.content else []) +
        [embed.description for embed in message.embeds if embed.description] +
        [
            f'<text_file name="{html.escape(att.filename)}">\n{html.escape((await httpx_client.get(att.url)).text)}\n</text_file>'
            for att in good_attachments["text"]
        ]
    )
    
    if text_content.startswith(bot_user.mention):
        text_content = text_content.replace(bot_user.mention, "", 1).lstrip()
        
    images: List[Dict[str, Any]] = [
        dict(
            type="image_url",
            image_url=dict(
                url=f"data:{att.content_type};base64,{b64encode((await httpx_client.get(att.url)).content).decode('utf-8')}"
            ),
        )
        for att in good_attachments["image"]
    ]
    
    has_bad_attachments: bool = len(message.attachments) > sum(
        len(att_list) for att_list in good_attachments.values()
    )
    
    return text_content[:max_text], images, has_bad_attachments

async def find_next_message(
    curr_msg: Message,
    bot_user: ClientUser
) -> Optional[Message]:
    """
    Find the next message in a conversation chain.
    
    Args:
        curr_msg: Current Discord message
        bot_user: Bot user object
        
    Returns:
        The next message in the chain or None
    """
    try:
        # Case 1: Back-to-back messages from the same user
        if (
            not curr_msg.reference
            and bot_user.mention not in curr_msg.content
            and (
                prev_msg_in_channel := (
                    [
                        m
                        async for m in curr_msg.channel.history(
                            before=curr_msg, limit=1
                        )
                    ]
                    or [None]
                )[0]
            )
            and any(
                prev_msg_in_channel.type == type
                for type in (
                    discord.MessageType.default,
                    discord.MessageType.reply,
                )
            )
            and prev_msg_in_channel.author
            == (
                bot_user
                if curr_msg.channel.type == discord.ChannelType.private
                else curr_msg.author
            )
        ):
            return prev_msg_in_channel
        else:
            # Case 2: Message in a thread or a reply
            is_public_thread: bool = (
                curr_msg.channel.type == discord.ChannelType.public_thread
            )
            next_is_parent_msg: bool = (
                not curr_msg.reference
                and is_public_thread
                and curr_msg.channel.parent
                and curr_msg.channel.parent.type == discord.ChannelType.text
            )
            next_msg_id: Optional[int] = (
                curr_msg.channel.id
                if next_is_parent_msg
                else getattr(curr_msg.reference, "message_id", None)
            )
            if next_msg_id:
                if next_is_parent_msg:
                    return (
                        curr_msg.channel.starter_message
                        or await curr_msg.channel.parent.fetch_message(
                            next_msg_id
                        )
                    )
                else:
                    return (
                        curr_msg.reference.cached_message
                        or await curr_msg.channel.fetch_message(next_msg_id)
                    )
    except (discord.NotFound, discord.HTTPError, AttributeError):
        logger.exception("Error fetching next message in the chain")
    
    return None

async def build_conversation_context(
    new_msg: Message,
    bot_user: ClientUser,
    msg_nodes: Dict[int, MsgNode],
    config: Dict[str, Any],
    httpx_client: httpx.AsyncClient,
    allowed_file_types: Tuple[str, ...]
) -> Tuple[List[Dict[str, Any]], set[str]]:
    """
    Build conversation context from message chain.
    
    Args:
        new_msg: New Discord message
        bot_user: Bot user object
        msg_nodes: Dictionary of message nodes
        config: Configuration dictionary
        httpx_client: HTTP client
        allowed_file_types: Tuple of allowed file types
        
    Returns:
        Tuple containing:
        - List of messages for LLM context
        - Set of user warnings
    """
    # Determine model capabilities
    accept_images: bool = any(x in config["model"].lower() for x in [
        "gpt-4o", "claude-3", "gemini", "pixtral", "llava", "vision", "vl"
    ])
    accept_usernames: bool = any(x in config["provider"].lower() for x in [
        "openai", "x-ai"
    ])
    
    # Get configuration limits
    max_text: int = config["max_text"]
    max_images: int = config["max_images"] if accept_images else 0
    max_messages: int = config["max_messages"]
    
    messages: List[Dict[str, Any]] = []
    user_warnings: set[str] = set()
    curr_msg: Optional[Message] = new_msg
    
    # Traverse message chain to build context
    while curr_msg is not None and len(messages) < max_messages:
        curr_node: MsgNode = msg_nodes.setdefault(curr_msg.id, MsgNode())
        async with curr_node.lock:
            if curr_node.text is None:
                # Extract message content and attachments
                curr_node.text, curr_node.images, curr_node.has_bad_attachments = await process_message_attachments(
                    curr_msg, httpx_client, allowed_file_types, max_text, bot_user
                )
                
                # Set message role and user ID
                curr_node.role = "assistant" if curr_msg.author == bot_user else "user"
                curr_node.user_id = curr_msg.author.id if curr_node.role == "user" else None
                
                # Find next message in conversation chain
                try:
                    curr_node.next_msg = await find_next_message(curr_msg, bot_user)
                except Exception:
                    curr_node.fetch_next_failed = True
            
            # Format message content for LLM API
            if curr_node.images[:max_images]:
                content: List[Dict[str, Any]] = (
                    ([dict(type="text", text=curr_node.text[:max_text])]
                     if curr_node.text[:max_text]
                     else []) +
                    curr_node.images[:max_images]
                )
            else:
                content: str = curr_node.text[:max_text]
                
            # Add message to context if it has content
            if content != "":
                message: Dict[str, Any] = dict(
                    content=content,
                    role=curr_node.role,
                    timestamp=curr_msg.created_at.strftime("%Y-%m-%d %H:%M:%S.%f%z")
                )
                if accept_usernames and curr_node.user_id is not None:
                    message["name"] = str(curr_node.user_id)
                messages.append(message)
            
            # Add warnings if needed
            if len(curr_node.text) > max_text:
                warning_msg = f"Max text limit exceeded: {len(curr_node.text)} > {max_text} characters in message {curr_msg.id}"
                logger.warning(warning_msg)
                user_warnings.add(f"⚠️ Max {max_text:,} characters per message")
            if len(curr_node.images) > max_images:
                warning_msg = f"Max images limit exceeded: {len(curr_node.images)} > {max_images} in message {curr_msg.id}"
                logger.warning(warning_msg)
                user_warnings.add(
                    f"⚠️ Max {max_images} image{'' if max_images == 1 else 's'} per message"
                    if max_images > 0
                    else "⚠️ Can't see images"
                )
            if curr_node.has_bad_attachments:
                logger.warning(f"Unsupported attachments detected in message {curr_msg.id}")
                user_warnings.add("⚠️ Unsupported attachments")
            if curr_node.fetch_next_failed or (
                curr_node.next_msg is not None and len(messages) == max_messages
            ):
                logger.warning(f"Message chain length limit reached ({max_messages}) for message {curr_msg.id}")
                user_warnings.add(
                    f"⚠️ Only using last {len(messages)} message{'' if len(messages) == 1 else 's'}"
                )
                
            # Move to next message in chain
            curr_msg = curr_node.next_msg

    # Reverse messages for chronological order
    messages = messages[::-1]
    
    # Add system prompt if available
    if system_prompt := config["system_prompt"]:
        system_prompt_extras: List[str] = [f"Today's date: {dt.now().strftime('%B %d, %Y')}."]
        if accept_usernames:
            system_prompt_extras.append(
                "User's names are their Discord IDs and should be typed as '<@ID>'."
            )
        full_system_prompt: str = "\n".join([system_prompt] + system_prompt_extras)
        messages.insert(0, dict(role="system", content=full_system_prompt))
        
    return messages, user_warnings

async def handle_lens_sauce_commands(
    new_msg: Message, 
    cmd_type: Literal["lens", "sauce"],
    msg_nodes: Dict[int, MsgNode], 
    messages: List[Dict[str, Any]],
    api_key_manager: APIKeyManager,
    httpx_client: httpx.AsyncClient,
    config: Dict[str, Any]
) -> Optional[str]:
    """
    Handle lens and sauce commands.
    
    Args:
        new_msg: Discord message
        cmd_type: Command type ('lens' or 'sauce')
        msg_nodes: Dictionary of message nodes
        messages: List of messages for LLM context
        api_key_manager: API key manager instance
        httpx_client: HTTP client
        config: Configuration dictionary
        
    Returns:
        Error message if any, None on success
    """
    if not new_msg.attachments:
        service_name: str = "Google Lens" if cmd_type == "lens" else "SauceNAO"
        error_msg = f"No image attachment for the {service_name} search in message {new_msg.id}"
        logger.warning(error_msg)
        return f"Please attach an image for the {service_name} search."
    
    image_attachment: discord.Attachment = new_msg.attachments[0]
    image_url: str = image_attachment.url
    
    try:
        if cmd_type == "lens":
            logger.info(f"Processing Google Lens search for image in message {new_msg.id}")
            lens_results: Dict[str, Any] = await get_google_lens_results(
                image_url, api_key_manager, httpx_client
            )
            formatted_results: str = await process_google_lens_results(
                lens_results, config, api_key_manager, httpx_client
            )
            results_tag: str = 'lens results'
        else:  # sauce
            logger.info(f"Processing SauceNAO search for image in message {new_msg.id}")
            formatted_results: str = await handle_saucenao_query(
                image_url, api_key_manager, httpx_client
            )
            results_tag: str = 'saucenao results'
    except Exception as e:
        service_name: str = "Google Lens" if cmd_type == "lens" else "SauceNAO"
        error_msg = f"Error calling {service_name} API for message {new_msg.id}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return f"Error calling {service_name} API: {str(e)}"
    
    user_content: str = new_msg.content
    prefix_len: int = len(cmd_type)
    user_message_content: str = user_content[prefix_len:].lstrip()
    
    augmented_user_message: str = (
        f"User Query: {html.escape(user_message_content)}\n\n"
        f"{results_tag.capitalize()}:\n{formatted_results}"
    )
    
    # Update the user message in the context
    for message in reversed(messages):
        if message['role'] == 'user':
            if isinstance(message['content'], list):
                for part in message['content']:
                    if part.get('type') == 'text':
                        part['text'] = augmented_user_message
                        break
                else:
                    message['content'].insert(0, {'type': 'text', 'text': augmented_user_message})
            else:
                message['content'] = augmented_user_message
            break
    
    msg_nodes[new_msg.id].text = augmented_user_message
    msg_nodes[new_msg.id].internet_used = True
    logger.info(f"Successfully processed {cmd_type} command for message {new_msg.id}")
    
    return None

async def handle_regular_message(
    new_msg: Message,
    msg_nodes: Dict[int, MsgNode],
    messages: List[Dict[str, Any]],
    api_key_manager: APIKeyManager,
    httpx_client: httpx.AsyncClient,
    config: Dict[str, Any]
) -> None:
    """
    Handle regular user messages (non-lens, non-sauce).
    
    Args:
        new_msg: Discord message
        msg_nodes: Dictionary of message nodes
        messages: List of messages for LLM context
        api_key_manager: API key manager instance
        httpx_client: HTTP client
        config: Configuration dictionary
    """
    # Check for URLs in the message
    urls_in_message: List[str] = extract_urls_from_text(new_msg.content)
    augmented_user_message: Optional[str] = None
    
    if urls_in_message:
        # Handle URL content extraction
        logger.info(f"Found {len(urls_in_message)} URLs in message {new_msg.id}")
        contents: List[str] = await fetch_urls_content(
            urls_in_message, api_key_manager, httpx_client, config=config
        )
        augmented_user_message = (
            f"User Query: {html.escape(new_msg.content)}\n\n"
            f"URL Results:\n"
        )
        for idx, (url, content) in enumerate(zip(urls_in_message, contents), start=1):
            augmented_user_message += (
                f"Result {idx}:\n"
                f"URL: {html.escape(url)}\n"
                f"Content: {content}\n\n"
            )
    else:
        # Handle web search if needed
        logger.info(f"Checking if web search is needed for message {new_msg.id}")
        latest_user_query: str = await rephrase_query(messages, config, api_key_manager)
        if latest_user_query != 'not_needed':
            logger.info(f"Web search needed for message {new_msg.id}, query: {latest_user_query}")
            split_queries: List[str] = await split_query(latest_user_query, config, api_key_manager)
            msg_nodes[new_msg.id].serper_queries = split_queries
            msg_nodes[new_msg.id].internet_used = True
            logger.info(f"Split into {len(split_queries)} queries: {split_queries}")
            aggregated_results: str = await handle_search_queries(
                split_queries, api_key_manager, httpx_client, config=config
            )
            augmented_user_message = f"User Query: {html.escape(new_msg.content)}\n\n{aggregated_results}"
        else:
            logger.info(f"Web search not needed for message {new_msg.id}")
    
    # Update user message with search results or URL content
    if augmented_user_message:
        for message in reversed(messages):
            if message['role'] == 'user':
                if isinstance(message['content'], list):
                    for part in message['content']:
                        if part.get('type') == 'text':
                            part['text'] = augmented_user_message
                            break
                    else:
                        message['content'].insert(0, {'type': 'text', 'text': augmented_user_message})
                else:
                    message['content'] = augmented_user_message
                break
        msg_nodes[new_msg.id].text = augmented_user_message
        msg_nodes[new_msg.id].internet_used = True
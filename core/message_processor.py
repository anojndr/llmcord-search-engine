"""
Message Processor Module

This module handles processing of Discord messages, including:
- Extracting content and attachments
- Building conversation context
- Handling special commands (lens, sauce)
- Integrating with search services
"""

import asyncio
import html
import logging
import re
from base64 import b64encode
from datetime import datetime as dt
from typing import Dict, Any, List, Optional, Tuple, Literal

import discord
import httpx
from discord import Message, File, ClientUser

from config.api_key_manager import APIKeyManager
from core.message_node import MsgNode
from images.google_lens_handler import (
    get_google_lens_results,
    process_google_lens_results
)
from images.saucenao_handler import handle_saucenao_query
from llm.query_splitter_handler import split_query
from llm.rephraser_handler import rephrase_query
from search.search_handler import handle_search_queries
from search.url_handler import extract_urls_from_text, fetch_urls_content

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


async def process_message_attachments(
    message: Message,
    httpx_client: httpx.AsyncClient,
    allowed_file_types: Tuple[str, ...],
    max_text: int,
    bot_user: ClientUser,
    provider: str = None  # Provider-specific handling parameter
) -> Tuple[str, List[Dict[str, Any]], bool]:
    """
    Process attachments in a Discord message.
    
    Args:
        message: Discord message
        httpx_client: HTTP client
        allowed_file_types: Tuple of allowed file types
        max_text: Maximum text length
        bot_user: Bot user object
        provider: The provider being used (e.g., 'google')
        
    Returns:
        Tuple containing:
        - Processed text content
        - List of image data
        - Flag indicating if there were unsupported attachments
    """
    # Define max file size for Google provider
    MAX_GOOGLE_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB limit
    
    # Define mime types for Google provider
    google_supported_mime_types = {
        'application/pdf': 'pdf',
        'application/x-javascript': 'text/javascript',
        'text/javascript': 'javascript',
        'application/x-python': 'text/x-python',
        'text/x-python': 'python',
        'text/plain': 'txt',
        'text/html': 'html',
        'text/css': 'css',
        'text/md': 'markdown',
        'text/csv': 'csv',
        'text/xml': 'xml',
        'text/rtf': 'rtf',
        'audio/wav': 'audio',
        'audio/mp3': 'audio',
        'audio/aiff': 'audio',
        'audio/aac': 'audio',
        'audio/ogg': 'audio',
        'audio/flac': 'audio'
    }
    
    provider = provider or ""  # Default to empty string if None
    is_google_provider = provider.lower() == 'google'
    
    # Collect attachments by type
    good_attachments: Dict[str, List[discord.Attachment]] = {
        type: [
            att
            for att in message.attachments
            if att.content_type and type in att.content_type
        ]
        for type in allowed_file_types
    }
    
    # Build text content
    text_parts = []
    if message.content:
        text_parts.append(message.content)
    
    for embed in message.embeds:
        if embed.description:
            text_parts.append(embed.description)
    
    # Process text file attachments
    for att in good_attachments.get("text", []):
        try:
            response = await httpx_client.get(att.url)
            text_content = response.text
            text_parts.append(
                f'<text_file name="{html.escape(att.filename)}">\n'
                f'{html.escape(text_content)}\n'
                f'</text_file>'
            )
        except Exception as e:
            logger.error(
                f"Error fetching text from attachment {att.filename}: {e}", 
                exc_info=True
            )
    
    text_content = "\n".join(text_parts)
    
    # Remove bot mention if it starts the message
    if text_content.startswith(bot_user.mention):
        text_content = text_content.replace(bot_user.mention, "", 1).lstrip()
        
    images: List[Dict[str, Any]] = []
    has_bad_attachments: bool = False
    
    # Process attachments based on provider
    if is_google_provider:
        logger.info(f"Processing attachments for Google provider (Gemini)")
        
        for att in message.attachments:
            logger.debug(
                f"Processing attachment: {att.filename}, "
                f"content_type: {att.content_type}, size: {att.size} bytes"
            )
            
            if att.size > MAX_GOOGLE_FILE_SIZE_BYTES:
                logger.warning(
                    f"File too large for Google API: {att.filename} "
                    f"({att.size} bytes)"
                )
                has_bad_attachments = True
                continue
                
            if att.content_type:
                # Handle image attachment
                if "image" in att.content_type:
                    logger.debug(f"Adding image attachment: {att.filename}")
                    try:
                        response = await httpx_client.get(att.url)
                        image_data = response.content
                        images.append(
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": (
                                        f"data:{att.content_type};base64,"
                                        f"{b64encode(image_data).decode('utf-8')}"
                                    )
                                },
                            }
                        )
                    except Exception as e:
                        logger.error(
                            f"Error downloading image {att.filename}: {e}", 
                            exc_info=True
                        )
                        has_bad_attachments = True
                
                # Handle supported file types for Google Gemini
                elif any(
                    mime_type in att.content_type 
                    for mime_type in google_supported_mime_types
                ):
                    logger.debug(
                        f"Adding file attachment as data URL: {att.filename}"
                    )
                    try:
                        response = await httpx_client.get(att.url)
                        content = response.content
                        
                        # Use original mime type or normalize it if needed
                        mime_type = att.content_type
                        if (mime_type in google_supported_mime_types and
                                isinstance(google_supported_mime_types[mime_type], str) and
                                '/' in google_supported_mime_types[mime_type]):
                            mime_type = google_supported_mime_types[mime_type]
                        
                        images.append(
                            {
                                "type": "image_url",  # LiteLLM uses image_url for all files
                                "image_url": {
                                    "url": (
                                        f"data:{mime_type};base64,"
                                        f"{b64encode(content).decode('utf-8')}"
                                    )
                                },
                            }
                        )
                    except Exception as e:
                        logger.error(
                            f"Error downloading file {att.filename}: {e}", 
                            exc_info=True
                        )
                        has_bad_attachments = True
                else:
                    logger.warning(
                        f"Unsupported file type for Google API: {att.filename} "
                        f"(content type: {att.content_type})"
                    )
                    has_bad_attachments = True
    else:
        # Original behavior for other providers - only handle images
        logger.debug(f"Processing images for non-Google provider: {provider}")
        for att in good_attachments.get("image", []):
            try:
                response = await httpx_client.get(att.url)
                image_data = response.content
                images.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": (
                                f"data:{att.content_type};base64,"
                                f"{b64encode(image_data).decode('utf-8')}"
                            )
                        },
                    }
                )
            except Exception as e:
                logger.error(
                    f"Error downloading image {att.filename}: {e}", 
                    exc_info=True
                )
                has_bad_attachments = True
        
        # Calculate has_bad_attachments for non-Google providers
        if len(message.attachments) > sum(
            len(att_list) for att_list in good_attachments.values()
        ):
            has_bad_attachments = True
    
    logger.info(
        f"Processed {len(images)} attachments, "
        f"has_bad_attachments={has_bad_attachments}"
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
        # Handle replies - only process reference messages when it's an explicit reply
        if curr_msg.reference:
            next_msg_id = getattr(curr_msg.reference, "message_id", None)
            if next_msg_id:
                return (
                    curr_msg.reference.cached_message
                    or await curr_msg.channel.fetch_message(next_msg_id)
                )
                
        # Handle thread parent messages
        is_public_thread = (
            curr_msg.channel.type == discord.ChannelType.public_thread
        )
        if (not curr_msg.reference
            and is_public_thread
            and curr_msg.channel.parent
            and curr_msg.channel.parent.type == discord.ChannelType.text):
            
            return (
                curr_msg.channel.starter_message
                or await curr_msg.channel.parent.fetch_message(
                    curr_msg.channel.id
                )
            )
            
        # No longer fetching consecutive messages from the same user
        # This ensures only the latest message is processed
    except (discord.NotFound, discord.HTTPError, AttributeError) as e:
        logger.error(
            f"Error fetching next message in the chain: {e}", 
            exc_info=True
        )
    
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
    # Get provider from config
    provider: str = config["provider"]
    
    # Determine model capabilities
    accept_images: bool = any(
        x in config["model"].lower() for x in [
            "gpt-4o", "claude-3", "gemini", "pixtral", 
            "llava", "vision", "vl", "grok"
        ]
    )
    accept_usernames: bool = any(
        x in provider.lower() for x in ["openai"]
    )
    
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
                # Extract message content and attachments, passing provider
                (
                    curr_node.text, 
                    curr_node.images, 
                    curr_node.has_bad_attachments
                ) = await process_message_attachments(
                    curr_msg, 
                    httpx_client, 
                    allowed_file_types, 
                    max_text, 
                    bot_user, 
                    provider
                )
                
                # Set message role and user ID
                curr_node.role = (
                    "assistant" if curr_msg.author == bot_user else "user"
                )
                curr_node.user_id = (
                    curr_msg.author.id if curr_node.role == "user" else None
                )
                
                # Find next message in conversation chain
                try:
                    curr_node.next_msg = await find_next_message(
                        curr_msg, bot_user
                    )
                except Exception as e:
                    logger.error(
                        f"Error finding next message: {e}", 
                        exc_info=True
                    )
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
                    timestamp=curr_msg.created_at.strftime(
                        "%Y-%m-%d %H:%M:%S.%f%z"
                    )
                )
                if accept_usernames and curr_node.user_id is not None:
                    message["name"] = str(curr_node.user_id)
                messages.append(message)
            
            # Add warnings if needed
            if len(curr_node.text) > max_text:
                warning_msg = (
                    f"Max text limit exceeded: {len(curr_node.text)} > "
                    f"{max_text} characters in message {curr_msg.id}"
                )
                logger.warning(warning_msg)
                user_warnings.add(
                    f"⚠️ Max {max_text:,} characters per message"
                )
            if len(curr_node.images) > max_images:
                warning_msg = (
                    f"Max images limit exceeded: {len(curr_node.images)} > "
                    f"{max_images} in message {curr_msg.id}"
                )
                logger.warning(warning_msg)
                user_warnings.add(
                    f"⚠️ Max {max_images} "
                    f"image{'' if max_images == 1 else 's'} per message"
                    if max_images > 0
                    else "⚠️ Can't see images"
                )
            if curr_node.has_bad_attachments:
                logger.warning(
                    f"Unsupported attachments detected in message {curr_msg.id}"
                )
                user_warnings.add("⚠️ Unsupported attachments")
            if curr_node.fetch_next_failed or (
                curr_node.next_msg is not None and len(messages) == max_messages
            ):
                logger.warning(
                    f"Message chain length limit reached ({max_messages}) "
                    f"for message {curr_msg.id}"
                )
                user_warnings.add(
                    f"⚠️ Only using last {len(messages)} "
                    f"message{'' if len(messages) == 1 else 's'}"
                )
                
            # Move to next message in chain
            curr_msg = curr_node.next_msg

    # Reverse messages for chronological order
    messages = messages[::-1]
    
    # Add system prompt if available and model is not grok
    if system_prompt := config["system_prompt"]:
        # Check if the model is grok
        model = config["model"].lower()
        if "grok" not in model:
            system_prompt_extras: List[str] = [
                f"Today's date: {dt.now().strftime('%B %d, %Y')}."
            ]
            if accept_usernames:
                system_prompt_extras.append(
                    "User's names are their Discord IDs and should be typed as '<@ID>'."
                )
            full_system_prompt: str = "\n".join(
                [system_prompt] + system_prompt_extras
            )
            messages.insert(0, dict(role="system", content=full_system_prompt))
        else:
            logger.info(f"Model '{model}' is grok, not sending system prompt")
        
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
        service_name = "Google Lens" if cmd_type == "lens" else "SauceNAO"
        error_msg = (
            f"No image attachment for the {service_name} search in "
            f"message {new_msg.id}"
        )
        logger.warning(error_msg)
        return f"Please attach an image for the {service_name} search."
    
    image_attachment = new_msg.attachments[0]
    image_url = image_attachment.url
    
    try:
        if cmd_type == "lens":
            logger.info(
                f"Processing Google Lens search for image in message {new_msg.id}"
            )
            lens_results = await get_google_lens_results(
                image_url, api_key_manager, httpx_client
            )
            formatted_results = await process_google_lens_results(
                lens_results, config, api_key_manager, httpx_client
            )
            results_tag = 'lens results'
        else:  # sauce
            logger.info(
                f"Processing SauceNAO search for image in message {new_msg.id}"
            )
            formatted_results = await handle_saucenao_query(
                image_url, api_key_manager, httpx_client
            )
            results_tag = 'saucenao results'
    except Exception as e:
        service_name = "Google Lens" if cmd_type == "lens" else "SauceNAO"
        error_msg = (
            f"Error calling {service_name} API for message {new_msg.id}: "
            f"{str(e)}"
        )
        logger.error(error_msg, exc_info=True)
        return f"Error calling {service_name} API: {str(e)}"
    
    user_content = new_msg.content
    prefix_len = len(cmd_type)
    user_message_content = user_content[prefix_len:].lstrip()
    
    augmented_user_message = (
        f"User Query: {html.escape(user_message_content)}\n\n"
        f"{results_tag.capitalize()}:\n{formatted_results}"
    )
    
    # Update the user message in the context
    _update_user_message_content(messages, augmented_user_message)
    
    msg_nodes[new_msg.id].text = augmented_user_message
    msg_nodes[new_msg.id].internet_used = True
    logger.info(
        f"Successfully processed {cmd_type} command for message {new_msg.id}"
    )
    
    return None


def _update_user_message_content(
    messages: List[Dict[str, Any]], 
    new_content: str
) -> None:
    """
    Update the user message content in the messages list.
    
    Args:
        messages: List of message objects
        new_content: New content to set
    """
    for message in reversed(messages):
        if message['role'] == 'user':
            if isinstance(message['content'], list):
                for part in message['content']:
                    if part.get('type') == 'text':
                        part['text'] = new_content
                        break
                else:
                    message['content'].insert(
                        0, {'type': 'text', 'text': new_content}
                    )
            else:
                message['content'] = new_content
            break


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
    urls_in_message = extract_urls_from_text(new_msg.content)
    augmented_user_message = None
    
    if urls_in_message:
        # Handle URL content extraction
        await _handle_urls_in_message(
            new_msg,
            msg_nodes,
            messages,
            urls_in_message,
            api_key_manager,
            httpx_client,
            config
        )
    else:
        # Handle web search if needed
        await _handle_web_search(
            new_msg,
            msg_nodes,
            messages,
            api_key_manager,
            httpx_client,
            config
        )


async def _handle_urls_in_message(
    new_msg: Message,
    msg_nodes: Dict[int, MsgNode],
    messages: List[Dict[str, Any]],
    urls_in_message: List[str],
    api_key_manager: APIKeyManager,
    httpx_client: httpx.AsyncClient,
    config: Dict[str, Any]
) -> None:
    """
    Handle URLs found in a message.
    
    Args:
        new_msg: Discord message
        msg_nodes: Dictionary of message nodes
        messages: List of messages for LLM context
        urls_in_message: List of URLs found in the message
        api_key_manager: API key manager instance
        httpx_client: HTTP client
        config: Configuration dictionary
    """
    logger.info(
        f"Found {len(urls_in_message)} URLs in message {new_msg.id}"
    )
    
    # Fetch all URL contents
    contents = await fetch_urls_content(
        urls_in_message, api_key_manager, httpx_client, config=config
    )
    
    # Use the new consistent format for all URL types
    if len(urls_in_message) == 1:
        # Handle single URL case with the new format
        content_type = "web"
        url = urls_in_message[0]
        content = contents[0]
        
        # Determine content type based on URL
        if 'youtube.com' in url or 'youtu.be' in url:
            content_type = "youtube"
        elif 'reddit.com' in url or 'redd.it' in url:
            content_type = "reddit"
            # Remove the "Reddit Content:" prefix if present
            if content.startswith("Reddit Content:\n"):
                content = content.replace("Reddit Content:\n", "", 1)
        
        # Format as per the requested format
        augmented_user_message = (
            f"answer the user query based on the {content_type} content. don't generate images.\n\n"
            f"user query:\n{html.escape(new_msg.content)}\n\n"
            f"{content_type} content:\n{content}"
        )
    else:
        # Multiple URLs - use the same format but combine all URL content
        augmented_user_message = (
            f"answer the user query based on the web content. don't generate images.\n\n"
            f"user query:\n{html.escape(new_msg.content)}\n\n"
            f"web content:\n"
        )
        
        for idx, (url, content) in enumerate(
            zip(urls_in_message, contents), start=1
        ):
            # Determine content type based on URL
            content_type = "Web"
            if 'youtube.com' in url or 'youtu.be' in url:
                content_type = "YouTube"
            elif 'reddit.com' in url or 'redd.it' in url:
                content_type = "Reddit"
                # Remove the "Reddit Content:" prefix if present
                if content.startswith("Reddit Content:\n"):
                    content = content.replace("Reddit Content:\n", "", 1)
                    
            augmented_user_message += (
                f"Source {idx} ({content_type}):\n"
                f"URL: {html.escape(url)}\n"
                f"{content}\n\n"
            )
    
    # Update the user message
    _update_user_message_content(messages, augmented_user_message)
    msg_nodes[new_msg.id].text = augmented_user_message
    msg_nodes[new_msg.id].internet_used = True


async def _handle_web_search(
    new_msg: Message,
    msg_nodes: Dict[int, MsgNode],
    messages: List[Dict[str, Any]],
    api_key_manager: APIKeyManager,
    httpx_client: httpx.AsyncClient,
    config: Dict[str, Any]
) -> None:
    """
    Handle web search for a message if needed.
    
    Args:
        new_msg: Discord message
        msg_nodes: Dictionary of message nodes
        messages: List of messages for LLM context
        api_key_manager: API key manager instance
        httpx_client: HTTP client
        config: Configuration dictionary
    """
    logger.info(f"Checking if web search is needed for message {new_msg.id}")
    latest_user_query = await rephrase_query(
        messages, config, api_key_manager
    )
    
    if latest_user_query != 'not_needed':
        logger.info(
            f"Web search needed for message {new_msg.id}, "
            f"query: {latest_user_query}"
        )
        split_queries = await split_query(
            latest_user_query, config, api_key_manager
        )
        msg_nodes[new_msg.id].serper_queries = split_queries
        msg_nodes[new_msg.id].internet_used = True
        logger.info(
            f"Split into {len(split_queries)} queries: {split_queries}"
        )
        
        aggregated_results = await handle_search_queries(
            split_queries, api_key_manager, httpx_client, config=config
        )
        
        augmented_user_message = (
            f"answer the user query based on the aggregated search results. don't generate images.\n\n"
            f"user query:\n{html.escape(new_msg.content)}\n\n"
            f"{aggregated_results}"
        )
        
        # Update the user message
        _update_user_message_content(messages, augmented_user_message)
        msg_nodes[new_msg.id].text = augmented_user_message
    else:
        logger.info(f"Web search not needed for message {new_msg.id}")
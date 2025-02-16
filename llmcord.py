"""
llmcord Main Application

This is the entry point for the LLM-based Discord bot. The bot processes messages,
manages conversations, integrates web search, image processing, YouTube/Reddit content extraction,
and finally communicates with various large language models (LLMs) for responses.

The code includes detailed logic for message chaining, retry loops for streaming API responses,
and configuration-based behavior.
"""

import os
import asyncio
import re
from base64 import b64encode
from dataclasses import dataclass, field
from datetime import datetime as dt
import json
import logging
from typing import Literal, Optional
import discord
import httpx
from litellm import acompletion as litellm_acompletion
from dotenv import load_dotenv
import html

# Import all handler modules for search, URL extraction, rephrasing and query splitting.
from search_handler import handle_search_query
from url_handler import extract_urls_from_text, fetch_urls_content
from rephraser_handler import rephrase_query
from query_splitter_handler import split_query
from google_lens_handler import get_google_lens_results, process_google_lens_results
from saucenao_handler import handle_saucenao_query
from searxng_image_handler import fetch_images

from discord.ui import View, Button, TextInput
from discord import File
import io

from api_key_manager import APIKeyManager

from keep_alive import keep_alive

# Set up logging configuration for the application.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)

# Start the keep-alive HTTP server in a separate thread.
keep_alive()

# Constants defining which models support image (vision) inputs.
VISION_MODEL_TAGS = (
    "gpt-4o",
    "claude-3",
    "gemini",
    "pixtral", 
    "llava",
    "vision",
    "vl",
)
# Providers that support including usernames in the messages.
PROVIDERS_SUPPORTING_USERNAMES = ("openai", "x-ai")

ALLOWED_FILE_TYPES = ("image", "text")

# Embed colors for Discord messages.
EMBED_COLOR_COMPLETE = discord.Color.dark_green()
EMBED_COLOR_INCOMPLETE = discord.Color.orange()

# Indicator appended to streaming responses.
STREAMING_INDICATOR = " ⚪"
EDIT_DELAY_SECONDS = 1

MAX_MESSAGE_NODES = 100

# Load environment variables from .env file.
load_dotenv()

async def fetch_images_and_update_views(split_queries, user_msg_id, response_msgs, api_key_manager, httpx_client):
    """
    Background task to fetch images asynchronously and update response messages.
    
    Args:
        split_queries (list): List of search query strings.
        user_msg_id (str or int): The unique ID of the user’s message.
        response_msgs (list): Discord messages to edit with image content.
        api_key_manager: API key manager helper.
        httpx_client (httpx.AsyncClient): HTTP client.
    """
    try:
        image_files_dict, image_urls_dict = await fetch_images(split_queries, 5, api_key_manager, httpx_client)
        
        async with msg_nodes[user_msg_id].lock:
            msg_nodes[user_msg_id].image_files = image_files_dict
            msg_nodes[user_msg_id].image_urls = image_urls_dict
        
        for response_msg in response_msgs:
            new_view = OutputView(
                contents=msg_nodes[response_msg.id].text,
                query=msg_nodes[user_msg_id].text,
                serper_queries=split_queries,
                image_files=image_files_dict,
                image_urls=image_urls_dict
            )
            await response_msg.edit(view=new_view)
    except Exception as e:
        logging.error(f"Error in image fetch background task: {e}")

class ImageCountModal(discord.ui.Modal, title="Select Number of Images"):
    def __init__(self, parent_view):
        """
        Initialize the modal that asks the user for the number of images.
        
        Args:
            parent_view (discord.ui.View): The parent view to update when the modal is submitted.
        """
        super().__init__()
        self.parent_view = parent_view
        
        self.image_count = TextInput(
            label="Number of images per query",
            placeholder="Enter a number between 1 and 5",
            default="1",
            min_length=1,
            max_length=1,
            required=True
        )
        self.add_item(self.image_count)

    async def on_submit(self, interaction: discord.Interaction):
        """
        Called when the user submits their image count input.
        """
        try:
            count = int(self.image_count.value)
            if 1 <= count <= 5:
                await self.parent_view.show_images(interaction, count)
            else:
                await interaction.response.send_message(
                    "Please enter a number between 1 and 5.",
                    ephemeral=True
                )
        except ValueError:
            await interaction.response.send_message(
                "Please enter a valid number between 1 and 5.",
                ephemeral=True
            )

class OutputView(discord.ui.View):
    def __init__(self, contents, query, serper_queries=None, image_files=None, image_urls=None):
        """
        Initialize the Output view used to display message content and buttons.

        Args:
            contents: The text content for the output.
            query: Original user query.
            serper_queries (list, optional): List of queries used for image search.
            image_files (dict, optional): Mapping of queries to Discord File objects.
            image_urls (dict, optional): Mapping of queries to URLs that failed to download.
        """
        super().__init__(timeout=None)
        self.contents = contents
        self.query = query
        self.serper_queries = serper_queries
        self.image_files = image_files or {}
        self.image_urls = image_urls or {}

        # Add a button to download output text as a file.
        self.add_text_file_button()
        # Add a button to show images if available.
        if self.serper_queries and (self.image_files or self.image_urls):
            self.add_show_images_button()

    def add_text_file_button(self):
        """Add a button that triggers sending the text output as a file."""
        text_file_button = Button(
            label="Get Output as Text File",
            style=discord.ButtonStyle.primary,
            custom_id="text_file"
        )
        text_file_button.callback = self.text_file_button_callback
        self.add_item(text_file_button)

    def add_show_images_button(self):
        """Add a button that triggers showing images."""
        show_images_button = Button(
            label="Show Images",
            style=discord.ButtonStyle.secondary,
            custom_id="show_images"
        )
        show_images_button.callback = self.show_images_button_callback
        self.add_item(show_images_button)

    async def text_file_button_callback(self, interaction: discord.Interaction):
        """
        Callback that sends the text output as a text file.
        """
        await self.send_text_file(interaction)
        for item in self.children:
            if item.custom_id == "text_file":
                item.disabled = True
                break
        await interaction.message.edit(view=self)

    async def show_images_button_callback(self, interaction: discord.Interaction):
        """
        Callback that opens a modal to let the user choose how many images to display.
        """
        total_images = sum(len(files) for files in self.image_files.values()) + \
                      sum(len(urls) for urls in self.image_urls.values())
                      
        if total_images == 0:
            await interaction.response.send_message("No images found.", ephemeral=True)
            return

        modal = ImageCountModal(self)
        await interaction.response.send_modal(modal)
        for item in self.children:
            if item.custom_id == "show_images":
                item.disabled = True
                break
        await interaction.message.edit(view=self)

    async def send_text_file(self, interaction: discord.Interaction):
        """
        Compile the full content into a file and send it.
        """
        full_content = "".join(self.contents)
        file = io.StringIO(full_content)
        await interaction.response.send_message(
            content="Here is the output as a text file:",
            file=File(file, filename="output.txt"),
            ephemeral=True
        )

    async def show_images(self, interaction: discord.Interaction, selected_count: int):
        """
        Based on the selected count, send the images or error messages.

        Args:
            selected_count (int): The number of images to display per query.
        """
        await interaction.response.defer()

        if len(self.image_files) == 1 and not self.serper_queries:
            query = next(iter(self.image_files))
            files = self.image_files[query][:selected_count] if self.image_files[query] else []
            urls = self.image_urls[query][:selected_count] if query in self.image_urls else []

            if not files and not urls:
                await interaction.followup.send("No images available.", ephemeral=True)
                return

            message_content = f"Here are {len(files) + len(urls)} images:"
            if urls:
                message_content += "\n\nFailed to download the following images (sent as URLs):\n" + "\n".join(urls)

            await interaction.followup.send(content=message_content, files=files)
        else:
            for i, query in enumerate(self.image_files.keys(), 1):
                files = self.image_files[query][:selected_count] if query in self.image_files else []
                urls = self.image_urls[query][:selected_count] if query in self.image_urls else []

                if not files and not urls:
                    continue

                message_content = f"Images for query {i}: '{query}' ({len(files) + len(urls)} images)"
                if urls:
                    message_content += "\n\nFailed to download the following images (sent as URLs):\n" + "\n".join(urls)

                await interaction.followup.send(content=message_content, files=files)

@dataclass
class MsgNode:
    """
    Data class representing a node in the conversation chain.
    
    Attributes:
        text (str): The text content of the message.
        images (list): List of attached image data.
        role (str): Either "user" or "assistant".
        user_id (int): ID of the user who sent the message.
        next_msg (discord.Message): The next message in the chain.
        has_bad_attachments (bool): Indicator of unsupported attachments.
        fetch_next_failed (bool): Indicates if fetching the next message failed.
        lock (asyncio.Lock): Lock for synchronizing concurrent access.
        serper_queries (list): List of search queries from splitting.
        image_files (list): List of Discord File objects for images.
        image_urls (list): List of image URLs that failed to download.
        internet_used (bool): Whether internet searches were used to augment the message.
    """
    text: Optional[str] = None
    images: list = field(default_factory=list)
    role: Literal["user", "assistant"] = "assistant"
    user_id: Optional[int] = None
    next_msg: Optional[discord.Message] = None
    has_bad_attachments: bool = False
    fetch_next_failed: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    serper_queries: Optional[list] = None
    image_files: Optional[list] = None
    image_urls: Optional[list] = None
    internet_used: bool = False

def get_config():
    """
    Load and return configuration options from environment variables and the system_prompt.txt file.
    
    Returns:
        dict: A dictionary of configuration settings.
    """
    try:
        with open('system_prompt.txt', 'r', encoding='utf-8') as f:
            system_prompt = f.read()
    except FileNotFoundError:
        system_prompt = ("You are a helpful assistant. Cite the most relevant search results as needed to answer the "
                         "question, avoiding irrelevant ones. Write only the response and use markdown for formatting. "
                         "Include a clickable hyperlink at the end of the corresponding sentence, using the name of the site "
                         "as the link text (e.g., [Wikipedia](https://example.com) or [ResearchGate](https://example.com)).")

    config = {
        "bot_token": os.getenv("BOT_TOKEN"),
        "client_id": os.getenv("CLIENT_ID"),
        "status_message": os.getenv("STATUS_MESSAGE"),
        "allow_dms": os.getenv("ALLOW_DMS", "true").lower() == "true",
        "allowed_channel_ids": list(map(int, os.getenv("ALLOWED_CHANNEL_IDS", "").split(","))) if os.getenv("ALLOWED_CHANNEL_IDS") else [],
        "allowed_role_ids": list(map(int, os.getenv("ALLOWED_ROLE_IDS", "").split(","))) if os.getenv("ALLOWED_ROLE_IDS") else [],
        "blocked_user_ids": list(map(int, os.getenv("BLOCKED_USER_IDS", "").split(","))) if os.getenv("BLOCKED_USER_IDS") else [],
        "max_text": int(os.getenv("MAX_TEXT", "100000")),
        "max_images": int(os.getenv("MAX_IMAGES", "5")),
        "max_messages": int(os.getenv("MAX_MESSAGES", "25")),
        "use_plain_responses": os.getenv("USE_PLAIN_RESPONSES", "false").lower() == "true",
        "providers": {
            "openai": {
                "api_keys": os.getenv("OPENAI_API_KEYS", "").split(","),
            },
            "x-ai": {
                "api_keys": os.getenv("XAI_API_KEYS", "").split(","),
            },
            "google": {
                "api_keys": os.getenv("GOOGLE_API_KEYS", "").split(","),
            },
            "mistral": {
                "api_keys": os.getenv("MISTRAL_API_KEYS", "").split(","),
            },
            "groq": {
                "api_keys": os.getenv("GROQ_API_KEYS", "").split(","),
            },
            "openrouter": {
                "api_keys": os.getenv("OPENROUTER_API_KEYS", "").split(","),
            },
            "claude": {
                "api_keys": os.getenv("CLAUDE_API_KEYS", "").split(","),
            },
            "openrouter": {
                "api_keys": os.getenv("OPENROUTER_API_KEYS", "").split(","),
            },
        },
        "provider": os.getenv("PROVIDER", "openai"),
        "model": os.getenv("MODEL", "gpt-4"),
        "extra_api_parameters": {
            "temperature": float(os.getenv("EXTRA_API_PARAMETERS_TEMPERATURE", "1")),
            "top_p": float(os.getenv("EXTRA_API_PARAMETERS_TOP_P", "1")),
        },
        "rephraser_provider": os.getenv("REPHRASER_PROVIDER", "openai"),
        "rephraser_model": os.getenv("REPHRASER_MODEL", "gpt-4"),
        "rephraser_extra_api_parameters": {
            "temperature": float(os.getenv("REPHRASER_EXTRA_API_PARAMETERS_TEMPERATURE", "1")),
            "top_p": float(os.getenv("REPHRASER_EXTRA_API_PARAMETERS_TOP_P", "1")),
        },
        "query_splitter_provider": os.getenv("QUERY_SPLITTER_PROVIDER", "openai"),
        "query_splitter_model": os.getenv("QUERY_SPLITTER_MODEL", "gpt-4"),
        "query_splitter_extra_api_parameters": {
            "temperature": float(os.getenv("QUERY_SPLITTER_EXTRA_API_PARAMETERS_TEMPERATURE", "1")),
            "top_p": float(os.getenv("QUERY_SPLITTER_EXTRA_API_PARAMETERS_TOP_P", "1")),
        },
        "system_prompt": system_prompt,
        "serper_api_keys": os.getenv("SERPER_API_KEYS", "").split(","),
        "serpapi_api_keys": os.getenv("SERPAPI_API_KEYS", "").split(","),
        "youtube_api_keys": os.getenv("YOUTUBE_API_KEYS", "").split(","),
        "saucenao_api_key": os.getenv("SAUCENAO_API_KEY", ""),
        "max_urls": int(os.getenv("MAX_URLS", "5")),
    }
    return config

# Load configuration and instantiate the API key manager.
cfg = get_config()
api_key_manager = APIKeyManager(cfg)

if client_id := cfg["client_id"]:
    logging.info(
        f"\n\nBOT INVITE URL:\nhttps://discord.com/api/oauth2/authorize?client_id={client_id}&permissions=412317273088&scope=bot\n"
    )

# Initialize Discord client and activity.
intents = discord.Intents.default()
intents.message_content = True
activity = discord.Game(
    name=(cfg["status_message"] or "https://github.com/anojndr/llmcord-search-engine")[:128]
)
discord_client = discord.Client(intents=intents, activity=activity)

# Create an HTTPX AsyncClient instance for all HTTP requests.
httpx_client = httpx.AsyncClient(http2=True)

# Global dictionary to store conversation nodes.
msg_nodes = {}
last_task_time = None

def truncate_base64(base64_string, max_length=50):
    """Truncate a base64 string for logging purposes to avoid extremely long logs."""
    if len(base64_string) > max_length:
        return base64_string[:max_length] + "..."
    return base64_string

@discord_client.event
async def on_message(new_msg):
    """
    Discord event handler called when a new message is received.
    This handler:
      - Validates if the message is meant for the bot.
      - Processes attachments and text.
      - Augments the conversation using search APIs when needed.
      - Invokes the chosen LLM with the assembled prompt.
      - Streams the results back into Discord messages.
    """
    global msg_nodes, last_task_time, httpx_client

    is_dm = new_msg.channel.type == discord.ChannelType.private

    # Pattern to ignore if someone types "at ai" in text.
    at_ai_pattern = r'\bat ai\b'

    if (
        not is_dm
        and not re.search(at_ai_pattern, new_msg.content, re.IGNORECASE)
        and discord_client.user not in new_msg.mentions
    ) or new_msg.author.bot:
        return

    # Remove bot-mention text and leading whitespace.
    content_without_at_ai = re.sub(at_ai_pattern, '', new_msg.content, flags=re.IGNORECASE)
    content_without_mentions = content_without_at_ai.replace(discord_client.user.mention, '').lstrip()
    new_msg.content = content_without_mentions

    # Reload configuration in case of hot reloading.
    cfg = get_config()

    allow_dms = cfg["allow_dms"]
    allowed_channel_ids = cfg["allowed_channel_ids"]
    allowed_role_ids = cfg["allowed_role_ids"]
    blocked_user_ids = cfg["blocked_user_ids"]

    # Gather channel identifiers to enforce channel/role restrictions.
    channel_ids = tuple(
        id
        for id in (
            new_msg.channel.id,
            getattr(new_msg.channel, "parent_id", None),
            getattr(new_msg.channel, "category_id", None),
        )
        if id
    )

    is_bad_channel = (is_dm and not allow_dms) or (
        not is_dm
        and allowed_channel_ids
        and not any(id in allowed_channel_ids for id in channel_ids)
    )
    is_bad_user = new_msg.author.id in blocked_user_ids or (
        allowed_role_ids
        and not any(
            role.id in allowed_role_ids for role in getattr(new_msg.author, "roles", [])
        )
    )

    if is_bad_channel or is_bad_user:
        return

    allowed_mentions = discord.AllowedMentions.none()
    progress_message = await new_msg.reply(
        "Processing your request...",
        mention_author=False,
        allowed_mentions=allowed_mentions
    )

    try:
        # Get API key for the main provider.
        api_key = await api_key_manager.get_next_api_key(cfg["provider"])
        if not api_key:
            api_key = 'sk-no-key-required'

        # Determine if images and usernames are allowed based on model/provider.
        accept_images = any(x in cfg["model"].lower() for x in VISION_MODEL_TAGS)
        accept_usernames = any(x in cfg["provider"].lower() for x in PROVIDERS_SUPPORTING_USERNAMES)

        max_text = cfg["max_text"]
        max_images = cfg["max_images"] if accept_images else 0
        max_messages = cfg["max_messages"]

        use_plain_responses = cfg["use_plain_responses"]
        max_message_length = (
            2000 if use_plain_responses else (4096 - len(STREAMING_INDICATOR))
        )

        messages = []
        user_warnings = set()
        curr_msg = new_msg
        while curr_msg is not None and len(messages) < max_messages:
            curr_node = msg_nodes.setdefault(curr_msg.id, MsgNode())

            async with curr_node.lock:
                if curr_node.text is None:
                    # Filter attachments that match allowed file types.
                    good_attachments = {
                        type: [
                            att
                            for att in curr_msg.attachments
                            if att.content_type and type in att.content_type
                        ]
                        for type in ALLOWED_FILE_TYPES
                    }

                    # Assemble textual content from message text and attached files.
                    curr_node.text = "\n".join(
                        ([curr_msg.content] if curr_msg.content else []) +
                        [embed.description for embed in curr_msg.embeds if embed.description] +
                        [
                            f'<text_file name="{html.escape(att.filename)}">\n{html.escape((await httpx_client.get(att.url)).text)}\n</text_file>'
                            for att in good_attachments["text"]
                        ]
                    )

                    # Remove a leading bot mention if present.
                    if curr_node.text.startswith(discord_client.user.mention):
                        curr_node.text = curr_node.text.replace(
                            discord_client.user.mention, "", 1
                        ).lstrip()

                    # Process image attachments into base64 strings.
                    curr_node.images = [
                        dict(
                            type="image_url",
                            image_url=dict(
                                url=f"data:{att.content_type};base64,{b64encode((await httpx_client.get(att.url)).content).decode('utf-8')}"
                            ),
                        )
                        for att in good_attachments["image"]
                    ]

                    # Determine role based on message sender.
                    curr_node.role = (
                        "assistant" if curr_msg.author == discord_client.user else "user"
                    )

                    curr_node.user_id = (
                        curr_msg.author.id if curr_node.role == "user" else None
                    )

                    curr_node.has_bad_attachments = len(curr_msg.attachments) > sum(
                        len(att_list) for att_list in good_attachments.values()
                    )

                    try:
                        # Determine the next message in the conversation chain.
                        if (
                            not curr_msg.reference
                            and discord_client.user.mention not in curr_msg.content
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
                                discord_client.user
                                if curr_msg.channel.type == discord.ChannelType.private
                                else curr_msg.author
                            )
                        ):
                            curr_node.next_msg = prev_msg_in_channel
                        else:
                            is_public_thread = (
                                curr_msg.channel.type == discord.ChannelType.public_thread
                            )
                            next_is_parent_msg = (
                                not curr_msg.reference
                                and is_public_thread
                                and curr_msg.channel.parent.type == discord.ChannelType.text
                            )

                            next_msg_id = (
                                curr_msg.channel.id
                                if next_is_parent_msg
                                else getattr(curr_msg.reference, "message_id", None)
                            )
                            if next_msg_id:
                                if next_is_parent_msg:
                                    curr_node.next_msg = (
                                        curr_msg.channel.starter_message
                                        or await curr_msg.channel.parent.fetch_message(
                                            next_msg_id
                                        )
                                    )
                                else:
                                    curr_node.next_msg = (
                                        curr_msg.reference.cached_message
                                        or await curr_msg.channel.fetch_message(next_msg_id)
                                    )
                    except (discord.NotFound, discord.HTTPException, AttributeError):
                        logging.exception("Error fetching next message in the chain")
                        curr_node.fetch_next_failed = True

                # Prepare content to send based on text and image limits.
                if curr_node.images[:max_images]:
                    content = (
                        ([dict(type="text", text=curr_node.text[:max_text])]
                         if curr_node.text[:max_text]
                         else [])
                        + curr_node.images[:max_images]
                    )
                else:
                    content = curr_node.text[:max_text]

                if content != "":
                    message = dict(
                        content=content, 
                        role=curr_node.role,
                        timestamp=curr_msg.created_at.strftime("%Y-%m-%d %H:%M:%S.%f%z")
                    )
                    if accept_usernames and curr_node.user_id is not None:
                        message["name"] = str(curr_node.user_id)

                    messages.append(message)

                # Check for warnings due to text length, image count, unsupported files, or truncated chain.
                if len(curr_node.text) > max_text:
                    user_warnings.add(f"⚠️ Max {max_text:,} characters per message")
                if len(curr_node.images) > max_images:
                    user_warnings.add(
                        f"⚠️ Max {max_images} image{'' if max_images == 1 else 's'} per message"
                        if max_images > 0
                        else "⚠️ Can't see images"
                    )
                if curr_node.has_bad_attachments:
                    user_warnings.add("⚠️ Unsupported attachments")
                if curr_node.fetch_next_failed or (
                    curr_node.next_msg is not None and len(messages) == max_messages
                ):
                    user_warnings.add(
                        f"⚠️ Only using last {len(messages)} message{'' if len(messages) == 1 else 's'}"
                    )

                curr_msg = curr_node.next_msg

        messages = messages[::-1]

        logging.info(
            f"Message received (user ID: {new_msg.author.id}, attachments: {len(new_msg.attachments)}, conversation length: {len(messages)}):\n{new_msg.content}"
        )

        # Prepend system prompt with additional details if configured.
        if system_prompt := cfg["system_prompt"]:
            system_prompt_extras = [f"Today's date: {dt.now().strftime('%B %d, %Y')}."]
            if accept_usernames:
                system_prompt_extras.append(
                    "User's names are their Discord IDs and should be typed as '<@ID>'."
                )

            full_system_prompt = "\n".join([system_prompt] + system_prompt_extras)
            messages.insert(0, dict(role="system", content=full_system_prompt))

        msg_nodes[new_msg.id].internet_used = False

        user_message_content = new_msg.content

        # Check if the query is a command to run lens or saucenao searches.
        if user_message_content.lower().startswith(('lens', 'sauce')):
            is_lens = user_message_content.lower().startswith('lens')
            prefix_len = len('lens') if is_lens else len('sauce')
            user_message_content = user_message_content[prefix_len:].lstrip()

            if len(new_msg.attachments) == 0:
                service_name = "Google Lens" if is_lens else "SauceNAO"
                await progress_message.edit(content=f"Please attach an image for the {service_name} search.", allowed_mentions=allowed_mentions)
                return

            image_attachment = new_msg.attachments[0]
            image_url = image_attachment.url

            try:
                if is_lens:
                    lens_results = await get_google_lens_results(image_url, api_key_manager, httpx_client)
                    formatted_results = await process_google_lens_results(lens_results, cfg, api_key_manager, httpx_client)
                    results_tag = 'lens_results'
                else:
                    saucenao_api_key = cfg.get('saucenao_api_key')
                    if not saucenao_api_key:
                        await progress_message.edit(content='No SauceNAO API key available.', allowed_mentions=allowed_mentions)
                        return
                    formatted_results = await handle_saucenao_query(image_url, saucenao_api_key, httpx_client)
                    results_tag = 'saucenao_results'
            except Exception as e:
                service_name = "Google Lens" if is_lens else "SauceNAO"
                await progress_message.edit(content=f"Error calling {service_name} API: {e}", allowed_mentions=allowed_mentions)
                return

            # Augment the user query with the visual search results.
            augmented_user_message = (
                f'<user_query>\n{html.escape(user_message_content)}\n</user_query>\n\n'
                f'<{results_tag}>\n{formatted_results}\n</{results_tag}>'
            )

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

        else:
            urls_in_message = extract_urls_from_text(new_msg.content)
            is_url_query = False
            augmented_user_message = None
            if urls_in_message:
                contents = await fetch_urls_content(urls_in_message, api_key_manager, httpx_client, config=cfg)
                augmented_user_message = (
                    f'<user_query>\n{html.escape(new_msg.content)}\n</user_query>\n\n'
                    f'<url_results>\n'
                )
                for idx, (url, content) in enumerate(zip(urls_in_message, contents), start=1):
                    augmented_user_message += (
                        f'<url_result id="{idx}">\n'
                        f'<url>{html.escape(url)}</url>\n'
                        f'<content>{content}</content>\n'
                        f'</url_result>\n'
                    )
                augmented_user_message += '</url_results>'
                is_url_query = True

            if not is_url_query:
                # Rephrase query before splitting it; if rephrasing is not needed, the returned string will be 'not_needed'
                latest_user_query = await rephrase_query(messages, cfg, api_key_manager)
                if latest_user_query != 'not_needed':
                    split_queries = await split_query(latest_user_query, cfg, api_key_manager)
                    serper_api_key = await api_key_manager.get_next_api_key('serper')
                    if not serper_api_key:
                        await progress_message.edit(content='No Serper API key available.', allowed_mentions=allowed_mentions)
                        return

                    msg_nodes[new_msg.id].serper_queries = split_queries
                    msg_nodes[new_msg.id].internet_used = True

                    search_results_list = await asyncio.gather(
                        *[handle_search_query(q, api_key_manager, httpx_client, config=cfg) for q in split_queries]
                    )

                    search_results = (
                        f'<user_query>\n{html.escape(new_msg.content)}\n</user_query>\n\n'
                        f'<search_results_by_query>\n'
                    )
                    for idx, (query, result) in enumerate(zip(split_queries, search_results_list), start=1):
                        search_results += (
                            f'<query_result id="{idx}">\n'
                            f'<query>{html.escape(query)}</query>\n'
                            f'<results>{result}</results>\n'
                            f'</query_result>\n'
                        )
                    search_results += '</search_results_by_query>'

                    augmented_user_message = search_results

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

        response_msgs = []
        response_contents = []
        prev_chunk = None
        edit_task = None

        searched_for_text_added = False
        serper_queries = getattr(msg_nodes[new_msg.id], 'serper_queries', None)
        if serper_queries:
            search_queries_text = ', '.join(f'"{q}"' for q in serper_queries)
            searched_for_text = f'searched for: {search_queries_text}\n\n'
        else:
            searched_for_text = ''

        kwargs = {
            "model": cfg["model"],
            "messages": messages,
            "stream": True,
            "api_key": api_key,
            **cfg["extra_api_parameters"]
        }

        if cfg["provider"] == "google":
            kwargs["safety_settings"] = [
                {
                    "category": "HARM_CATEGORY_HARASSMENT",
                    "threshold": "BLOCK_NONE",
                },
                {
                    "category": "HARM_CATEGORY_HATE_SPEECH",
                    "threshold": "BLOCK_NONE",
                },
                {
                    "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "threshold": "BLOCK_NONE",
                },
                {
                    "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                    "threshold": "BLOCK_NONE",
                },
                {
                    "category": "HARM_CATEGORY_CIVIC_INTEGRITY",
                    "threshold": "BLOCK_NONE",
                }                
            ]

        # Prepare a logging-friendly version of the payload.
        logging_kwargs = json.loads(json.dumps(kwargs, default=str))
        for message in logging_kwargs.get('messages', []):
            if isinstance(message.get('content'), list):
                for item in message['content']:
                    if item.get('type') == 'image_url' and 'url' in item.get('image_url', {}):
                        item['image_url']['url'] = truncate_base64(item['image_url']['url'])
            elif isinstance(message.get('content'), str):
                pass

        logging.info(
            f"Payload being sent to LLM API:\n{json.dumps(logging_kwargs, indent=2, default=str)}"
        )
        
        # ----- RETRY LOGIC FOR MAIN MODEL CALL INCLUDING STREAMING -----
        max_retries = 5
        attempt = 0
        stream_successful = False
        while attempt < max_retries and not stream_successful:
            try:
                if attempt > 0:
                    kwargs["api_key"] = await api_key_manager.get_next_api_key(cfg["provider"])
                logging.info(f"Attempt {attempt+1} for main model using API key: {kwargs['api_key']}")
        
                response_stream = await litellm_acompletion(**kwargs)
                # Process streaming chunks within this try/except block.
                prev_chunk = None
                async for curr_chunk in response_stream:
                    prev_content = (prev_chunk.choices[0].delta.content
                                    if (prev_chunk is not None and prev_chunk.choices[0].delta.content)
                                    else "")
                    curr_content = curr_chunk.choices[0].delta.content or ""
                    
                    if response_contents or prev_content:
                        if response_contents == [] or len(response_contents[-1] + prev_content) > max_message_length:
                            response_contents.append("")
                            if not searched_for_text_added and searched_for_text:
                                response_contents[-1] = searched_for_text
                                searched_for_text_added = True

                            if not use_plain_responses:
                                embed = discord.Embed(
                                    description=(response_contents[-1] + prev_content + STREAMING_INDICATOR),
                                    color=EMBED_COLOR_INCOMPLETE,
                                )
                                for warning in sorted(user_warnings):
                                    embed.add_field(name=warning, value="", inline=False)
                                footer_text = f"Model: {cfg['model']} | " + (
                                    "Internet used" if msg_nodes[new_msg.id].internet_used else "Internet NOT used"
                                )
                                embed.set_footer(text=footer_text)

                                view = OutputView(response_contents, user_message_content, serper_queries)

                                if response_msgs == []:
                                    response_msg = await progress_message.edit(
                                        content=None, embed=embed, view=view, allowed_mentions=allowed_mentions
                                    )
                                    msg_nodes[response_msg.id] = MsgNode(
                                        next_msg=new_msg,
                                        internet_used=msg_nodes[new_msg.id].internet_used,
                                    )
                                    await msg_nodes[response_msg.id].lock.acquire()
                                    response_msgs.append(response_msg)
                                    last_task_time = dt.now().timestamp()
                                else:
                                    reply_to_msg = response_msgs[-1]
                                    response_msg = await reply_to_msg.reply(
                                        embed=embed, view=view, mention_author=False, allowed_mentions=allowed_mentions
                                    )
                                    msg_nodes[response_msg.id] = MsgNode(
                                        next_msg=new_msg,
                                        internet_used=msg_nodes[new_msg.id].internet_used,
                                    )
                                    await msg_nodes[response_msg.id].lock.acquire()
                                    response_msgs.append(response_msg)
                                    last_task_time = dt.now().timestamp()

                        response_contents[-1] += prev_content

                        if not use_plain_responses:
                            finish_reason = curr_chunk.choices[0].finish_reason

                            ready_to_edit = (
                                (edit_task is None or edit_task.done())
                                and dt.now().timestamp() - last_task_time >= EDIT_DELAY_SECONDS
                            )
                            msg_split_incoming = len(response_contents[-1] + curr_content) > max_message_length
                            is_final_edit = finish_reason is not None or msg_split_incoming
                            is_good_finish = finish_reason is not None and any(
                                finish_reason.lower() == x for x in ("stop", "end_turn")
                            )

                            if ready_to_edit or is_final_edit:
                                if edit_task is not None:
                                    await edit_task

                                embed.description = (
                                    response_contents[-1]
                                    if is_final_edit
                                    else (response_contents[-1] + STREAMING_INDICATOR)
                                )
                                embed.color = (
                                    EMBED_COLOR_COMPLETE
                                    if msg_split_incoming or is_good_finish
                                    else EMBED_COLOR_INCOMPLETE
                                )
                                footer_text = f"Model: {cfg['model']} | " + (
                                    "Internet used" if msg_nodes[new_msg.id].internet_used else "Internet NOT used"
                                )
                                embed.set_footer(text=footer_text)

                                edit_task = asyncio.create_task(
                                    response_msgs[-1].edit(embed=embed, view=view, allowed_mentions=allowed_mentions)
                                )
                                last_task_time = dt.now().timestamp()

                    prev_chunk = curr_chunk

                # If the async for loop completes without error, the streaming was successful.
                stream_successful = True
            except Exception as e:
                logging.exception("Error during streaming iteration, retrying with new API key. Attempt %d/%d", attempt+1, max_retries)
                attempt += 1
                if attempt >= max_retries:
                    await progress_message.edit(content="An error occurred while processing your request (rate limit exceeded).", allowed_mentions=allowed_mentions)
                    return
                # Otherwise, continue to retry the entire call and streaming iteration.
        # ----- END RETRY LOGIC -----

        try:
            if use_plain_responses:
                view = OutputView(response_contents, user_message_content, serper_queries)
                for content in response_contents:
                    if response_msgs == []:
                        response_msg = await progress_message.edit(
                            content=content, view=view, suppress_embeds=True, allowed_mentions=allowed_mentions
                        )
                        msg_nodes[response_msg.id] = MsgNode(next_msg=new_msg)
                        await msg_nodes[response_msg.id].lock.acquire()
                        response_msgs.append(response_msg)
                    else:
                        reply_to_msg = response_msgs[-1]
                        response_msg = await reply_to_msg.reply(
                            content=content, view=view, suppress_embeds=True, mention_author=False, allowed_mentions=allowed_mentions
                        )
                        msg_nodes[response_msg.id] = MsgNode(next_msg=new_msg)
                        await msg_nodes[response_msg.id].lock.acquire()
                        response_msgs.append(response_msg)
        except Exception:
            logging.exception("Error while generating response")
            await progress_message.edit(content="An error occurred while processing your request.", allowed_mentions=allowed_mentions)

        # Release locks for each response message node.
        for response_msg in response_msgs:
            msg_nodes[response_msg.id].text = "".join(response_contents)
            msg_nodes[response_msg.id].lock.release()

        # Maintain the global message dictionary within a maximum size.
        if (num_nodes := len(msg_nodes)) > MAX_MESSAGE_NODES:
            for msg_id in sorted(msg_nodes.keys())[: num_nodes - MAX_MESSAGE_NODES]:
                async with msg_nodes.setdefault(msg_id, MsgNode()).lock:
                    msg_nodes.pop(msg_id, None)

        user_msg_node = msg_nodes.get(new_msg.id)
        if user_msg_node and user_msg_node.serper_queries:
            # Launch background image fetching and view updating.
            asyncio.create_task(
                fetch_images_and_update_views(
                    user_msg_node.serper_queries,
                    new_msg.id,
                    response_msgs,
                    api_key_manager,
                    httpx_client
                )
            )

    except Exception:
        logging.exception("Error in on_message handler")
        await progress_message.edit(content="An error occurred while processing your request.", allowed_mentions=allowed_mentions)
        return

async def main():
    """
    Main coroutine to start the Discord client and handle shutdown gracefully.
    """
    try:
        await discord_client.start(cfg["bot_token"])
    finally:
        await httpx_client.aclose()

# Run the main function.
asyncio.run(main())
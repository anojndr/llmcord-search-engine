"""
llmcord Main Application

This is the entry point for the LLM-based Discord bot. The bot processes messages,
manages conversations, integrates web search, image processing, YouTube/Reddit content extraction,
and communicates with various large language models (LLMs) for responses.
"""

import os
import asyncio
import re
from base64 import b64encode
from dataclasses import dataclass, field
from datetime import datetime as dt
import json
import logging
from typing import Literal, Optional, Dict, Any, List, Tuple
import discord
import httpx
from litellm import acompletion as litellm_acompletion
from dotenv import load_dotenv
import html

from search_handler import handle_search_queries
from url_handler import extract_urls_from_text, fetch_urls_content
from rephraser_handler import rephrase_query
from query_splitter_handler import split_query
from google_lens_handler import get_google_lens_results, process_google_lens_results
from saucenao_handler import handle_saucenao_query
from searxng_image_handler import fetch_images

from discord.ui import Button, TextInput
from discord import File, Message
import io

from api_key_manager import APIKeyManager

from keep_alive import keep_alive

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)

keep_alive()

VISION_MODEL_TAGS: Tuple[str, ...] = (
    "gpt-4o",
    "claude-3",
    "gemini",
    "pixtral",
    "llava",
    "vision",
    "vl",
)
PROVIDERS_SUPPORTING_USERNAMES: Tuple[str, ...] = ("openai", "x-ai")

ALLOWED_FILE_TYPES: Tuple[str, ...] = ("image", "text")

EMBED_COLOR_COMPLETE: discord.Color = discord.Color.dark_green()
EMBED_COLOR_INCOMPLETE: discord.Color = discord.Color.orange()

STREAMING_INDICATOR: str = " ⚪"
EDIT_DELAY_SECONDS: int = 1

MAX_MESSAGE_NODES: int = 100

load_dotenv()

async def fetch_images_and_update_views(
    split_queries: List[str],
    user_msg_id: int,
    response_msgs: List[Message],
    api_key_manager: APIKeyManager,
    httpx_client: httpx.AsyncClient
) -> None:
    try:
        image_files_dict: Dict[str, List[File]]
        image_urls_dict: Dict[str, List[str]]
        image_files_dict, image_urls_dict = await fetch_images(split_queries, 5, api_key_manager, httpx_client)

        async with msg_nodes[user_msg_id].lock:
            msg_nodes[user_msg_id].image_files = image_files_dict
            msg_nodes[user_msg_id].image_urls = image_urls_dict

        for response_msg in response_msgs:
            new_view: OutputView = OutputView(
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
    parent_view: 'OutputView'
    image_count: TextInput

    def __init__(self, parent_view: 'OutputView') -> None:
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

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            count: int = int(self.image_count.value)
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
    contents: List[str]
    query: str
    serper_queries: Optional[List[str]]
    image_files: Dict[str, List[File]]
    image_urls: Dict[str, List[str]]

    def __init__(
        self,
        contents: List[str],
        query: str,
        serper_queries: Optional[List[str]] = None,
        image_files: Optional[Dict[str, List[File]]] = None,
        image_urls: Optional[Dict[str, List[str]]] = None
    ) -> None:
        super().__init__(timeout=None)
        self.contents = contents
        self.query = query
        self.serper_queries = serper_queries
        self.image_files = image_files or {}
        self.image_urls = image_urls or {}

        self.add_text_file_button()
        if self.serper_queries and (self.image_files or self.image_urls):
            self.add_show_images_button()

    def add_text_file_button(self) -> None:
        text_file_button: Button = Button(
            label="Get Output as Text File",
            style=discord.ButtonStyle.primary,
            custom_id="text_file"
        )
        text_file_button.callback = self.text_file_button_callback
        self.add_item(text_file_button)

    def add_show_images_button(self) -> None:
        show_images_button: Button = Button(
            label="Show Images",
            style=discord.ButtonStyle.secondary,
            custom_id="show_images"
        )
        show_images_button.callback = self.show_images_button_callback
        self.add_item(show_images_button)

    async def text_file_button_callback(self, interaction: discord.Interaction) -> None:
        await self.send_text_file(interaction)
        for item in self.children:
            if item.custom_id == "text_file":
                item.disabled = True
                break
        await interaction.message.edit(view=self)

    async def show_images_button_callback(self, interaction: discord.Interaction) -> None:
        total_images: int = sum(len(files) for files in self.image_files.values()) + \
                          sum(len(urls) for urls in self.image_urls.values())

        if total_images == 0:
            await interaction.response.send_message("No images found.", ephemeral=True)
            return

        modal: ImageCountModal = ImageCountModal(self)
        await interaction.response.send_modal(modal)
        for item in self.children:
            if item.custom_id == "show_images":
                item.disabled = True
                break
        await interaction.message.edit(view=self)

    async def send_text_file(self, interaction: discord.Interaction) -> None:
        full_content: str = "".join(self.contents)
        file: io.StringIO = io.StringIO(full_content)
        await interaction.response.send_message(
            content="Here is the output as a text file:",
            file=File(file, filename="output.txt"),
            ephemeral=True
        )

    async def show_images(self, interaction: discord.Interaction, selected_count: int) -> None:
        await interaction.response.defer()

        if len(self.image_files) == 1 and not self.serper_queries:
            query: str = next(iter(self.image_files))
            files: List[File] = self.image_files[query][:selected_count] if self.image_files[query] else []
            urls: List[str] = self.image_urls[query][:selected_count] if query in self.image_urls else []
            if not files and not urls:
                await interaction.followup.send("No images available.", ephemeral=True)
                return
            message_content: str = f"Here are {len(files) + len(urls)} images:"
            if urls:
                message_content += "\n\nFailed downloads (shown as URLs):\n" + "\n".join(urls)
            await interaction.followup.send(content=message_content, files=files)
        else:
            for i, query in enumerate(self.image_files.keys(), 1):
                files: List[File] = self.image_files[query][:selected_count] if query in self.image_files else []
                urls: List[str] = self.image_urls[query][:selected_count] if query in self.image_urls else []
                if not files and not urls:
                    continue
                message_content: str = f"Images for query {i}: '{query}' ({len(files) + len(urls)} images)"
                if urls:
                    message_content += "\n\nFailed downloads (shown as URLs):\n" + "\n".join(urls)
                await interaction.followup.send(content=message_content, files=files)

@dataclass
class MsgNode:
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

def get_config() -> Dict[str, Any]:
    try:
        with open('system_prompt.txt', 'r', encoding='utf-8') as f:
            system_prompt: str = f.read()
    except FileNotFoundError:
        system_prompt: str = ("You are a helpful assistant. Cite the most relevant search results as needed to answer the "
                             "question, avoiding irrelevant ones. Write only the response and use markdown for formatting. "
                             "Include a clickable hyperlink at the end of the corresponding sentence using the site name.")

    config: Dict[str, Any] = {
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
        "saucenao_api_keys": os.getenv("SAUCENAO_API_KEYS", "").split(","),
        "max_urls": int(os.getenv("MAX_URLS", "5")),
    }
    return config

cfg: Dict[str, Any] = get_config()
api_key_manager: APIKeyManager = APIKeyManager(cfg)
if client_id := cfg["client_id"]:
    logging.info(
        f"\n\nBOT INVITE URL:\nhttps://discord.com/api/oauth2/authorize?client_id={client_id}&permissions=412317273088&scope=bot\n"
    )

intents: discord.Intents = discord.Intents.default()
intents.message_content = True
activity: discord.Game = discord.Game(
    name=(cfg["status_message"] or "https://github.com/anojndr/llmcord-search-engine")[:128]
)
discord_client: discord.Client = discord.Client(intents=intents, activity=activity)
httpx_client: httpx.AsyncClient = httpx.AsyncClient(http2=True)
msg_nodes: Dict[int, MsgNode] = {}
last_task_time: Optional[float] = None

def truncate_base64(base64_string: str, max_length: int = 50) -> str:
    if len(base64_string) > max_length:
        return base64_string[:max_length] + "..."
    return base64_string

@discord_client.event
async def on_message(new_msg: Message) -> None:
    global msg_nodes, last_task_time, httpx_client
    is_dm: bool = new_msg.channel.type == discord.ChannelType.private
    at_ai_pattern: str = r'\bat ai\b'
    if (
        not is_dm
        and not re.search(at_ai_pattern, new_msg.content, re.IGNORECASE)
        and discord_client.user not in new_msg.mentions
    ) or new_msg.author.bot:
        return

    content_without_at_ai: str = re.sub(at_ai_pattern, '', new_msg.content, flags=re.IGNORECASE)
    content_without_mentions: str = content_without_at_ai.replace(discord_client.user.mention, '').lstrip()
    new_msg.content = content_without_mentions

    cfg: Dict[str, Any] = get_config()
    allow_dms: bool = cfg["allow_dms"]
    allowed_channel_ids: List[int] = cfg["allowed_channel_ids"]
    allowed_role_ids: List[int] = cfg["allowed_role_ids"]
    blocked_user_ids: List[int] = cfg["blocked_user_ids"]

    channel_ids: Tuple[int, ...] = tuple(
        id
        for id in (
            new_msg.channel.id,
            getattr(new_msg.channel, "parent_id", None),
            getattr(new_msg.channel, "category_id", None),
        )
        if id
    )

    is_bad_channel: bool = (is_dm and not allow_dms) or (
        not is_dm
        and allowed_channel_ids
        and not any(id in allowed_channel_ids for id in channel_ids)
    )
    is_bad_user: bool = new_msg.author.id in blocked_user_ids or (
        allowed_role_ids
        and not any(
            role.id in allowed_role_ids for role in getattr(new_msg.author, "roles", [])
        )
    )

    if is_bad_channel or is_bad_user:
        return

    allowed_mentions: discord.AllowedMentions = discord.AllowedMentions.none()
    progress_message: Message = await new_msg.reply(
        "Processing your request...",
        mention_author=False,
        allowed_mentions=allowed_mentions
    )

    try:
        api_key: str = await api_key_manager.get_next_api_key(cfg["provider"])
        if not api_key:
            api_key = 'sk-no-key-required'

        accept_images: bool = any(x in cfg["model"].lower() for x in VISION_MODEL_TAGS)
        accept_usernames: bool = any(x in cfg["provider"].lower() for x in PROVIDERS_SUPPORTING_USERNAMES)
        max_text: int = cfg["max_text"]
        max_images: int = cfg["max_images"] if accept_images else 0
        max_messages: int = cfg["max_messages"]
        use_plain_responses: bool = cfg["use_plain_responses"]
        max_message_length: int = (
            2000 if use_plain_responses else (4096 - len(STREAMING_INDICATOR))
        )
        messages: List[Dict[str, Any]] = []
        user_warnings: set[str] = set()
        curr_msg: Optional[Message] = new_msg
        while curr_msg is not None and len(messages) < max_messages:
            curr_node: MsgNode = msg_nodes.setdefault(curr_msg.id, MsgNode())
            async with curr_node.lock:
                if curr_node.text is None:
                    good_attachments: Dict[str, List[discord.Attachment]] = {
                        type: [
                            att
                            for att in curr_msg.attachments
                            if att.content_type and type in att.content_type
                        ]
                        for type in ALLOWED_FILE_TYPES
                    }
                    curr_node.text = "\n".join(
                        ([curr_msg.content] if curr_msg.content else []) +
                        [embed.description for embed in curr_msg.embeds if embed.description] +
                        [
                            f'<text_file name="{html.escape(att.filename)}">\n{html.escape((await httpx_client.get(att.url)).text)}\n</text_file>'
                            for att in good_attachments["text"]
                        ]
                    )
                    if curr_node.text.startswith(discord_client.user.mention):
                        curr_node.text = curr_node.text.replace(
                            discord_client.user.mention, "", 1
                        ).lstrip()
                    curr_node.images = [
                        dict(
                            type="image_url",
                            image_url=dict(
                                url=f"data:{att.content_type};base64,{b64encode((await httpx_client.get(att.url)).content).decode('utf-8')}"
                            ),
                        )
                        for att in good_attachments["image"]
                    ]
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
                            is_public_thread: bool = (
                                curr_msg.channel.type == discord.ChannelType.public_thread
                            )
                            next_is_parent_msg: bool = (
                                not curr_msg.reference
                                and is_public_thread
                                and curr_msg.channel.parent.type == discord.ChannelType.text
                            )
                            next_msg_id: Optional[int] = (
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
                if curr_node.images[:max_images]:
                    content: List[Dict[str, Any]] = (
                        ([dict(type="text", text=curr_node.text[:max_text])]
                         if curr_node.text[:max_text]
                         else []) +
                        curr_node.images[:max_images]
                    )
                else:
                    content: str = curr_node.text[:max_text]
                if content != "":
                    message: Dict[str, Any] = dict(
                        content=content,
                        role=curr_node.role,
                        timestamp=curr_msg.created_at.strftime("%Y-%m-%d %H:%M:%S.%f%z")
                    )
                    if accept_usernames and curr_node.user_id is not None:
                        message["name"] = str(curr_node.user_id)
                    messages.append(message)
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
        if system_prompt := cfg["system_prompt"]:
            system_prompt_extras: List[str] = [f"Today's date: {dt.now().strftime('%B %d, %Y')}."]
            if accept_usernames:
                system_prompt_extras.append(
                    "User's names are their Discord IDs and should be typed as '<@ID>'."
                )
            full_system_prompt: str = "\n".join([system_prompt] + system_prompt_extras)
            messages.insert(0, dict(role="system", content=full_system_prompt))
        msg_nodes[new_msg.id].internet_used = False
        user_message_content: str = new_msg.content

        if user_message_content.lower().startswith(('lens', 'sauce')):
            is_lens: bool = user_message_content.lower().startswith('lens')
            prefix_len: int = len('lens') if is_lens else len('sauce')
            user_message_content = user_message_content[prefix_len:].lstrip()
            if len(new_msg.attachments) == 0:
                service_name: str = "Google Lens" if is_lens else "SauceNAO"
                await progress_message.edit(content=f"Please attach an image for the {service_name} search.", allowed_mentions=allowed_mentions)
                return
            image_attachment: discord.Attachment = new_msg.attachments[0]
            image_url: str = image_attachment.url
            try:
                if is_lens:
                    lens_results: Dict[str, Any] = await get_google_lens_results(image_url, api_key_manager, httpx_client)
                    formatted_results: str = await process_google_lens_results(lens_results, cfg, api_key_manager, httpx_client)
                    results_tag: str = 'lens results'
                else:
                    formatted_results: str = await handle_saucenao_query(image_url, api_key_manager, httpx_client)
                    results_tag: str = 'saucenao results'
            except Exception as e:
                service_name: str = "Google Lens" if is_lens else "SauceNAO"
                await progress_message.edit(content=f"Error calling {service_name} API: {e}", allowed_mentions=allowed_mentions)
                return
            augmented_user_message: str = (
                f"User Query: {html.escape(user_message_content)}\n\n"
                f"{results_tag.capitalize()}:\n{formatted_results}"
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
            urls_in_message: List[str] = extract_urls_from_text(new_msg.content)
            is_url_query: bool = False
            augmented_user_message: Optional[str] = None
            if urls_in_message:
                contents: List[str] = await fetch_urls_content(urls_in_message, api_key_manager, httpx_client, config=cfg)
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
                is_url_query = True
            if not is_url_query:
                latest_user_query: str = await rephrase_query(messages, cfg, api_key_manager)
                if latest_user_query != 'not_needed':
                    split_queries: List[str] = await split_query(latest_user_query, cfg, api_key_manager)
                    msg_nodes[new_msg.id].serper_queries = split_queries
                    msg_nodes[new_msg.id].internet_used = True
                    aggregated_results: str = await handle_search_queries(split_queries, api_key_manager, httpx_client, config=cfg)
                    augmented_user_message = f"User Query: {html.escape(new_msg.content)}\n\nAggregated Search Results:\n{aggregated_results}"
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

        response_msgs: List[Message] = []
        response_contents: List[str] = []
        prev_chunk: Any = None
        edit_task: Optional[asyncio.Task] = None

        searched_for_text_added: bool = False
        serper_queries: Optional[List[str]] = getattr(msg_nodes[new_msg.id], 'serper_queries', None)
        if serper_queries:
            search_queries_text: str = ', '.join(f'"{q}"' for q in serper_queries)
            searched_for_text: str = f"Searched for: {search_queries_text}\n\n"
        else:
            searched_for_text: str = ''

        kwargs: Dict[str, Any] = {
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
        logging.info(
            f"Payload being sent to LLM API:\n{json.dumps(kwargs, indent=2, default=str)}"
        )

        max_retries: int = 5
        attempt: int = 0
        stream_successful: bool = False
        while attempt < max_retries and not stream_successful:
            try:
                if attempt > 0:
                    kwargs["api_key"] = await api_key_manager.get_next_api_key(cfg["provider"])
                logging.info(f"Attempt {attempt+1} for main model using API key: {kwargs['api_key']}")
                response_stream = await litellm_acompletion(**kwargs)
                prev_chunk = None
                async for curr_chunk in response_stream:
                    prev_content: str = (prev_chunk.choices[0].delta.content
                                        if (prev_chunk is not None and prev_chunk.choices[0].delta.content)
                                        else "")
                    curr_content: str = curr_chunk.choices[0].delta.content or ""
                    if response_contents or prev_content:
                        if response_contents == [] or len(response_contents[-1] + prev_content) > max_message_length:
                            response_contents.append("")
                            if not use_plain_responses:
                                embed_description: str = ""
                                if not searched_for_text_added and searched_for_text:
                                    embed_description = searched_for_text
                                    searched_for_text_added = True

                                embed_description += response_contents[-1] + prev_content + STREAMING_INDICATOR

                                embed: discord.Embed = discord.Embed(
                                    description=embed_description,
                                    color=EMBED_COLOR_INCOMPLETE,
                                )
                                for warning in sorted(user_warnings):
                                    embed.add_field(name=warning, value="", inline=False)
                                footer_text: str = f"Model: {cfg['model']} | " + (
                                    "Internet used" if msg_nodes[new_msg.id].internet_used else "Internet NOT used"
                                )
                                embed.set_footer(text=footer_text)
                                view: OutputView = OutputView(response_contents, user_message_content, serper_queries)
                                if response_msgs == []:
                                    response_msg: Message = await progress_message.edit(
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
                                    reply_to_msg: Message = response_msgs[-1]
                                    response_msg: Message = await reply_to_msg.reply(
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
                            finish_reason: Optional[str] = curr_chunk.choices[0].finish_reason
                            ready_to_edit: bool = (
                                (edit_task is None or edit_task.done())
                                and dt.now().timestamp() - last_task_time >= EDIT_DELAY_SECONDS
                            )
                            msg_split_incoming: bool = len(response_contents[-1] + curr_content) > max_message_length
                            is_final_edit: bool = finish_reason is not None or msg_split_incoming
                            is_good_finish: bool = finish_reason is not None and any(
                                finish_reason.lower() == x for x in ("stop", "end_turn")
                            )
                            if ready_to_edit or is_final_edit:
                                if edit_task is not None:
                                    await edit_task

                                embed_description: str = ""
                                if searched_for_text_added and searched_for_text:
                                    embed_description = searched_for_text

                                embed_description += (
                                    response_contents[-1]
                                    if is_final_edit
                                    else (response_contents[-1] + STREAMING_INDICATOR)
                                )

                                embed.description = embed_description
                                embed.color = (
                                    EMBED_COLOR_COMPLETE
                                    if msg_split_incoming or is_good_finish
                                    else EMBED_COLOR_INCOMPLETE
                                )
                                footer_text: str = f"Model: {cfg['model']} | " + (
                                    "Internet used" if msg_nodes[new_msg.id].internet_used else "Internet NOT used"
                                )
                                embed.set_footer(text=footer_text)
                                edit_task = asyncio.create_task(
                                    response_msgs[-1].edit(embed=embed, view=view, allowed_mentions=allowed_mentions)
                                )
                                last_task_time = dt.now().timestamp()
                    prev_chunk = curr_chunk
                stream_successful = True
            except Exception as e:
                logging.exception("Error during streaming iteration, retrying with new API key. Attempt %d/%d", attempt+1, max_retries)
                attempt += 1
                if attempt >= max_retries:
                    await progress_message.edit(content="An error occurred while processing your request (rate limit exceeded).", allowed_mentions=allowed_mentions)
                    return
        try:
            if use_plain_responses:
                view: OutputView = OutputView(response_contents, user_message_content, serper_queries)
                for content in response_contents:
                    if response_msgs == []:
                        response_msg: Message = await progress_message.edit(
                            content=content, view=view, suppress_embeds=True, allowed_mentions=allowed_mentions
                        )
                        msg_nodes[response_msg.id] = MsgNode(next_msg=new_msg)
                        await msg_nodes[response_msg.id].lock.acquire()
                        response_msgs.append(response_msg)
                    else:
                        reply_to_msg: Message = response_msgs[-1]
                        response_msg: Message = await reply_to_msg.reply(
                            content=content, view=view, suppress_embeds=True, mention_author=False, allowed_mentions=allowed_mentions
                        )
                        msg_nodes[response_msg.id] = MsgNode(next_msg=new_msg)
                        await msg_nodes[response_msg.id].lock.acquire()
                        response_msgs.append(response_msg)
        except Exception:
            logging.exception("Error while generating response")
            await progress_message.edit(content="An error occurred while processing your request.", allowed_mentions=allowed_mentions)
        for response_msg in response_msgs:
            msg_nodes[response_msg.id].text = "".join(response_contents)
            msg_nodes[response_msg.id].lock.release()
        if (num_nodes := len(msg_nodes)) > MAX_MESSAGE_NODES:
            for msg_id in sorted(msg_nodes.keys())[: num_nodes - MAX_MESSAGE_NODES]:
                async with msg_nodes.setdefault(msg_id, MsgNode()).lock:
                    msg_nodes.pop(msg_id, None)
        user_msg_node: Optional[MsgNode] = msg_nodes.get(new_msg.id)
        if user_msg_node and user_msg_node.serper_queries:
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

async def main() -> None:
    try:
        await discord_client.start(cfg["bot_token"])
    finally:
        await httpx_client.aclose()

asyncio.run(main())
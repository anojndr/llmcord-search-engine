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
from openai import AsyncOpenAI
from dotenv import load_dotenv

from search_handler import handle_search_query
from url_handler import extract_urls_from_text, fetch_urls_content
from rephraser_handler import rephrase_query
from query_splitter_handler import split_query
from google_lens_handler import get_google_lens_results, process_google_lens_results
from image_handler import fetch_images_from_serper

from discord.ui import View, Button, TextInput
from discord import File
import io

from api_key_manager import APIKeyManager

from keep_alive import keep_alive

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)

keep_alive()

VISION_MODEL_TAGS = (
    "gpt-4o",
    "claude-3",
    "gemini",
    "pixtral",
    "llava",
    "vision",
    "vl",
)
PROVIDERS_SUPPORTING_USERNAMES = ("openai", "x-ai")

ALLOWED_FILE_TYPES = ("image", "text")

EMBED_COLOR_COMPLETE = discord.Color.dark_green()
EMBED_COLOR_INCOMPLETE = discord.Color.orange()

STREAMING_INDICATOR = " ⚪"
EDIT_DELAY_SECONDS = 1

MAX_MESSAGE_NODES = 100

load_dotenv()

class ImageCountModal(discord.ui.Modal, title="Select Number of Images"):
    def __init__(self, parent_view):
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
        super().__init__(timeout=None)
        self.contents = contents
        self.query = query
        self.serper_queries = serper_queries
        
        if isinstance(image_files, dict):
            self.image_files = image_files
        else:
            self.image_files = {query: image_files} if image_files else {}
            
        if isinstance(image_urls, dict):
            self.image_urls = image_urls
        else:
            self.image_urls = {query: image_urls} if image_urls else {}

        self.add_text_file_button()
        if self.serper_queries is not None:
            self.add_show_images_button()

    def add_text_file_button(self):
        text_file_button = Button(
            label="Get Output as Text File",
            style=discord.ButtonStyle.primary,
            custom_id="text_file"
        )
        text_file_button.callback = self.text_file_button_callback
        self.add_item(text_file_button)

    def add_show_images_button(self):
        show_images_button = Button(
            label="Show Images",
            style=discord.ButtonStyle.secondary,
            custom_id="show_images"
        )
        show_images_button.callback = self.show_images_button_callback
        self.add_item(show_images_button)

    async def text_file_button_callback(self, interaction: discord.Interaction):
        await self.send_text_file(interaction)
        for item in self.children:
            if item.custom_id == "text_file":
                item.disabled = True
                break
        await interaction.message.edit(view=self)

    async def show_images_button_callback(self, interaction: discord.Interaction):
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
        full_content = "".join(self.contents)
        file = io.StringIO(full_content)
        await interaction.response.send_message(
            content="Here is the output as a text file:",
            file=File(file, filename="output.txt"),
            ephemeral=True
        )

    async def show_images(self, interaction: discord.Interaction, selected_count: int):
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
                "base_url": os.getenv("OPENAI_BASE_URL"),
                "api_keys": os.getenv("OPENAI_API_KEYS", "").split(","),
            },
            "x-ai": {
                "base_url": os.getenv("XAI_BASE_URL"),
                "api_keys": os.getenv("XAI_API_KEYS", "").split(","),
            },
            "google": {
                "base_url": os.getenv("GOOGLE_BASE_URL"),
                "api_keys": os.getenv("GOOGLE_API_KEYS", "").split(","),
            },
            "mistral": {
                "base_url": os.getenv("MISTRAL_BASE_URL", "https://api.mistral.ai/v1"),
                "api_keys": os.getenv("MISTRAL_API_KEYS", "").split(","),
            },
            "groq": {
                "base_url": os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
                "api_keys": os.getenv("GROQ_API_KEYS", "").split(","),
            },
            "openrouter": {
                "base_url": os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
                "api_keys": os.getenv("OPENROUTER_API_KEYS", "").split(","),
            },
            "ollama": {
                "base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
                "api_keys": [],
            },
            "lmstudio": {
                "base_url": os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1"),
                "api_keys": [],
            },
            "vllm": {
                "base_url": os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1"),
                "api_keys": [],
            },
            "oobabooga": {
                "base_url": os.getenv("OOBOOGA_BASE_URL", "http://localhost:5000/v1"),
                "api_keys": [],
            },
            "jan": {
                "base_url": os.getenv("JAN_BASE_URL", "http://localhost:1337/v1"),
                "api_keys": [],
            },
        },
        "model": os.getenv("MODEL", "openai/gpt-4o"),
        "extra_api_parameters": {
            "temperature": float(os.getenv("EXTRA_API_PARAMETERS_TEMPERATURE", "1.0")),
        },
        "rephraser_model": os.getenv("REPHRASER_MODEL", "openai/gpt-4o-mini"),
        "rephraser_extra_api_parameters": {
            "temperature": float(os.getenv("REPHRASER_EXTRA_API_PARAMETERS_TEMPERATURE", "0.7")),
        },
        "query_splitter_model": os.getenv("QUERY_SPLITTER_MODEL", "openai/gpt-4o-mini"),
        "query_splitter_extra_api_parameters": {
            "temperature": float(os.getenv("QUERY_SPLITTER_EXTRA_API_PARAMETERS_TEMPERATURE", "0.5")),
        },
        "system_prompt": os.getenv("SYSTEM_PROMPT", "You are a helpful assistant..."),
        "serper_api_keys": os.getenv("SERPER_API_KEYS", "").split(","),
        "serpapi_api_keys": os.getenv("SERPAPI_API_KEYS", "").split(","),
        "youtube_api_keys": os.getenv("YOUTUBE_API_KEYS", "").split(","),
        "max_urls": int(os.getenv("MAX_URLS", "5")),
    }
    return config

cfg = get_config()
api_key_manager = APIKeyManager(cfg)

if client_id := cfg["client_id"]:
    logging.info(
        f"\n\nBOT INVITE URL:\nhttps://discord.com/api/oauth2/authorize?client_id={client_id}&permissions=412317273088&scope=bot\n"
    )

intents = discord.Intents.default()
intents.message_content = True
activity = discord.Game(
    name=(cfg["status_message"] or "https://github.com/anojndr/llmcord-search-engine")[:128]
)
discord_client = discord.Client(intents=intents, activity=activity)

httpx_client = httpx.AsyncClient()

msg_nodes = {}
last_task_time = None

@discord_client.event
async def on_message(new_msg):
    global msg_nodes, last_task_time, httpx_client

    is_dm = new_msg.channel.type == discord.ChannelType.private

    at_ai_pattern = r'\bat ai\b'

    if (
        not is_dm
        and not re.search(at_ai_pattern, new_msg.content, re.IGNORECASE)
        and discord_client.user not in new_msg.mentions
    ) or new_msg.author.bot:
        return

    content_without_at_ai = re.sub(at_ai_pattern, '', new_msg.content, flags=re.IGNORECASE)
    content_without_mentions = content_without_at_ai.replace(discord_client.user.mention, '').lstrip()
    new_msg.content = content_without_mentions

    cfg = get_config()

    allow_dms = cfg["allow_dms"]
    allowed_channel_ids = cfg["allowed_channel_ids"]
    allowed_role_ids = cfg["allowed_role_ids"]
    blocked_user_ids = cfg["blocked_user_ids"]

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
        provider, model = cfg["model"].split("/", 1)
        base_url = cfg["providers"][provider]["base_url"]
        api_key = await api_key_manager.get_next_api_key(provider)
        if not api_key:
            api_key = 'sk-no-key-required'

        openai_client = AsyncOpenAI(base_url=base_url, api_key=api_key)

        accept_images = any(x in model.lower() for x in VISION_MODEL_TAGS)
        accept_usernames = any(x in provider.lower() for x in PROVIDERS_SUPPORTING_USERNAMES)

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
                    good_attachments = {
                        type: [
                            att
                            for att in curr_msg.attachments
                            if att.content_type and type in att.content_type
                        ]
                        for type in ALLOWED_FILE_TYPES
                    }

                    curr_node.text = "\n".join(
                        ([curr_msg.content] if curr_msg.content else [])
                        + [embed.description for embed in curr_msg.embeds if embed.description]
                        + [
                            (await httpx_client.get(att.url)).text
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
                    message = dict(content=content, role=curr_node.role)
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
            system_prompt_extras = [f"Today's date: {dt.now().strftime('%B %d, %Y')}."]
            if accept_usernames:
                system_prompt_extras.append(
                    "User's names are their Discord IDs and should be typed as '<@ID>'."
                )

            full_system_prompt = "\n".join([system_prompt] + system_prompt_extras)
            messages.insert(0, dict(role="system", content=full_system_prompt))

        msg_nodes[new_msg.id].internet_used = False

        user_message_content = new_msg.content

        if user_message_content.lower().startswith('lens'):
            user_message_content = user_message_content[len('lens'):].lstrip()

            if len(new_msg.attachments) == 0:
                await progress_message.edit(content="Please attach an image for the Google Lens search.", allowed_mentions=allowed_mentions)
                return

            image_attachment = new_msg.attachments[0]
            image_url = image_attachment.url

            serpapi_api_key = await api_key_manager.get_next_api_key('serpapi')
            if not serpapi_api_key:
                await progress_message.edit(content='No SerpApi API key available.', allowed_mentions=allowed_mentions)
                return

            try:
                lens_results = await get_google_lens_results(image_url, api_key_manager, httpx_client)
            except Exception as e:
                await progress_message.edit(content=f"Error calling Google Lens API: {e}", allowed_mentions=allowed_mentions)
                return

            formatted_lens_results = await process_google_lens_results(lens_results, cfg, api_key_manager, httpx_client)

            augmented_user_message = user_message_content + "\n\nRespond to my query based on the google lens results:\n" + formatted_lens_results

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
                    new_msg.content + "\n\nRespond to my query based on the url content/s:\n"
                )
                for idx, (url, content) in enumerate(zip(urls_in_message, contents), start=1):
                    augmented_user_message += (
                        f"url {idx}:\n{url}\nurl {idx} content:\n{content}\n\n"
                    )
                is_url_query = True

            if not is_url_query:
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

                    search_results = ""
                    for idx, (query, result) in enumerate(zip(split_queries, search_results_list), start=1):
                        search_results += f"Results for query {idx} ('{query}'):\n{result}\n\n"

                    augmented_user_message = new_msg.content + "\n\nRespond to my query based on the search results:\n" + search_results

                    if split_queries:
                        image_files_dict = {}
                        image_urls_dict = {}
                        
                        for query in split_queries:
                            files, urls = await fetch_images_from_serper([query], 5, api_key_manager, httpx_client)
                            image_files_dict[query] = files
                            image_urls_dict[query] = urls

                        msg_nodes[new_msg.id].image_files = image_files_dict
                        msg_nodes[new_msg.id].image_urls = image_urls_dict
                    else:
                        files, urls = await fetch_images_from_serper([latest_user_query], 5, api_key_manager, httpx_client)
                        msg_nodes[new_msg.id].image_files = {latest_user_query: files}
                        msg_nodes[new_msg.id].image_urls = {latest_user_query: urls}

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

        kwargs = dict(
            model=model,
            messages=messages,
            stream=True,
            extra_body=cfg["extra_api_parameters"],
        )

        logging.info(
            f"Payload being sent to LLM API:\n{json.dumps(kwargs, indent=2, default=str)}"
        )

        try:
            async for curr_chunk in await openai_client.chat.completions.create(
                **kwargs
            ):
                prev_content = (
                    prev_chunk.choices[0].delta.content
                    if prev_chunk is not None and prev_chunk.choices[0].delta.content
                    else ""
                )
                curr_content = curr_chunk.choices[0].delta.content or ""

                if response_contents or prev_content:
                    if response_contents == [] or len(
                        response_contents[-1] + prev_content
                    ) > max_message_length:
                        response_contents.append("")

                        if not searched_for_text_added and searched_for_text:
                            response_contents[-1] = searched_for_text
                            searched_for_text_added = True

                        if not use_plain_responses:
                            embed = discord.Embed(
                                description=(
                                    response_contents[-1]
                                    + prev_content
                                    + STREAMING_INDICATOR
                                ),
                                color=EMBED_COLOR_INCOMPLETE,
                            )
                            for warning in sorted(user_warnings):
                                embed.add_field(name=warning, value="", inline=False)
                            footer_text = f"Model: {model} | " + (
                                "Internet used"
                                if msg_nodes[new_msg.id].internet_used
                                else "Internet NOT used"
                            )
                            embed.set_footer(text=footer_text)

                            view = OutputView(response_contents, user_message_content, serper_queries, msg_nodes[new_msg.id].image_files, msg_nodes[new_msg.id].image_urls)

                            if response_msgs == []:
                                response_msg = await progress_message.edit(
                                    content=None, embed=embed, view=view, allowed_mentions=allowed_mentions
                                )
                                msg_nodes[response_msg.id] = MsgNode(
                                    next_msg=new_msg,
                                    internet_used=msg_nodes[
                                        new_msg.id
                                    ].internet_used,
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
                                    internet_used=msg_nodes[
                                        new_msg.id
                                    ].internet_used,
                                )
                                await msg_nodes[response_msg.id].lock.acquire()
                                response_msgs.append(response_msg)
                                last_task_time = dt.now().timestamp()

                    response_contents[-1] += prev_content

                    if not use_plain_responses:
                        finish_reason = curr_chunk.choices[0].finish_reason

                        ready_to_edit = (
                            (edit_task is None or edit_task.done())
                            and dt.now().timestamp() - last_task_time
                            >= EDIT_DELAY_SECONDS
                        )
                        msg_split_incoming = len(
                            response_contents[-1] + curr_content
                        ) > max_message_length
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
                            footer_text = f"Model: {model} | " + (
                                "Internet used"
                                if msg_nodes[new_msg.id].internet_used
                                else "Internet NOT used"
                            )
                            embed.set_footer(text=footer_text)

                            edit_task = asyncio.create_task(
                                response_msgs[-1].edit(embed=embed, view=view, allowed_mentions=allowed_mentions)
                            )
                            last_task_time = dt.now().timestamp()

                prev_chunk = curr_chunk

            if use_plain_responses:
                view = OutputView(response_contents, user_message_content, serper_queries, msg_nodes[new_msg.id].image_files, msg_nodes[new_msg.id].image_urls)

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

        for response_msg in response_msgs:
            msg_nodes[response_msg.id].text = "".join(response_contents)
            msg_nodes[response_msg.id].lock.release()

        if (num_nodes := len(msg_nodes)) > MAX_MESSAGE_NODES:
            for msg_id in sorted(msg_nodes.keys())[: num_nodes - MAX_MESSAGE_NODES]:
                async with msg_nodes.setdefault(msg_id, MsgNode()).lock:
                    msg_nodes.pop(msg_id, None)

    except Exception:
        logging.exception("Error in on_message handler")
        await progress_message.edit(content="An error occurred while processing your request.", allowed_mentions=allowed_mentions)
        return

async def main():
    try:
        await discord_client.start(cfg["bot_token"])
    finally:
        await httpx_client.aclose()

asyncio.run(main())
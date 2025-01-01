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
import yaml

from search_handler import handle_search_query
from url_handler import extract_urls_from_text, fetch_urls_content
from rephraser_handler import rephrase_query
from query_splitter_handler import split_query
from google_lens_handler import get_google_lens_results, process_google_lens_results

from discord.ui import View, Button
from discord import File
import io

from api_key_manager import APIKeyManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)

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


def get_config(filename="config.yaml"):
    with open(filename, "r") as file:
        return yaml.safe_load(file)


cfg = get_config()
api_key_manager = APIKeyManager(cfg)

if client_id := cfg["client_id"]:
    logging.info(
        f"\n\nBOT INVITE URL:\nhttps://discord.com/api/oauth2/authorize?client_id={client_id}&permissions=412317273088&scope=bot\n"
    )

intents = discord.Intents.default()
intents.message_content = True
activity = discord.Game(
    name=(cfg["status_message"] or "https://github.com/anojndr/llmcord")[:128]
)
discord_client = discord.Client(intents=intents, activity=activity)

httpx_client = httpx.AsyncClient()

msg_nodes = {}
last_task_time = None


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

    internet_used: bool = False


class OutputView(View):
    def __init__(self, contents):
        super().__init__()
        self.contents = contents

    @discord.ui.button(label="Get Output as Text File", style=discord.ButtonStyle.primary)
    async def send_text_file(self, interaction: discord.Interaction, button: discord.ui.Button):
        full_content = "".join(self.contents)
        file = io.StringIO(full_content)
        await interaction.response.send_message(
            content="Here is the output as a text file:",
            file=File(file, filename="output.txt"),
            ephemeral=True
        )
        button.disabled = True
        await interaction.message.edit(view=self)


@discord_client.event
async def on_message(new_msg):
    global msg_nodes, last_task_time

    is_dm = new_msg.channel.type == discord.ChannelType.private

    at_ai_pattern = r'\bat ai\b'

    if (
        not is_dm and
        not re.search(at_ai_pattern, new_msg.content.lower()) and
        discord_client.user not in new_msg.mentions
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

    progress_message = await new_msg.channel.send("Processing your request...")

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

        # Initialize messages list
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
                await progress_message.edit(content="Please attach an image for the Google Lens search.")
                return

            image_attachment = new_msg.attachments[0]
            image_url = image_attachment.url

            serpapi_api_key = await api_key_manager.get_next_api_key('serpapi')
            if not serpapi_api_key:
                await progress_message.edit(content='No SerpApi API key available.')
                return

            try:
                lens_results = await get_google_lens_results(image_url, api_key_manager)
            except Exception as e:
                await progress_message.edit(content=f"Error calling Google Lens API: {e}")
                return

            formatted_lens_results = await process_google_lens_results(lens_results, cfg, api_key_manager)

            augmented_user_message = user_message_content + "\n\nRespond to my query based on the google lens results:\n" + formatted_lens_results

            new_user_message = {
                'role': 'user',
                'content': augmented_user_message
            }
            messages.append(new_user_message)

            msg_nodes[new_msg.id].text = augmented_user_message
            msg_nodes[new_msg.id].internet_used = True
        else:
            urls_in_message = extract_urls_from_text(new_msg.content)
            is_url_query = False
            augmented_user_message = None
            if urls_in_message:
                contents = await fetch_urls_content(urls_in_message, api_key_manager, config=cfg)
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
                        await progress_message.edit(content='No Serper API key available.')
                        return

                    msg_nodes[new_msg.id].serper_queries = split_queries
                    msg_nodes[new_msg.id].internet_used = True

                    search_results_list = await asyncio.gather(
                        *[handle_search_query(q, api_key_manager, config=cfg) for q in split_queries]
                    )

                    search_results = ""
                    for idx, (query, result) in enumerate(zip(split_queries, search_results_list), start=1):
                        search_results += f"Results for query {idx} ('{query}'):\n{result}\n\n"

                    augmented_user_message = new_msg.content + "\n\nRespond to my query based on the search results:\n" + search_results

            new_user_message = {
                'role': 'user',
                'content': augmented_user_message
            }
            messages.append(new_user_message)

            msg_nodes[new_msg.id].text = augmented_user_message
            msg_nodes[new_msg.id].internet_used = True

        # Generate and send response message(s)
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

                            view = OutputView(response_contents)

                            if response_msgs == []:
                                response_msg = await progress_message.edit(
                                    content=None, embed=embed, view=view
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
                                    embed=embed, view=view, mention_author=False
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
                                response_msgs[-1].edit(embed=embed, view=view)
                            )
                            last_task_time = dt.now().timestamp()

                prev_chunk = curr_chunk

            if use_plain_responses:
                view = OutputView(response_contents)

                for content in response_contents:
                    if response_msgs == []:
                        response_msg = await progress_message.edit(
                            content=content, view=view, suppress_embeds=True
                        )
                        msg_nodes[response_msg.id] = MsgNode(next_msg=new_msg)
                        await msg_nodes[response_msg.id].lock.acquire()
                        response_msgs.append(response_msg)
                    else:
                        reply_to_msg = response_msgs[-1]
                        response_msg = await reply_to_msg.reply(
                            content=content, view=view, suppress_embeds=True, mention_author=False
                        )
                        msg_nodes[response_msg.id] = MsgNode(next_msg=new_msg)
                        await msg_nodes[response_msg.id].lock.acquire()
                        response_msgs.append(response_msg)
        except Exception:
            logging.exception("Error while generating response")
            await progress_message.edit(content="An error occurred while processing your request.")

        for response_msg in response_msgs:
            msg_nodes[response_msg.id].text = "".join(response_contents)
            msg_nodes[response_msg.id].lock.release()

        # Delete oldest MsgNodes from the cache
        if (num_nodes := len(msg_nodes)) > MAX_MESSAGE_NODES:
            for msg_id in sorted(msg_nodes.keys())[: num_nodes - MAX_MESSAGE_NODES]:
                async with msg_nodes.setdefault(msg_id, MsgNode()).lock:
                    msg_nodes.pop(msg_id, None)

    except Exception:
        logging.exception("Error in on_message handler")
        await progress_message.edit(content="An error occurred while processing your request.")
        return


async def main():
    await discord_client.start(cfg["bot_token"])


asyncio.run(main())
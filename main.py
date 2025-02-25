"""
Main Module

This is the entry point for the llmcord application.
It sets up the Discord bot and starts it with the appropriate configuration.
"""

import asyncio
import logging
import discord
from discord import Game
from utils.keep_alive import keep_alive
from config.config_manager import get_config
from core.bot_client import BotClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)

async def main() -> None:
    """
    Main entry point for the application.
    """
    # Keep the server alive (for hosted environments)
    keep_alive()
    
    # Set up Discord bot
    cfg = get_config()
    intents: discord.Intents = discord.Intents.default()
    intents.message_content = True
    
    activity: Game = Game(
        name=(cfg["status_message"] or "https://github.com/anojndr/llmcord-search-engine")[:128]
    )
    
    discord_client: BotClient = BotClient(intents=intents, activity=activity)
    
    try:
        await discord_client.start(cfg["bot_token"])
    finally:
        await discord_client.close()

if __name__ == "__main__":
    asyncio.run(main())
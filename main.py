"""
Main Module

This is the entry point for the llmcord application.
It sets up the Discord bot and starts it with the appropriate configuration.
"""

import asyncio
import logging

import discord
from discord import Game

from config.config_manager import get_config
from core.bot_client import BotClient
from logging_config import setup_logging
from utils.keep_alive import keep_alive

# Initialize logging
setup_logging("INFO")

# Define logger for this module
logger = logging.getLogger(__name__)


async def main() -> None:
    """
    Main entry point for the application.
    Sets up and runs the Discord bot with configuration from environment.
    """
    # Keep the server alive (for hosted environments)
    keep_alive()
    
    # Set up Discord bot
    cfg = get_config()
    intents = discord.Intents.default()
    intents.message_content = True
    
    status_message = (cfg["status_message"] or 
                      "https://github.com/anojndr/llmcord-search-engine")
    activity = Game(name=status_message[:128])
    
    discord_client = BotClient(intents=intents, activity=activity)
    
    try:
        if not cfg["bot_token"]:
            logger.critical("Missing bot token in configuration")
            raise ValueError(
                "Bot token is required but not provided in configuration"
            )
        
        logger.info("Starting Discord bot with provided configuration")
        await discord_client.start(cfg["bot_token"])
    except Exception as e:
        logger.critical(f"Failed to start Discord bot: {str(e)}", exc_info=True)
        raise
    finally:
        logger.info("Closing Discord client")
        await discord_client.close()


if __name__ == "__main__":
    asyncio.run(main())
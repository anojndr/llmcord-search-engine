"""
Commands Setup Module

This module handles setting up all slash commands for the Discord bot.
"""

import logging
from typing import Dict, Any

import discord
from discord import app_commands

from config.api_key_manager import APIKeyManager
from commands.generateimage_command import setup_generateimage_command
from commands.model_command import setup_model_command

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class CommandManager:
    """Manager for Discord slash commands."""
    
    def __init__(
        self, 
        client: discord.Client, 
        api_key_manager: APIKeyManager
    ):
        """
        Initialize the command manager.
        
        Args:
            client: Discord client instance
            api_key_manager: API key manager instance
        """
        self.client = client
        self.api_key_manager = api_key_manager
        self.commands = {}
        
        # Create a single command tree for the client
        logger.info("Creating command tree for Discord client")
        self.tree = app_commands.CommandTree(client)
        
        # Initialize commands with the shared command tree
        logger.info("Initializing slash commands")
        self.generate_image_command = setup_generateimage_command(
            client, 
            api_key_manager, 
            self.tree
        )
        self.model_command = setup_model_command(
            client, 
            api_key_manager, 
            self.tree
        )
    
    async def sync_commands(self) -> None:
        """Synchronize all commands with Discord."""
        try:
            logger.info("Syncing commands with Discord")
            await self.tree.sync()
            logger.info("All commands synchronized successfully")
        except Exception as e:
            logger.error(f"Error syncing commands: {e}", exc_info=True)
            raise


def setup_commands(
    client: discord.Client, 
    api_key_manager: APIKeyManager
) -> CommandManager:
    """
    Set up all commands for the Discord bot.
    
    Args:
        client: Discord client instance
        api_key_manager: API key manager instance
    
    Returns:
        Command manager instance
    """
    logger.info("Setting up Discord slash commands")
    manager = CommandManager(client, api_key_manager)
    return manager
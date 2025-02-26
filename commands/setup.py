"""
Commands Setup Module

This module handles setting up all slash commands for the Discord bot.
"""

import discord
import logging
from typing import Dict, Any

from config.api_key_manager import APIKeyManager
from commands.generateimage_command import setup_generateimage_command

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class CommandManager:
    """Manager for Discord slash commands."""
    
    def __init__(self, client: discord.Client, api_key_manager: APIKeyManager):
        """
        Initialize the command manager.
        
        Args:
            client: Discord client instance
            api_key_manager: API key manager instance
        """
        self.client = client
        self.api_key_manager = api_key_manager
        self.commands = {}
        
        # Initialize commands
        self.generate_image_command = setup_generateimage_command(client, api_key_manager)
    
    async def sync_commands(self) -> None:
        """Synchronize all commands with Discord."""
        await self.generate_image_command.sync_commands()
        logger.info("All commands synchronized")

def setup_commands(client: discord.Client, api_key_manager: APIKeyManager) -> CommandManager:
    """
    Set up all commands for the Discord bot.
    
    Args:
        client: Discord client instance
        api_key_manager: API key manager instance
    
    Returns:
        Command manager instance
    """
    manager = CommandManager(client, api_key_manager)
    return manager
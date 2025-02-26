"""
Generate Image Command Module

This module implements the /generateimage Discord slash command.
It registers the command and handles the execution.
"""

import logging
import discord
from discord import app_commands
from typing import Optional, Dict, Any

from config.api_key_manager import APIKeyManager
from images.image_generator import generate_image

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class GenerateImageCommand:
    """Handler for the /generateimage slash command."""
    
    def __init__(self, client: discord.Client, api_key_manager: APIKeyManager, command_tree: app_commands.CommandTree):
        """
        Initialize the command handler.
        
        Args:
            client: Discord client instance
            api_key_manager: API key manager instance
            command_tree: The shared command tree from CommandManager
        """
        self.client = client
        self.api_key_manager = api_key_manager
        self.tree = command_tree
        
        # Register the command
        self.register_command()
    
    def register_command(self) -> None:
        """Register the /generateimage command."""
        
        @self.tree.command(
            name="generateimage",
            description="Generate an image based on a text prompt (format: /generateimage prompt: your prompt here)"
        )
        async def generateimage(interaction: discord.Interaction, prompt: str) -> None:
            """
            Generate an image based on a text prompt.
            
            Args:
                interaction: Discord interaction
                prompt: Text prompt for image generation
            """
            # Defer response to give time for image generation
            await interaction.response.defer(thinking=True)
            
            # Check if prompt is provided
            if not prompt:
                await interaction.followup.send(
                    "Please provide a prompt for the image. Format: `/generateimage prompt: your prompt here`",
                    ephemeral=True
                )
                return
            
            # Strip "prompt:" prefix if used
            if prompt.lower().startswith("prompt:"):
                prompt = prompt[7:].lstrip()
            
            try:
                # Get API key
                api_key = await self.get_api_key()
                
                # Generate the image
                success, result, _ = await generate_image(
                    prompt=prompt,
                    httpx_client=self.client.httpx_client,
                    api_key=api_key
                )
                
                if success:
                    # Create an embed with the image
                    embed = discord.Embed(
                        title="Generated Image",
                        description=f"Prompt: {prompt}",
                        color=discord.Color.blue()
                    )
                    embed.set_image(url=result)
                    
                    # Send the image
                    await interaction.followup.send(embed=embed)
                else:
                    # Send error message
                    await interaction.followup.send(
                        f"Failed to generate image: {result}",
                        ephemeral=True
                    )
            
            except Exception as e:
                logger.exception(f"Error in generateimage command: {e}")
                await interaction.followup.send(
                    f"An error occurred: {str(e)}",
                    ephemeral=True
                )
    
    async def get_api_key(self) -> Optional[str]:
        """
        Get API key for image generation.
        
        Returns:
            API key if available, None otherwise
        """
        try:
            # Try to get from API key manager
            return await self.api_key_manager.get_next_api_key("image_gen")
        except:
            # Fallback to environment variable
            return None

# Function to setup the command
def setup_generateimage_command(client: discord.Client, api_key_manager: APIKeyManager, command_tree: app_commands.CommandTree) -> GenerateImageCommand:
    """
    Set up the /generateimage command.
    
    Args:
        client: Discord client instance
        api_key_manager: API key manager instance
        command_tree: The shared command tree from CommandManager
    
    Returns:
        Command handler instance
    """
    command = GenerateImageCommand(client, api_key_manager, command_tree)
    return command
"""
Model Command Module

This module implements the /model Discord slash command.
It registers the command and handles the execution to set the model and provider.
"""

import logging
import os
from typing import Optional, Dict, Any, List

import discord
from discord import app_commands

from config.config_manager import get_config
from config.api_key_manager import APIKeyManager

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Mapping of providers to their available models
PROVIDER_MODELS = {
    "google": [
        "gemini/gemini-2.0-flash",
        "gemini/gemini-2.0-flash-thinking-exp-01-21",
    ],
    "mistral": [
        "mistral/mistral-large-latest",
        "mistral/pixtral-large-latest",
    ],
    "together_ai": [
        "together_ai/deepseek-ai/DeepSeek-R1-Distill-Llama-70B-free",
    ],
    "xai": [
        "openai/grok-3",
    ],
}


class ModelCommand:
    """Handler for the /model slash command."""
    
    def __init__(
        self, 
        client: discord.Client, 
        api_key_manager: APIKeyManager, 
        command_tree: app_commands.CommandTree
    ):
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
        """Register the /model command."""
        
        @self.tree.command(
            name="model",
            description="Set the provider and model for the bot"
        )
        @app_commands.describe(
            provider="The AI provider to use",
            model="The model from the selected provider"
        )
        async def model(
            interaction: discord.Interaction, 
            provider: str,
            model: str
        ) -> None:
            """
            Set the model and provider for the bot.
            
            Args:
                interaction: Discord interaction
                provider: The AI provider to use
                model: The model to use
            """
            # Defer response to avoid timeout
            await interaction.response.defer(ephemeral=False)
            
            # Check if provider is valid
            if provider not in PROVIDER_MODELS:
                logger.warning(
                    f"Invalid provider '{provider}' requested by "
                    f"{interaction.user.name} ({interaction.user.id})"
                )
                available_providers = ", ".join(PROVIDER_MODELS.keys())
                await interaction.followup.send(
                    f"Invalid provider: {provider}. Available providers: "
                    f"{available_providers}",
                    ephemeral=False
                )
                return
            
            # Check if model is valid for this provider
            if model not in PROVIDER_MODELS[provider]:
                logger.warning(
                    f"Invalid model '{model}' for provider '{provider}' "
                    f"requested by {interaction.user.name} "
                    f"({interaction.user.id})"
                )
                available_models = ", ".join(PROVIDER_MODELS[provider])
                await interaction.followup.send(
                    f"Invalid model: {model} for provider {provider}. "
                    f"Available models: {available_models}",
                    ephemeral=False
                )
                return
            
            # Update current config
            try:
                # Set environment variables
                old_provider = os.environ.get("PROVIDER", "unknown")
                old_model = os.environ.get("MODEL", "unknown")
                
                os.environ["PROVIDER"] = provider
                os.environ["MODEL"] = model
                
                # Force reload of configuration
                from config.config_manager import get_config
                get_config(force_reload=True)
                
                # Send success message
                await interaction.followup.send(
                    f"Provider set to {provider} and model set to {model}.",
                    ephemeral=False
                )
                
                logger.info(
                    f"Model changed from {old_provider}/{old_model} to "
                    f"{provider}/{model} by {interaction.user.name} "
                    f"({interaction.user.id})"
                )
            
            except Exception as e:
                logger.error(
                    f"Error setting model to {provider}/{model}: {e}", 
                    exc_info=True
                )
                await interaction.followup.send(
                    f"An error occurred: {str(e)}",
                    ephemeral=False
                )
        
        # Implement autocomplete for provider parameter
        @model.autocomplete('provider')
        async def provider_autocomplete(
            interaction: discord.Interaction,
            current: str,
        ) -> List[app_commands.Choice[str]]:
            """
            Autocomplete handler for provider parameter.
            
            Args:
                interaction: Discord interaction
                current: Current input string
                
            Returns:
                List of matching provider choices
            """
            providers = list(PROVIDER_MODELS.keys())
            
            # Filter providers based on current input
            filtered = [
                provider for provider in providers 
                if current.lower() in provider.lower()
            ]
            
            # Return up to 25 choices (Discord limit)
            return [
                app_commands.Choice(name=provider, value=provider)
                for provider in filtered[:25]
            ]
        
        # Implement autocomplete for model parameter
        @model.autocomplete('model')
        async def model_autocomplete(
            interaction: discord.Interaction,
            current: str,
        ) -> List[app_commands.Choice[str]]:
            """
            Autocomplete handler for model parameter.
            
            Args:
                interaction: Discord interaction
                current: Current input string
                
            Returns:
                List of matching model choices based on selected provider
            """
            # Get the provider from the interaction options
            provider_option = None
            for option in interaction.data.get('options', []):
                if option.get('name') == 'provider':
                    provider_option = option.get('value')
                    break
            
            # If no provider is selected, return empty list
            if not provider_option or provider_option not in PROVIDER_MODELS:
                return []
            
            # Get models for the selected provider
            models = PROVIDER_MODELS[provider_option]
            
            # Filter models based on current input
            filtered = [
                model for model in models 
                if current.lower() in model.lower()
            ]
            
            # Return up to 25 choices (Discord limit)
            return [
                app_commands.Choice(name=model, value=model)
                for model in filtered[:25]
            ]


def setup_model_command(
    client: discord.Client, 
    api_key_manager: APIKeyManager, 
    command_tree: app_commands.CommandTree
) -> ModelCommand:
    """
    Set up the /model command.
    
    Args:
        client: Discord client instance
        api_key_manager: API key manager instance
        command_tree: The shared command tree from CommandManager
    
    Returns:
        Command handler instance
    """
    logger.info("Setting up /model command")
    command = ModelCommand(client, api_key_manager, command_tree)
    return command
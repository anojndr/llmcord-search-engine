"""
API Key Manager Module

This module defines the APIKeyManager class to manage API keys for different providers.
It loads keys from a configuration, maintains counters per provider, and provides an 
asynchronous method to retrieve the next key in a round-robin fashion.
"""

import asyncio
from collections import defaultdict

class APIKeyManager:
    def __init__(self, config):
        """
        Initialize the APIKeyManager instance with a configuration dictionary.

        Args:
            config (dict): Dictionary containing API keys per provider and other settings.
        """
        self.config = config
        # A dictionary mapping service names to asyncio locks to avoid concurrent key updates
        self.locks = defaultdict(asyncio.Lock)
        # Holds list of API keys per provider
        self.providers_keys = {}
        # Keeps track of which key to use next for each provider
        self.index_counters = {}

        # Process providers keys from the configuration
        for provider, details in config.get('providers', {}).items():
            api_keys = details.get('api_keys', [])
            if api_keys:
                self.providers_keys[provider] = api_keys
                self.index_counters[provider] = 0

        # Additional providers are handled outside of the 'providers' dict
        self.serper_api_keys = config.get('serper_api_keys', [])
        self.serpapi_api_keys = config.get('serpapi_api_keys', [])
        self.youtube_api_keys = config.get('youtube_api_keys', [])
        if self.serper_api_keys:
            self.index_counters['serper'] = 0
        if self.serpapi_api_keys:
            self.index_counters['serpapi'] = 0
        if self.youtube_api_keys:
            self.index_counters['youtube'] = 0

    async def get_next_api_key(self, service_name):
        """
        Asynchronously retrieve and rotate the API key for the given service.

        Args:
            service_name (str): The name of the service/provider for which to retrieve the key.

        Returns:
            str or None: The next API key available or None if not found.
        """
        async with self.locks[service_name]:
            keys = []
            # Check the configured providers keys first
            if service_name in self.providers_keys:
                keys = self.providers_keys[service_name]
            # Alternatively, check additional providers
            elif service_name == 'serper':
                keys = self.serper_api_keys
            elif service_name == 'serpapi':
                keys = self.serpapi_api_keys
            elif service_name == 'youtube':
                keys = self.youtube_api_keys

            if not keys:
                return None

            # Get the current index and rotate to the next key
            index = self.index_counters[service_name]
            key = keys[index]
            self.index_counters[service_name] = (index + 1) % len(keys)
            return key
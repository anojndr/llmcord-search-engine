"""
API Key Manager Module

This module defines the APIKeyManager class to manage API keys for different providers.
It loads keys from a configuration, maintains counters per provider, and provides an 
asynchronous method to retrieve the next key in a round-robin fashion.
"""

import asyncio
from collections import defaultdict
from typing import Dict, List, Optional, Any

class APIKeyManager:
    config: Dict[str, Any]
    locks: 'defaultdict[str, asyncio.Lock]'
    providers_keys: Dict[str, List[str]]
    index_counters: Dict[str, int]
    serper_api_keys: List[str]
    serpapi_api_keys: List[str]
    youtube_api_keys: List[str]
    saucenao_api_keys: List[str]

    def __init__(self, config: Dict[str, Any]) -> None:
        """
        Initialize the APIKeyManager instance with a configuration dictionary.

        Args:
            config: Dictionary containing API keys per provider and other settings.
        """
        self.config = config
        self.locks = defaultdict(asyncio.Lock)
        self.providers_keys = {}
        self.index_counters = {}

        for provider, details in config.get('providers', {}).items():
            api_keys: List[str] = details.get('api_keys', [])
            if api_keys:
                self.providers_keys[provider] = api_keys
                self.index_counters[provider] = 0

        self.serper_api_keys = config.get('serper_api_keys', [])
        self.serpapi_api_keys = config.get('serpapi_api_keys', [])
        self.youtube_api_keys = config.get('youtube_api_keys', [])
        self.saucenao_api_keys = config.get('saucenao_api_keys', [])
        if self.serper_api_keys:
            self.index_counters['serper'] = 0
        if self.serpapi_api_keys:
            self.index_counters['serpapi'] = 0
        if self.youtube_api_keys:
            self.index_counters['youtube'] = 0
        if self.saucenao_api_keys:
            self.index_counters['saucenao'] = 0

    async def get_next_api_key(self, service_name: str) -> Optional[str]:
        """
        Asynchronously retrieve and rotate the API key for the given service.

        Args:
            service_name: The name of the service/provider for which to retrieve the key.

        Returns:
            The next API key available or None if not found.
        """
        async with self.locks[service_name]:
            keys: List[str] = []
            if service_name in self.providers_keys:
                keys = self.providers_keys[service_name]
            elif service_name == 'serper':
                keys = self.serper_api_keys
            elif service_name == 'serpapi':
                keys = self.serpapi_api_keys
            elif service_name == 'youtube':
                keys = self.youtube_api_keys
            elif service_name == 'saucenao':
                keys = self.saucenao_api_keys

            if not keys:
                return None

            index: int = self.index_counters[service_name]
            key: str = keys[index]
            self.index_counters[service_name] = (index + 1) % len(keys)
            return key
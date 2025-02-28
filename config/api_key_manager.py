"""
API Key Manager Module

This module defines the APIKeyManager class to manage API keys for different providers.
It loads keys from a configuration, maintains counters per provider, and provides an 
asynchronous method to retrieve the next key in a round-robin fashion.
"""

import asyncio
import logging
from collections import defaultdict
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class APIKeyManager:
    config: Dict[str, Any]
    locks: 'defaultdict[str, asyncio.Lock]'
    providers_keys: Dict[str, List[str]]
    index_counters: Dict[str, int]
    serper_api_keys: List[str]
    serpapi_api_keys: List[str]
    youtube_api_keys: List[str]
    image_gen_api_keys: List[str]
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

        logger.info("Initializing API key manager")

        for provider, details in config.get('providers', {}).items():
            api_keys: List[str] = details.get('api_keys', [])
            # Filter out empty keys
            api_keys = [key for key in api_keys if key.strip()]
            
            if api_keys:
                self.providers_keys[provider] = api_keys
                self.index_counters[provider] = 0
                logger.info(f"Loaded {len(api_keys)} API keys for provider '{provider}'")
            else:
                logger.warning(f"No API keys found for provider '{provider}'")

        # Load special service API keys
        self.serper_api_keys = [key for key in config.get('serper_api_keys', []) if key.strip()]
        self.serpapi_api_keys = [key for key in config.get('serpapi_api_keys', []) if key.strip()]
        self.youtube_api_keys = [key for key in config.get('youtube_api_keys', []) if key.strip()]
        self.image_gen_api_keys = [key for key in config.get('image_gen_api_keys', []) if key.strip()]
        self.saucenao_api_keys = [key for key in config.get('saucenao_api_keys', []) if key.strip()]
        
        # Initialize counters for services with keys
        if self.serper_api_keys:
            self.index_counters['serper'] = 0
            logger.info(f"Loaded {len(self.serper_api_keys)} API keys for Serper service")
        else:
            logger.warning("No API keys found for Serper service")
            
        if self.serpapi_api_keys:
            self.index_counters['serpapi'] = 0
            logger.info(f"Loaded {len(self.serpapi_api_keys)} API keys for SerpAPI service")
        else:
            logger.warning("No API keys found for SerpAPI service")
            
        if self.youtube_api_keys:
            self.index_counters['youtube'] = 0
            logger.info(f"Loaded {len(self.youtube_api_keys)} API keys for YouTube service")
        else:
            logger.warning("No API keys found for YouTube service")
            
        if self.image_gen_api_keys:
            self.index_counters['image_gen'] = 0
            logger.info(f"Loaded {len(self.image_gen_api_keys)} API keys for image generation service")
        else:
            logger.warning("No API keys found for image generation service")
            
        if self.saucenao_api_keys:
            self.index_counters['saucenao'] = 0
            logger.info(f"Loaded {len(self.saucenao_api_keys)} API keys for SauceNAO service")
        else:
            logger.warning("No API keys found for SauceNAO service")

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
            elif service_name == 'image_gen':
                keys = self.image_gen_api_keys
            elif service_name == 'saucenao':
                keys = self.saucenao_api_keys

            if not keys:
                logger.warning(f"No API keys available for service '{service_name}'")
                return None

            index: int = self.index_counters[service_name]
            key: str = keys[index]
            self.index_counters[service_name] = (index + 1) % len(keys)
            logger.debug(f"Returning API key #{index+1}/{len(keys)} for service '{service_name}'")
            return key
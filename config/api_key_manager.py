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
    """
    Manages API keys for various services and providers.
    
    This class loads API keys from configuration, maintains rotation counters,
    and provides methods to retrieve keys in a round-robin fashion.
    """
    
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

        # Load provider keys
        for provider, details in config.get('providers', {}).items():
            api_keys = details.get('api_keys', [])
            # Filter out empty keys
            api_keys = [key for key in api_keys if key.strip()]
            
            if api_keys:
                self.providers_keys[provider] = api_keys
                self.index_counters[provider] = 0
                logger.info(
                    f"Loaded {len(api_keys)} API keys for provider '{provider}'"
                )
            else:
                logger.warning(f"No API keys found for provider '{provider}'")

        # Load special service API keys
        self._load_service_keys(config)
    
    def _load_service_keys(self, config: Dict[str, Any]) -> None:
        """
        Load API keys for special services from configuration.
        
        Args:
            config: Configuration dictionary containing service API keys
        """
        # Define services and their configuration keys
        services = {
            'serper': 'serper_api_keys',
            'serpapi': 'serpapi_api_keys',
            'youtube': 'youtube_api_keys',
            'image_gen': 'image_gen_api_keys',
            'saucenao': 'saucenao_api_keys'
        }
        
        # Load each service's keys
        for service_name, config_key in services.items():
            keys = [key for key in config.get(config_key, []) if key.strip()]
            setattr(self, f"{service_name}_api_keys", keys)
            
            if keys:
                self.index_counters[service_name] = 0
                logger.info(
                    f"Loaded {len(keys)} API keys for {service_name} service"
                )
            else:
                logger.warning(f"No API keys found for {service_name} service")

    async def get_next_api_key(self, service_name: str) -> Optional[str]:
        """
        Asynchronously retrieve and rotate the API key for the given service.

        Args:
            service_name: The name of the service/provider for which to retrieve the key.

        Returns:
            The next API key available or None if not found.
        """
        async with self.locks[service_name]:
            # Get the list of keys for the requested service
            keys: List[str] = []
            
            if service_name in self.providers_keys:
                keys = self.providers_keys[service_name]
            elif hasattr(self, f"{service_name}_api_keys"):
                keys = getattr(self, f"{service_name}_api_keys")
            
            if not keys:
                logger.warning(
                    f"No API keys available for service '{service_name}'"
                )
                return None

            # Get the next key in rotation
            index = self.index_counters[service_name]
            key = keys[index]
            
            # Update the counter for next time
            self.index_counters[service_name] = (index + 1) % len(keys)
            
            logger.debug(
                f"Returning API key #{index+1}/{len(keys)} for service "
                f"'{service_name}'"
            )
            return key
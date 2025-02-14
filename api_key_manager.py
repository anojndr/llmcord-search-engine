import asyncio
from collections import defaultdict

class APIKeyManager:
    def __init__(self, config):
        self.config = config
        self.locks = defaultdict(asyncio.Lock)
        self.providers_keys = {}
        self.index_counters = {}

        for provider, details in config.get('providers', {}).items():
            api_keys = details.get('api_keys', [])
            if api_keys:
                self.providers_keys[provider] = api_keys
                self.index_counters[provider] = 0

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
        async with self.locks[service_name]:
            keys = []
            if service_name in self.providers_keys:
                keys = self.providers_keys[service_name]
            elif service_name == 'serper':
                keys = self.serper_api_keys
            elif service_name == 'serpapi':
                keys = self.serpapi_api_keys
            elif service_name == 'youtube':
                keys = self.youtube_api_keys

            if not keys:
                return None

            index = self.index_counters[service_name]
            key = keys[index]
            self.index_counters[service_name] = (index + 1) % len(keys)
            return key
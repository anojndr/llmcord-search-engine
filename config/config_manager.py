"""
Configuration Manager Module

This module handles loading and managing configuration for the application.
It loads environment variables and provides a structured configuration object.
"""

import os
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

def get_config() -> Dict[str, Any]:
    """
    Load configuration from environment variables.
    
    Returns:
        A dictionary containing the application configuration.
    """
    logger.info("Loading application configuration")
    
    try:
        with open('system_prompt.txt', 'r', encoding='utf-8') as f:
            system_prompt: str = f.read()
            logger.info("Successfully loaded system_prompt.txt")
    except FileNotFoundError:
        logger.warning("system_prompt.txt not found, using default system prompt")
        system_prompt: str = ("You are a helpful assistant. Cite the most relevant search results as needed to answer the "
                             "question, avoiding irrelevant ones. Write only the response and use markdown for formatting. "
                             "Include a clickable hyperlink at the end of the corresponding sentence using the site name.")

    # Bot token and client ID validation
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        logger.warning("BOT_TOKEN environment variable is not set!")
        
    client_id = os.getenv("CLIENT_ID")
    if not client_id:
        logger.warning("CLIENT_ID environment variable is not set!")

    # Parse allowed channels, roles, and blocked users
    allowed_channel_ids_str = os.getenv("ALLOWED_CHANNEL_IDS", "")
    allowed_role_ids_str = os.getenv("ALLOWED_ROLE_IDS", "")
    blocked_user_ids_str = os.getenv("BLOCKED_USER_IDS", "")
    
    allowed_channel_ids = []
    if allowed_channel_ids_str:
        try:
            allowed_channel_ids = list(map(int, allowed_channel_ids_str.split(",")))
        except ValueError:
            logger.error("Invalid ALLOWED_CHANNEL_IDS format. Expected comma-separated integers.")
            allowed_channel_ids = []
    
    allowed_role_ids = []
    if allowed_role_ids_str:
        try:
            allowed_role_ids = list(map(int, allowed_role_ids_str.split(",")))
        except ValueError:
            logger.error("Invalid ALLOWED_ROLE_IDS format. Expected comma-separated integers.")
            allowed_role_ids = []
    
    blocked_user_ids = []
    if blocked_user_ids_str:
        try:
            blocked_user_ids = list(map(int, blocked_user_ids_str.split(",")))
        except ValueError:
            logger.error("Invalid BLOCKED_USER_IDS format. Expected comma-separated integers.")
            blocked_user_ids = []

    # Parse numeric settings with validation
    try:
        max_text = int(os.getenv("MAX_TEXT", "100000"))
        if max_text <= 0:
            logger.warning("MAX_TEXT must be positive, defaulting to 100000")
            max_text = 100000
    except ValueError:
        logger.error("Invalid MAX_TEXT value, defaulting to 100000")
        max_text = 100000
        
    try:
        max_images = int(os.getenv("MAX_IMAGES", "5"))
        if max_images < 0:
            logger.warning("MAX_IMAGES must be non-negative, defaulting to 5")
            max_images = 5
    except ValueError:
        logger.error("Invalid MAX_IMAGES value, defaulting to 5")
        max_images = 5
        
    try:
        max_messages = int(os.getenv("MAX_MESSAGES", "25"))
        if max_messages <= 0:
            logger.warning("MAX_MESSAGES must be positive, defaulting to 25")
            max_messages = 25
    except ValueError:
        logger.error("Invalid MAX_MESSAGES value, defaulting to 25")
        max_messages = 25
        
    try:
        max_urls = int(os.getenv("MAX_URLS", "5"))
        if max_urls <= 0:
            logger.warning("MAX_URLS must be positive, defaulting to 5")
            max_urls = 5
    except ValueError:
        logger.error("Invalid MAX_URLS value, defaulting to 5")
        max_urls = 5

    # Float parameters with validation
    try:
        temperature = float(os.getenv("EXTRA_API_PARAMETERS_TEMPERATURE", "1"))
        if not (0 <= temperature <= 2):
            logger.warning("TEMPERATURE should be between 0 and 2, defaulting to 1")
            temperature = 1
    except ValueError:
        logger.error("Invalid TEMPERATURE value, defaulting to 1")
        temperature = 1
        
    try:
        top_p = float(os.getenv("EXTRA_API_PARAMETERS_TOP_P", "1"))
        if not (0 < top_p <= 1):
            logger.warning("TOP_P should be between 0 and 1, defaulting to 1")
            top_p = 1
    except ValueError:
        logger.error("Invalid TOP_P value, defaulting to 1")
        top_p = 1
        
    try:
        max_tokens = int(os.getenv("EXTRA_API_PARAMETERS_MAX_TOKENS", "4096"))
        if max_tokens <= 0:
            logger.warning("MAX_TOKENS must be positive, defaulting to 4096")
            max_tokens = 4096
    except ValueError:
        logger.error("Invalid MAX_TOKENS value, defaulting to 4096")
        max_tokens = 4096

    # Load provider API keys
    provider_configs = {}
    for provider in ["openai", "x-ai", "google", "mistral", "groq", "openrouter", "claude"]:
        env_var = f"{provider.upper().replace('-', '_')}_API_KEYS"
        api_keys = os.getenv(env_var, "").split(",") if os.getenv(env_var) else []
        api_keys = [key for key in api_keys if key.strip()]  # Remove empty keys
        
        if not api_keys:
            logger.warning(f"No API keys found for provider: {provider}")
        else:
            logger.info(f"Loaded {len(api_keys)} API keys for provider: {provider}")
            
        provider_configs[provider] = {
            "api_keys": api_keys,
        }

    # Build and return the config
    config: Dict[str, Any] = {
        "bot_token": bot_token,
        "client_id": client_id,
        "status_message": os.getenv("STATUS_MESSAGE"),
        "allow_dms": os.getenv("ALLOW_DMS", "true").lower() == "true",
        "allowed_channel_ids": allowed_channel_ids,
        "allowed_role_ids": allowed_role_ids,
        "blocked_user_ids": blocked_user_ids,
        "max_text": max_text,
        "max_images": max_images,
        "max_messages": max_messages,
        "use_plain_responses": os.getenv("USE_PLAIN_RESPONSES", "false").lower() == "true",
        "providers": provider_configs,
        "provider": os.getenv("PROVIDER", "openai"),
        "model": os.getenv("MODEL", "gpt-4"),
        "extra_api_parameters": {
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
        },
        "rephraser_provider": os.getenv("REPHRASER_PROVIDER", "openai"),
        "rephraser_model": os.getenv("REPHRASER_MODEL", "gpt-4"),
        "rephraser_extra_api_parameters": {
            "temperature": float(os.getenv("REPHRASER_EXTRA_API_PARAMETERS_TEMPERATURE", "1")),
            "top_p": float(os.getenv("REPHRASER_EXTRA_API_PARAMETERS_TOP_P", "1")),
            "max_tokens": int(os.getenv("REPHRASER_EXTRA_API_PARAMETERS_MAX_TOKENS", "4096")),
        },
        "query_splitter_provider": os.getenv("QUERY_SPLITTER_PROVIDER", "openai"),
        "query_splitter_model": os.getenv("QUERY_SPLITTER_MODEL", "gpt-4"),
        "query_splitter_extra_api_parameters": {
            "temperature": float(os.getenv("QUERY_SPLITTER_EXTRA_API_PARAMETERS_TEMPERATURE", "1")),
            "top_p": float(os.getenv("QUERY_SPLITTER_EXTRA_API_PARAMETERS_TOP_P", "1")),
            "max_tokens": int(os.getenv("QUERY_SPLITTER_EXTRA_API_PARAMETERS_MAX_TOKENS", "4096")),
        },
        "system_prompt": system_prompt,
        "serper_api_keys": os.getenv("SERPER_API_KEYS", "").split(",") if os.getenv("SERPER_API_KEYS") else [],
        "serpapi_api_keys": os.getenv("SERPAPI_API_KEYS", "").split(",") if os.getenv("SERPAPI_API_KEYS") else [],
        "youtube_api_keys": os.getenv("YOUTUBE_API_KEYS", "").split(",") if os.getenv("YOUTUBE_API_KEYS") else [],
        "saucenao_api_keys": os.getenv("SAUCENAO_API_KEYS", "").split(",") if os.getenv("SAUCENAO_API_KEYS") else [],
        "max_urls": max_urls,
        "image_gen_api_keys": os.getenv("IMAGE_GEN_API_KEYS", "").split(",") if os.getenv("IMAGE_GEN_API_KEYS") else [],
    }
    
    logger.info(f"Configuration loaded successfully. Using provider: {config['provider']}, model: {config['model']}")
    return config
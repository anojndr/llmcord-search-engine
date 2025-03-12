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

# Cache for storing the loaded configuration
_cached_config = None


def get_config(force_reload: bool = False) -> Dict[str, Any]:
    """
    Load configuration from environment variables.
    
    Args:
        force_reload: If True, force reload the configuration even if cached.
    
    Returns:
        A dictionary containing the application configuration.
    """
    global _cached_config
    
    # If we have a cached config and don't need to force reload, use it
    if _cached_config is not None and not force_reload:
        return _cached_config
    
    logger.info("Loading application configuration")
    
    # Load system prompt
    system_prompt = _load_system_prompt()
    
    # Load bot configuration
    bot_config = _load_bot_config()
    
    # Load permission and restriction settings
    permission_config = _load_permission_config()
    
    # Load message limit settings
    limits_config = _load_limit_config()
    
    # Load API configurations
    api_config = _load_api_config()
    
    # Load search settings
    search_config = _load_search_config()
    
    # Build and return the full config
    config = {
        **bot_config,
        **permission_config,
        **limits_config,
        **api_config,
        "system_prompt": system_prompt,
        **search_config,
    }
    
    logger.info(
        f"Configuration loaded successfully. Using provider: "
        f"{config['provider']}, model: {config['model']}"
    )
    
    # Cache the config for future use
    _cached_config = config
    
    return config


def _load_system_prompt() -> str:
    """
    Load system prompt from file or use default.
    
    Returns:
        System prompt string
    """
    try:
        with open('system_prompt.txt', 'r', encoding='utf-8') as f:
            system_prompt = f.read()
            logger.info("Successfully loaded system_prompt.txt")
    except FileNotFoundError:
        logger.warning("system_prompt.txt not found, using default system prompt")
        system_prompt = (
            "You are a helpful assistant. Cite the most relevant search "
            "results as needed to answer the question, avoiding irrelevant "
            "ones. Write only the response and use markdown for formatting. "
            "Include a clickable hyperlink at the end of the corresponding "
            "sentence using the site name."
        )
    
    return system_prompt


def _load_bot_config() -> Dict[str, Any]:
    """
    Load bot configuration settings.
    
    Returns:
        Dictionary with bot configuration
    """
    # Bot token and client ID validation
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        logger.warning("BOT_TOKEN environment variable is not set!")
        
    client_id = os.getenv("CLIENT_ID")
    if not client_id:
        logger.warning("CLIENT_ID environment variable is not set!")
    
    return {
        "bot_token": bot_token,
        "client_id": client_id,
        "status_message": os.getenv("STATUS_MESSAGE"),
        "allow_dms": os.getenv("ALLOW_DMS", "true").lower() == "true",
        "use_plain_responses": os.getenv(
            "USE_PLAIN_RESPONSES", "false"
        ).lower() == "true",
    }


def _load_permission_config() -> Dict[str, Any]:
    """
    Load permission and restriction settings.
    
    Returns:
        Dictionary with permission settings
    """
    # Parse allowed channels, roles, and blocked users
    allowed_channel_ids_str = os.getenv("ALLOWED_CHANNEL_IDS", "")
    allowed_role_ids_str = os.getenv("ALLOWED_ROLE_IDS", "")
    blocked_user_ids_str = os.getenv("BLOCKED_USER_IDS", "")
    
    allowed_channel_ids = _parse_id_list(
        allowed_channel_ids_str, 
        "ALLOWED_CHANNEL_IDS"
    )
    allowed_role_ids = _parse_id_list(
        allowed_role_ids_str, 
        "ALLOWED_ROLE_IDS"
    )
    blocked_user_ids = _parse_id_list(
        blocked_user_ids_str, 
        "BLOCKED_USER_IDS"
    )
    
    return {
        "allowed_channel_ids": allowed_channel_ids,
        "allowed_role_ids": allowed_role_ids,
        "blocked_user_ids": blocked_user_ids,
    }


def _parse_id_list(id_str: str, var_name: str) -> List[int]:
    """
    Parse a comma-separated string of IDs into a list of integers.
    
    Args:
        id_str: Comma-separated string of IDs
        var_name: Name of the variable (for error logging)
    
    Returns:
        List of parsed integer IDs
    """
    id_list = []
    if id_str:
        try:
            id_list = list(map(int, id_str.split(",")))
        except ValueError:
            logger.error(
                f"Invalid {var_name} format. Expected comma-separated integers."
            )
    return id_list


def _load_limit_config() -> Dict[str, Any]:
    """
    Load message limit settings.
    
    Returns:
        Dictionary with limit settings
    """
    # Parse numeric settings with validation
    max_text = _parse_positive_int(
        os.getenv("MAX_TEXT", "100000"), 
        "MAX_TEXT", 
        100000
    )
    max_images = _parse_non_negative_int(
        os.getenv("MAX_IMAGES", "5"), 
        "MAX_IMAGES", 
        5
    )
    max_messages = _parse_positive_int(
        os.getenv("MAX_MESSAGES", "25"), 
        "MAX_MESSAGES", 
        25
    )
    max_urls = _parse_positive_int(
        os.getenv("MAX_URLS", "5"), 
        "MAX_URLS", 
        5
    )
    
    # Float parameters with validation
    temperature = _parse_float_range(
        os.getenv("EXTRA_API_PARAMETERS_TEMPERATURE", "1"), 
        "TEMPERATURE", 
        1, 
        0, 
        2
    )
    top_p = _parse_float_range(
        os.getenv("EXTRA_API_PARAMETERS_TOP_P", "1"), 
        "TOP_P", 
        1, 
        0, 
        1
    )
    
    return {
        "max_text": max_text,
        "max_images": max_images,
        "max_messages": max_messages,
        "max_urls": max_urls,
        "extra_api_parameters": {
            "temperature": temperature,
            "top_p": top_p,
        },
    }


def _parse_positive_int(
    value: str, 
    name: str, 
    default: int
) -> int:
    """
    Parse a string as a positive integer.
    
    Args:
        value: String to parse
        name: Parameter name for logging
        default: Default value if parsing fails
    
    Returns:
        Parsed positive integer
    """
    try:
        result = int(value)
        if result <= 0:
            logger.warning(
                f"{name} must be positive, defaulting to {default}"
            )
            return default
        return result
    except ValueError:
        logger.error(f"Invalid {name} value, defaulting to {default}")
        return default


def _parse_non_negative_int(
    value: str, 
    name: str, 
    default: int
) -> int:
    """
    Parse a string as a non-negative integer.
    
    Args:
        value: String to parse
        name: Parameter name for logging
        default: Default value if parsing fails
    
    Returns:
        Parsed non-negative integer
    """
    try:
        result = int(value)
        if result < 0:
            logger.warning(
                f"{name} must be non-negative, defaulting to {default}"
            )
            return default
        return result
    except ValueError:
        logger.error(f"Invalid {name} value, defaulting to {default}")
        return default


def _parse_float_range(
    value: str, 
    name: str, 
    default: float, 
    min_val: float, 
    max_val: float
) -> float:
    """
    Parse a string as a float within a specific range.
    
    Args:
        value: String to parse
        name: Parameter name for logging
        default: Default value if parsing fails
        min_val: Minimum allowed value
        max_val: Maximum allowed value
    
    Returns:
        Parsed float within range
    """
    try:
        result = float(value)
        if not (min_val <= result <= max_val):
            logger.warning(
                f"{name} should be between {min_val} and {max_val}, "
                f"defaulting to {default}"
            )
            return default
        return result
    except ValueError:
        logger.error(f"Invalid {name} value, defaulting to {default}")
        return default


def _load_api_config() -> Dict[str, Any]:
    """
    Load API configurations for various providers.
    
    Returns:
        Dictionary with API configurations
    """
    # Load provider API keys
    provider_configs = {}
    providers = [
        "openai", "xai", "google", "mistral", "groq", "openrouter", "claude", 
        "together_ai"
    ]
    
    for provider in providers:
        env_var = f"{provider.upper().replace('-', '_')}_API_KEYS"
        api_keys_str = os.getenv(env_var, "")
        api_keys = []
        
        if api_keys_str:
            api_keys = [key for key in api_keys_str.split(",") if key.strip()]
        
        if not api_keys:
            logger.warning(f"No API keys found for provider: {provider}")
        else:
            logger.info(
                f"Loaded {len(api_keys)} API keys for provider: {provider}"
            )
            
        provider_configs[provider] = {
            "api_keys": api_keys,
        }
    
    # Load rephraser and query splitter configurations
    rephraser_config = _load_rephraser_config()
    query_splitter_config = _load_query_splitter_config()
    
    # Special API keys
    special_api_keys = _load_special_api_keys()
    
    return {
        "providers": provider_configs,
        "provider": os.getenv("PROVIDER", "openai"),
        "model": os.getenv("MODEL", "gpt-4"),
        **rephraser_config,
        **query_splitter_config,
        **special_api_keys,
    }


def _load_rephraser_config() -> Dict[str, Any]:
    """
    Load rephraser configuration.
    
    Returns:
        Dictionary with rephraser configuration
    """
    return {
        "rephraser_provider": os.getenv("REPHRASER_PROVIDER", "openai"),
        "rephraser_model": os.getenv("REPHRASER_MODEL", "gpt-4"),
        "rephraser_extra_api_parameters": {
            "temperature": float(os.getenv(
                "REPHRASER_EXTRA_API_PARAMETERS_TEMPERATURE", "1"
            )),
            "top_p": float(os.getenv(
                "REPHRASER_EXTRA_API_PARAMETERS_TOP_P", "1"
            )),
        },
    }


def _load_query_splitter_config() -> Dict[str, Any]:
    """
    Load query splitter configuration.
    
    Returns:
        Dictionary with query splitter configuration
    """
    return {
        "query_splitter_provider": os.getenv(
            "QUERY_SPLITTER_PROVIDER", "openai"
        ),
        "query_splitter_model": os.getenv("QUERY_SPLITTER_MODEL", "gpt-4"),
        "query_splitter_extra_api_parameters": {
            "temperature": float(os.getenv(
                "QUERY_SPLITTER_EXTRA_API_PARAMETERS_TEMPERATURE", "1"
            )),
            "top_p": float(os.getenv(
                "QUERY_SPLITTER_EXTRA_API_PARAMETERS_TOP_P", "1"
            )),
        },
    }


def _load_special_api_keys() -> Dict[str, Any]:
    """
    Load special API keys for services.
    
    Returns:
        Dictionary with special API keys
    """
    special_keys = {}
    special_services = [
        "serper", "serpapi", "youtube", "saucenao", "image_gen"
    ]
    
    for service in special_services:
        env_var = f"{service.upper()}_API_KEYS"
        keys_str = os.getenv(env_var, "")
        
        if keys_str:
            special_keys[f"{service}_api_keys"] = keys_str.split(",")
        else:
            special_keys[f"{service}_api_keys"] = []
    
    return special_keys


def _load_search_config() -> Dict[str, Any]:
    """
    Load search-related configuration.
    
    Returns:
        Dictionary with search configuration
    """
    return {
        "serper_api_keys": os.getenv("SERPER_API_KEYS", "").split(",") 
            if os.getenv("SERPER_API_KEYS") else [],
        "serpapi_api_keys": os.getenv("SERPAPI_API_KEYS", "").split(",") 
            if os.getenv("SERPAPI_API_KEYS") else [],
        "youtube_api_keys": os.getenv("YOUTUBE_API_KEYS", "").split(",") 
            if os.getenv("YOUTUBE_API_KEYS") else [],
        "saucenao_api_keys": os.getenv("SAUCENAO_API_KEYS", "").split(",") 
            if os.getenv("SAUCENAO_API_KEYS") else [],
        "image_gen_api_keys": os.getenv("IMAGE_GEN_API_KEYS", "").split(",") 
            if os.getenv("IMAGE_GEN_API_KEYS") else [],
    }
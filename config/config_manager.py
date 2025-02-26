"""
Configuration Manager Module

This module handles loading and managing configuration for the application.
It loads environment variables and provides a structured configuration object.
"""

import os
from typing import Dict, Any, List

def get_config() -> Dict[str, Any]:
    """
    Load configuration from environment variables.
    
    Returns:
        A dictionary containing the application configuration.
    """
    try:
        with open('system_prompt.txt', 'r', encoding='utf-8') as f:
            system_prompt: str = f.read()
    except FileNotFoundError:
        system_prompt: str = ("You are a helpful assistant. Cite the most relevant search results as needed to answer the "
                             "question, avoiding irrelevant ones. Write only the response and use markdown for formatting. "
                             "Include a clickable hyperlink at the end of the corresponding sentence using the site name.")

    config: Dict[str, Any] = {
        "bot_token": os.getenv("BOT_TOKEN"),
        "client_id": os.getenv("CLIENT_ID"),
        "status_message": os.getenv("STATUS_MESSAGE"),
        "allow_dms": os.getenv("ALLOW_DMS", "true").lower() == "true",
        "allowed_channel_ids": list(map(int, os.getenv("ALLOWED_CHANNEL_IDS", "").split(","))) if os.getenv("ALLOWED_CHANNEL_IDS") else [],
        "allowed_role_ids": list(map(int, os.getenv("ALLOWED_ROLE_IDS", "").split(","))) if os.getenv("ALLOWED_ROLE_IDS") else [],
        "blocked_user_ids": list(map(int, os.getenv("BLOCKED_USER_IDS", "").split(","))) if os.getenv("BLOCKED_USER_IDS") else [],
        "max_text": int(os.getenv("MAX_TEXT", "100000")),
        "max_images": int(os.getenv("MAX_IMAGES", "5")),
        "max_messages": int(os.getenv("MAX_MESSAGES", "25")),
        "use_plain_responses": os.getenv("USE_PLAIN_RESPONSES", "false").lower() == "true",
        "providers": {
            "openai": {
                "api_keys": os.getenv("OPENAI_API_KEYS", "").split(","),
            },
            "x-ai": {
                "api_keys": os.getenv("XAI_API_KEYS", "").split(","),
            },
            "google": {
                "api_keys": os.getenv("GOOGLE_API_KEYS", "").split(","),
            },
            "mistral": {
                "api_keys": os.getenv("MISTRAL_API_KEYS", "").split(","),
            },
            "groq": {
                "api_keys": os.getenv("GROQ_API_KEYS", "").split(","),
            },
            "openrouter": {
                "api_keys": os.getenv("OPENROUTER_API_KEYS", "").split(","),
            },
            "claude": {
                "api_keys": os.getenv("CLAUDE_API_KEYS", "").split(","),
            },
        },
        "provider": os.getenv("PROVIDER", "openai"),
        "model": os.getenv("MODEL", "gpt-4"),
        "extra_api_parameters": {
            "temperature": float(os.getenv("EXTRA_API_PARAMETERS_TEMPERATURE", "1")),
            "top_p": float(os.getenv("EXTRA_API_PARAMETERS_TOP_P", "1")),
            "max_tokens": int(os.getenv("EXTRA_API_PARAMETERS_MAX_TOKENS", "4096")),
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
        "max_urls": int(os.getenv("MAX_URLS", "5")),
        "image_gen_api_keys": os.getenv("IMAGE_GEN_API_KEYS", "").split(",") if os.getenv("IMAGE_GEN_API_KEYS") else [],
    }
    return config
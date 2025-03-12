"""
SearxNG Configuration Module

Loads SearxNG settings from environment variables, handling any comments in the string values.
It returns a dictionary used for constructing SearxNG API URLs.
"""

import os
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def get_searxng_config(env_vars: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Get SearxNG configuration from environment variables.

    Args:
        env_vars: A dictionary of environment variables (for testing).

    Returns:
        A dictionary containing SearxNG configuration options.
    """
    if env_vars is None:
        env_vars = os.environ
        
    logger.info("Loading SearxNG configuration from environment variables")

    # Get base URL with validation
    base_url = _validate_base_url(env_vars.get('SEARXNG_BASE_URL', 'http://localhost:4000'))
    
    # Get timeout with validation
    timeout = _parse_timeout(env_vars.get('SEARXNG_TIMEOUT', '30.0'))
    
    # Get safe search level with validation
    safe_search = _parse_safe_search(env_vars.get('SEARXNG_SAFE_SEARCH', '1'))
    
    # Create the config dictionary
    config: Dict[str, Any] = {
        'base_url': base_url,
        'timeout': timeout,
        'categories': env_vars.get('SEARXNG_CATEGORIES', 'general'),
        'language': env_vars.get('SEARXNG_LANGUAGE', 'en'),
        'safe_search': safe_search,
    }
    
    logger.info(
        f"SearxNG configuration loaded: base_url={config['base_url']}, "
        f"timeout={config['timeout']}, categories={config['categories']}, "
        f"language={config['language']}, safe_search={config['safe_search']}"
    )

    return config


def _validate_base_url(base_url: str) -> str:
    """
    Validate the SearxNG base URL.
    
    Args:
        base_url: The base URL to validate
        
    Returns:
        The validated base URL
    """
    if not base_url.startswith(('http://', 'https://')):
        logger.warning(
            f"Invalid SearxNG base URL: {base_url}. URL should start with "
            f"http:// or https://. Using default."
        )
        return 'http://localhost:4000'
    return base_url


def _parse_timeout(timeout_str: str) -> float:
    """
    Parse the timeout value from string.
    
    Args:
        timeout_str: Timeout value as string
        
    Returns:
        Parsed timeout value
    """
    timeout_str = timeout_str.split('#')[0].strip()
    try:
        timeout = float(timeout_str)
        if timeout <= 0:
            logger.warning(
                f"Invalid SearxNG timeout: {timeout}. Using default value of "
                f"30.0 seconds"
            )
            return 30.0
        return timeout
    except (ValueError, TypeError) as e:
        logger.warning(
            f"Invalid SearxNG timeout value: '{timeout_str}'. Using default "
            f"of 30.0. Error: {str(e)}"
        )
        return 30.0


def _parse_safe_search(safe_search_str: str) -> int:
    """
    Parse the safe search level from string.
    
    Args:
        safe_search_str: Safe search level as string
        
    Returns:
        Parsed safe search level
    """
    safe_search_str = safe_search_str.split('#')[0].strip()
    try:
        safe_search = int(safe_search_str)
        if safe_search not in (0, 1, 2):
            logger.warning(
                f"Invalid SearxNG safe_search value: {safe_search}. Using "
                f"default value of 1 (moderate)"
            )
            return 1
        return safe_search
    except (ValueError, TypeError) as e:
        logger.warning(
            f"Invalid SearxNG safe_search value: '{safe_search_str}'. Using "
            f"default of 1. Error: {str(e)}"
        )
        return 1
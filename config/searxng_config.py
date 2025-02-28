"""
SearxNG Configuration Module

Loads SearxNG settings from environment variables, handling any comments in the string values.
It returns a dictionary used for constructing SearxNG API URLs.
"""

import os
from typing import Dict, Any, Optional, Callable
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

    def parse_value_with_comments(
        value_str: str,
        convert_func: Callable[[str], Any],
        default_value: Any,
        value_name: str
    ) -> Any:
        """Parse a value from a string, ignoring any in-line comments.

        Args:
            value_str: The raw value string.
            convert_func: Conversion function (int, float, etc.).
            default_value: Value to use if conversion fails.
            value_name: Name of the setting (for logging).

        Returns:
            The converted value.
        """
        value_str = value_str.split('#')[0].strip()
        try:
            return convert_func(value_str)
        except (ValueError, TypeError) as e:
            logger.warning(
                f"Invalid {value_name} value: '{value_str}'. Using default of {default_value}. Error: {str(e)}"
            )
            return default_value

    # Get base URL with validation
    base_url = env_vars.get('SEARXNG_BASE_URL', 'http://localhost:4000')
    if not base_url.startswith(('http://', 'https://')):
        logger.warning(
            f"Invalid SearxNG base URL: {base_url}. URL should start with http:// or https://. Using default."
        )
        base_url = 'http://localhost:4000'
    
    # Get timeout with validation
    timeout_str = env_vars.get('SEARXNG_TIMEOUT', '30.0')
    timeout = parse_value_with_comments(timeout_str, float, 30.0, 'timeout')
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        logger.warning(
            f"Invalid SearxNG timeout: {timeout}. Using default value of 30.0 seconds"
        )
        timeout = 30.0
    
    # Get safe search level with validation
    safe_search_str = env_vars.get('SEARXNG_SAFE_SEARCH', '1')
    safe_search = parse_value_with_comments(safe_search_str, int, 1, 'safe_search')
    if not isinstance(safe_search, int) or safe_search not in (0, 1, 2):
        logger.warning(
            f"Invalid SearxNG safe_search value: {safe_search}. Using default value of 1 (moderate)"
        )
        safe_search = 1
    
    # Create the config dictionary
    config: Dict[str, Any] = {
        'base_url': base_url,
        'timeout': timeout,
        'categories': env_vars.get('SEARXNG_CATEGORIES', 'general'),
        'language': env_vars.get('SEARXNG_LANGUAGE', 'en'),
        'safe_search': safe_search,
    }
    
    logger.info(f"SearxNG configuration loaded: base_url={config['base_url']}, "
                f"timeout={config['timeout']}, categories={config['categories']}, "
                f"language={config['language']}, safe_search={config['safe_search']}")

    return config
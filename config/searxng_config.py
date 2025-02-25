"""
SearxNG Configuration Module

Loads SearxNG settings from environment variables, handling any comments in the string values.
It returns a dictionary used for constructing SearxNG API URLs.
"""

import os
from typing import Dict, Any, Optional, Callable
import logging

logger = logging.getLogger(__name__)

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
        except (ValueError, TypeError):
            logger.warning(
                f"Invalid {value_name} value: {value_str}. Using default of {default_value}."
            )
            return default_value

    config: Dict[str, Any] = {
        'base_url': env_vars.get('SEARXNG_BASE_URL', 'http://localhost:4000'),
        'timeout': parse_value_with_comments(env_vars.get('SEARXNG_TIMEOUT', '30.0'), float, 30.0, 'timeout'),
        'categories': env_vars.get('SEARXNG_CATEGORIES', 'general'),
        'language': env_vars.get('SEARXNG_LANGUAGE', 'en'),
        'safe_search': parse_value_with_comments(env_vars.get('SEARXNG_SAFE_SEARCH', '1'), int, 1, 'safe_search'),
    }

    if not config['base_url'].startswith(('http://', 'https://')):
        logger.warning(
            f"Invalid SearxNG base URL: {config['base_url']}. URL should start with http:// or https://"
        )
        config['base_url'] = 'http://localhost:4000'

    if not isinstance(config['timeout'], (int, float)) or config['timeout'] <= 0:
        logger.warning(
            f"Invalid SearxNG timeout: {config['timeout']}. Using default value of 30.0 seconds"
        )
        config['timeout'] = 30.0

    if not isinstance(config['safe_search'], int) or config['safe_search'] not in (0, 1, 2):
        logger.warning(
            f"Invalid SearxNG safe_search value: {config['safe_search']}. Using default value of 1 (moderate)"
        )
        config['safe_search'] = 1

    return config
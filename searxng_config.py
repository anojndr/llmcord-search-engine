"""
Configuration module for SearxNG integration.
Handles loading and validating SearxNG-related configuration.
"""

import os
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

def get_searxng_config(env_vars: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Get SearxNG configuration from environment variables or config file.
    
    Args:
        env_vars (Optional[Dict[str, Any]]): Environment variables dictionary for testing
        
    Returns:
        Dict[str, Any]: SearxNG configuration dictionary
    """
    if env_vars is None:
        env_vars = os.environ
        
    config = {
        'base_url': env_vars.get('SEARXNG_BASE_URL', 'http://localhost:4000'),
        'timeout': float(env_vars.get('SEARXNG_TIMEOUT', '30.0')),
        'categories': env_vars.get('SEARXNG_CATEGORIES', 'general'),
        'language': env_vars.get('SEARXNG_LANGUAGE', 'en'),
        'safe_search': int(env_vars.get('SEARXNG_SAFE_SEARCH', '1')),
    }
    
    # Validate configuration
    if not config['base_url'].startswith(('http://', 'https://')):
        logger.warning(
            f"Invalid SearxNG base URL: {config['base_url']}. "
            "URL should start with http:// or https://"
        )
        config['base_url'] = 'http://localhost:4000'
    
    if not isinstance(config['timeout'], (int, float)) or config['timeout'] <= 0:
        logger.warning(
            f"Invalid SearxNG timeout: {config['timeout']}. "
            "Using default value of 30.0 seconds"
        )
        config['timeout'] = 30.0
    
    if not isinstance(config['safe_search'], int) or config['safe_search'] not in (0, 1, 2):
        logger.warning(
            f"Invalid SearxNG safe_search value: {config['safe_search']}. "
            "Using default value of 1 (moderate)"
        )
        config['safe_search'] = 1
    
    return config
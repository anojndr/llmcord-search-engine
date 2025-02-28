"""
Image Generator Module

This module handles image generation using the LiteLLM-compatible API.
It provides a function to generate images based on text prompts.
"""

import logging
import os
from typing import Dict, Any, Optional, Tuple
import asyncio

import httpx
from litellm import image_generation

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

async def generate_image(
    prompt: str,
    httpx_client: httpx.AsyncClient,
    api_key: Optional[str] = None,
    model: str = "openai/flux-pro",
    size: str = "1024x1024"
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Generate an image using the specified API.
    
    Args:
        prompt: Text description of the desired image.
        httpx_client: HTTP client for API calls (not used directly in litellm call).
        api_key: Optional API key. If None, reads from environment.
        model: Model name for image generation.
        size: Size of the generated image.
        
    Returns:
        Tuple containing:
        - Success flag (True/False)
        - Image URL if successful, or error message if failed
        - Raw response or None
    """
    try:
        logger.info(f"Generating image with prompt: '{prompt}', model: {model}, size: {size}")
        
        # Use provided API key or get from environment
        if not api_key:
            api_key = os.getenv("IMAGE_GEN_API_KEYS", "").split(",")[0]
            if not api_key:
                logger.error("No image generation API key available")
                return False, "No image generation API key available", None
        
        # Call the image generation API using run_in_executor since it's not async
        logger.debug(f"Calling image_generation with model: {model}")
        response = await asyncio.to_thread(
            image_generation,
            prompt=prompt,
            model=model,
            api_base="https://api.electronhub.top",
            api_key=api_key,
            size=size
        )
        
        logger.debug(f"Image generation response received: {type(response)}")
        
        # Extract the image URL from the response
        if response and response.get('data') and len(response['data']) > 0:
            image_url = response['data'][0].get('url')
            if image_url:
                logger.info("Successfully generated image, URL received")
                return True, image_url, response
        
        error_message = "No image URL found in response"
        logger.warning(f"Image generation failed: {error_message}")
        logger.debug(f"Response content: {response}")
        return False, error_message, response
        
    except Exception as e:
        error_type = type(e).__name__
        logger.error(f"Error generating image: {error_type}: {str(e)}", exc_info=True)
        return False, f"Error generating image: {str(e)}", None
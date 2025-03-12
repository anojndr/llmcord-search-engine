"""
Image Generator Module

This module handles image generation using the LiteLLM-compatible API.
It provides a function to generate images based on text prompts.
"""

import asyncio
import logging
import os
import json
from typing import Dict, Any, Optional, Tuple, Union

import httpx
import requests

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


async def generate_image(
    prompt: str,
    httpx_client: httpx.AsyncClient,
    api_key: Optional[str] = None,
    model: str = "black-forest-labs/FLUX.1-schnell-Free",
    size: str = "1024x1024"
) -> Tuple[bool, Union[str, bytes], Optional[Dict[str, Any]]]:
    """
    Generate an image using the specified API.
    
    Args:
        prompt: Text description of the desired image.
        httpx_client: HTTP client for API calls.
        api_key: Optional API key. If None, reads from environment.
        model: Model name for image generation.
        size: Size of the generated image.
        
    Returns:
        Tuple containing:
        - Success flag (True/False)
        - Image data (bytes) if successful, or error message (str) if failed
        - Raw response or None
    """
    try:
        logger.info(
            f"Generating image with prompt: '{prompt}', model: {model}, "
            f"size: {size}"
        )
        
        # Use provided API key or get from environment
        if not api_key:
            api_key = os.getenv("IMAGE_GEN_API_KEYS", "").split(",")[0]
            if not api_key:
                logger.error("No image generation API key available")
                return False, "No image generation API key available", None
        
        # Direct API call to Together API to bypass LiteLLM's error-prone conversion
        api_url = "https://api.together.xyz/v1/images/generations"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "prompt": prompt,
            "size": size,
            "n": 1
        }
        
        logger.debug(f"Making direct API call to Together.ai with payload: {json.dumps(payload)}")
        
        # Make the API call in a non-blocking way
        def make_request():
            response = requests.post(api_url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()
        
        # Run in an executor to not block the event loop
        response_data = await asyncio.to_thread(make_request)
        
        logger.debug(f"Image generation response received: {json.dumps(response_data)}")
        
        # Extract the image URL from the response
        if (response_data and 
            'data' in response_data and 
            len(response_data['data']) > 0 and
            'url' in response_data['data'][0]):
            
            image_url = response_data['data'][0]['url']
            logger.info("Successfully generated image, URL received. Downloading image...")
            
            try:
                # Download the image content
                img_response = await httpx_client.get(image_url)
                img_response.raise_for_status()
                image_data = img_response.content
                logger.info(f"Successfully downloaded image ({len(image_data)} bytes)")
                return True, image_data, response_data
            except Exception as img_err:
                logger.error(f"Error downloading image: {img_err}", exc_info=True)
                return False, f"Error downloading image: {str(img_err)}", response_data
        
        error_message = "No image URL found in response"
        logger.warning(f"Image generation failed: {error_message}")
        logger.debug(f"Response content: {response_data}")
        return False, error_message, response_data
        
    except Exception as e:
        error_type = type(e).__name__
        logger.error(
            f"Error generating image: {error_type}: {str(e)}", 
            exc_info=True
        )
        return False, f"Error generating image: {str(e)}", None
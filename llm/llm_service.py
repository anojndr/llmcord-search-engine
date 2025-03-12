"""
LLM Service Module

This module handles communication with language model APIs, including:
- Preparing API requests
- Streaming responses
- Error handling and retries
"""

import asyncio
import json
import logging
from typing import Dict, Any, List, Optional, AsyncGenerator, Tuple

from litellm import acompletion

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class LLMService:
    """
    Service for interacting with language models.
    
    This service handles preparation of API payloads, streaming responses,
    and retrying failed requests with different API keys.
    """
    
    @staticmethod
    def prepare_google_safety_settings() -> List[Dict[str, str]]:
        """
        Prepare safety settings for Google models.
        
        Returns:
            List of safety setting dictionaries.
        """
        return [
            {
                "category": "HARM_CATEGORY_HARASSMENT",
                "threshold": "BLOCK_NONE",
            },
            {
                "category": "HARM_CATEGORY_HATE_SPEECH",
                "threshold": "BLOCK_NONE",
            },
            {
                "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "threshold": "BLOCK_NONE",
            },
            {
                "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                "threshold": "BLOCK_NONE",
            },
            {
                "category": "HARM_CATEGORY_CIVIC_INTEGRITY",
                "threshold": "BLOCK_NONE",
            }
        ]
    
    @staticmethod
    def prepare_request_payload(
        messages: List[Dict[str, Any]],
        config: Dict[str, Any],
        api_key: str
    ) -> Dict[str, Any]:
        """
        Prepare the LLM API request payload.
        
        Args:
            messages: List of message objects
            config: Application configuration
            api_key: API key to use
            
        Returns:
            Request payload dictionary
        """
        # Create clean messages with only standard fields
        processed_messages = []
        
        for message in messages:
            # Keep only standard OpenAI-compatible fields
            processed_message = {
                "role": message["role"],
                "content": message["content"]
            }
            
            # Add name field if present (supported by OpenAI and some others)
            if "name" in message:
                processed_message["name"] = message["name"]
            
            processed_messages.append(processed_message)
        
        kwargs: Dict[str, Any] = {
            "model": config["model"],
            "messages": processed_messages,
            "stream": True,
            "api_key": api_key,
            **config["extra_api_parameters"]
        }

        # Add safety settings for Google models
        if config["provider"] == "google":
            kwargs["safety_settings"] = (
                LLMService.prepare_google_safety_settings()
            )
            
        # Add base URL for xai provider
        if config["provider"] == "xai":
            kwargs["base_url"] = "http://localhost:5000/v1"
            
        return kwargs
    
    @staticmethod
    async def log_request_payload(payload: Dict[str, Any]) -> None:
        """
        Log the request payload, redacting sensitive information.
        
        Args:
            payload: Request payload dictionary
        """
        # Create a deep copy for logging to avoid modifying the original
        logging_payload = json.loads(json.dumps(payload, default=str))
        
        # Redact API key
        if "api_key" in logging_payload:
            api_key = logging_payload["api_key"]
            if isinstance(api_key, str) and len(api_key) > 8:
                logging_payload["api_key"] = (
                    api_key[:4] + "..." + api_key[-4:]
                )
        
        # Redact base64 image data in content
        for message in logging_payload.get('messages', []):
            if isinstance(message.get('content'), list):
                for item in message['content']:
                    if (item.get('type') == 'image_url' and 
                            'url' in item.get('image_url', {})):
                        url = item['image_url']['url']
                        if url.startswith('data:'):
                            prefix = url.split(',')[0] + ','
                            data = url.split(',')[1]
                            if len(data) > 20:
                                item['image_url']['url'] = (
                                    prefix + data[:10] + "..." + data[-10:]
                                )
        
        # Log base_url if present
        if "base_url" in logging_payload:
            logger.info(f"Using base_url: {logging_payload['base_url']}")
            
        logger.info(
            f"Payload being sent to LLM API:\n"
            f"{json.dumps(logging_payload, indent=2)}"
        )
    
    @staticmethod
    async def stream_completion(
        messages: List[Dict[str, Any]],
        config: Dict[str, Any],
        api_key: str,
        max_retries: int = 5
    ) -> AsyncGenerator[Any, None]:
        """
        Stream a completion from the language model API with retries.
        
        Args:
            messages: List of message objects
            config: Application configuration
            api_key: Initial API key to use
            max_retries: Maximum number of retry attempts
            
        Yields:
            Response chunks from the LLM API
        """
        current_api_key = api_key
        provider = config["provider"]
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                kwargs = LLMService.prepare_request_payload(
                    messages, config, current_api_key
                )
                await LLMService.log_request_payload(kwargs)
                
                logger.info(
                    f"Attempt {retry_count+1} for LLM completion using "
                    f"provider: {provider}"
                )
                response_stream = await acompletion(**kwargs)
                
                async for chunk in response_stream:
                    yield chunk
                
                # If we get here without exceptions, the stream was successful
                logger.info(
                    f"LLM completion stream completed successfully using "
                    f"provider: {provider}"
                )
                return
                
            except Exception as e:
                retry_count += 1
                error_type = type(e).__name__
                error_msg = str(e).lower()
                
                if ("rate limit" in error_msg or 
                        "too many requests" in error_msg):
                    logger.warning(
                        f"Rate limit exceeded during LLM request "
                        f"(attempt {retry_count}/{max_retries}) for provider "
                        f"{provider}: {str(e)}"
                    )
                else:
                    logger.error(
                        f"Error during LLM request "
                        f"(attempt {retry_count}/{max_retries}) for provider "
                        f"{provider}: {error_type}: {str(e)}",
                        exc_info=True
                    )
                
                if retry_count >= max_retries:
                    # Re-raise the exception on the last retry
                    raise
                
                # Log the retry attempt
                logger.info(f"Retrying with a new API key for {provider}")
                
                # Small delay before retry
                await asyncio.sleep(1)
    
    @staticmethod
    async def get_completion(
        messages: List[Dict[str, Any]],
        config: Dict[str, Any],
        api_key: str
    ) -> Tuple[bool, AsyncGenerator[Any, None]]:
        """
        Get a streaming completion from the language model.
        
        Args:
            messages: List of message objects
            config: Application configuration
            api_key: API key to use
            
        Returns:
            Tuple containing:
            - Boolean indicating success
            - Generator of response chunks
        """
        try:
            stream = LLMService.stream_completion(messages, config, api_key)
            return True, stream
        except Exception as e:
            error_type = type(e).__name__
            logger.error(
                f"Failed to get LLM completion: {error_type}: {str(e)}", 
                exc_info=True
            )
            return False, None
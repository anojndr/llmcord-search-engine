"""
Query Splitter Handler Module

This module defines a function to detect whether a query involves comparisons
and to split queries accordingly. It uses an LLM call to generate a JSON array
of query strings.
"""

import json
import logging
import re
from typing import List, Dict, Any
from litellm import acompletion

from config.api_key_manager import APIKeyManager

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


async def split_query(
    query: str,
    cfg: Dict[str, Any],
    api_key_manager: APIKeyManager
) -> List[str]:
    """
    Split an input query into multiple queries when it implies a comparison.

    The prompt instructs the model to:
      - If a comparison exists, return multiple queries including the original.
      - Otherwise, simply return the original query in a JSON array.

    Args:
        query: The original user query.
        cfg: Configuration options.
        api_key_manager: API key manager instance.

    Returns:
        A list of queries (strings) as parsed from the model's JSON output.
    """
    logger.info(f"Processing query for potential splitting: '{query}'")
    
    # Define the prompt template
    query_splitter_prompt = '''Your task is to determine if the query implies a comparison between multiple entities.

If it does, decompose it into separate queries focusing on each entity, along with the original comparison query.

If the query doesn't involve comparison, still return it inside a JSON array.

**Output Format:**

- **Always output only a JSON array of strings representing the final query or queries.**

- **Do not include any additional text, explanations, or code blocks.**

**Examples:**

Input: "compare the GDP of Japan and Korea"
Output:
["What is the GDP of Japan?", "What is the GDP of Korea?", "compare the GDP of Japan and Korea"]

Input: "Biggest star in the universe"
Output:
["Biggest star in the universe"]

Input: "which is better soundcore r50i nc or qcy melobuds pro"
Output:
["info about soundcore r50i nc", "info about qcy melobuds pro", "which is better soundcore r50i nc or qcy melobuds pro"]

Input: "Best budget earbuds 2024 reddit"
Output:
["Best budget earbuds 2024 reddit"]

Now, process the following query:

Input: "{query}"
Output:
'''

    # Format the prompt with the current query
    formatted_prompt = query_splitter_prompt.format(query=query)

    # Get provider and model settings
    query_splitter_provider = cfg.get('query_splitter_provider', 'openai')
    query_splitter_model = cfg.get('query_splitter_model', 'gpt-4')
    
    # Get API key
    api_key = await api_key_manager.get_next_api_key(query_splitter_provider)
    if not api_key:
        logger.warning(
            f"No API key available for query splitter provider: "
            f"{query_splitter_provider}, using placeholder"
        )
        api_key = 'sk-no-key-required'

    # Prepare LLM request
    messages = [
        {"role": "system", "content": "You are a concise assistant."},
        {"role": "user", "content": formatted_prompt}
    ]

    kwargs = {
        "model": query_splitter_model,
        "messages": messages,
        "stream": False,
        "api_key": api_key,
        **cfg.get("query_splitter_extra_api_parameters", {})
    }

    # Add safety settings for Google models
    if query_splitter_provider == "google":
        logger.debug("Adding safety settings for Google query splitter model")
        kwargs["safety_settings"] = [
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

    # Log request with redacted API key
    logging_kwargs = kwargs.copy()
    if 'api_key' in logging_kwargs:
        api_key_str = logging_kwargs['api_key']
        if isinstance(api_key_str, str) and len(api_key_str) > 8:
            logging_kwargs['api_key'] = api_key_str[:4] + '...' + api_key_str[-4:]
    
    logger.debug(
        f"Query splitter request: provider={query_splitter_provider}, "
        f"model={query_splitter_model}"
    )

    # Call the model with retries
    max_retries = 5
    response = None
    
    for i in range(max_retries):
        try:
            logger.info(
                f"Query splitter attempt {i+1}/{max_retries} using provider: "
                f"{query_splitter_provider}"
            )
            response = await acompletion(**kwargs)
            break
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e).lower()
            
            if "rate limit" in error_msg or "too many requests" in error_msg:
                logger.warning(
                    f"Rate limit exceeded for query splitter "
                    f"(attempt {i+1}/{max_retries}): {str(e)}"
                )
            else:
                logger.error(
                    f"Error calling query splitter model "
                    f"(attempt {i+1}/{max_retries}): {error_type}: {str(e)}", 
                    exc_info=True
                )
            
            # Get a new API key for next attempt
            new_api_key = await api_key_manager.get_next_api_key(
                query_splitter_provider
            )
            if new_api_key:
                kwargs["api_key"] = new_api_key
                logger.info(
                    f"Retrying with new API key for {query_splitter_provider}"
                )
            
            # On last attempt, return original query
            if i == max_retries - 1:
                logger.warning(
                    f"All query splitter attempts failed, returning original query"
                )
                return [query]

    # Handle case where we got no response
    if response is None:
        logger.warning("No response from query splitter, returning original query")
        return [query]

    # Process the response
    content = response.choices[0].message.content.strip()
    return _parse_query_splitter_response(content, query)


def _parse_query_splitter_response(content: str, original_query: str) -> List[str]:
    """
    Parse the response from the query splitter.
    
    Args:
        content: Response content from the LLM
        original_query: Original query (used as fallback)
        
    Returns:
        List of queries
    """
    try:
        # Try to extract JSON array from response
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            json_content = match.group(0)
            queries = json.loads(json_content)
            
            if isinstance(queries, list) and all(isinstance(q, str) for q in queries):
                logger.info(f"Query successfully split into {len(queries)} queries")
                for i, q in enumerate(queries):
                    logger.debug(f"Query {i+1}: {q}")
                return queries
            else:
                logger.warning(
                    f"Invalid JSON array format in query_splitter response: "
                    f"{json_content}"
                )
                return [original_query]
        else:
            logger.warning(
                f"No JSON array found in query_splitter response: {content}"
            )
            return [original_query]
    except json.JSONDecodeError as e:
        logger.error(
            f"Failed to parse JSON in query_splitter response: {e}, "
            f"content: {content}", 
            exc_info=True
        )
        return [original_query]
    except Exception as e:
        logger.error(
            f"Unexpected error processing query_splitter response: {e}", 
            exc_info=True
        )
        return [original_query]
"""
Rephraser Handler Module

This module provides a function to decide whether to rephrase the user's query for web search.
It calls an LLM with detailed instructions and returns either a rephrased query or 'not_needed'.
"""

import json
import logging
import re
from typing import List, Dict, Any, Optional

from litellm import acompletion

from config.api_key_manager import APIKeyManager

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def truncate_base64(base64_string: str, max_length: int = 50) -> str:
    """
    Truncate a base64 string to a maximum length for logging.
    
    Args:
        base64_string: The base64 string to truncate
        max_length: Maximum length to show
        
    Returns:
        Truncated string with ellipsis
    """
    if not base64_string:
        return ""
    if len(base64_string) > max_length:
        return base64_string[:max_length] + "..."
    return base64_string


def format_chat_history(messages: List[Dict[str, Any]]) -> str:
    """
    Format the messages into a chat history string from oldest to newest.

    Args:
        messages: The conversation messages.

    Returns:
        The formatted chat history.
    """
    chat_messages = [msg for msg in messages if msg.get("role") != "system"]
    logger.debug(f"Formatting chat history from {len(chat_messages)} messages")

    chat_history = []
    for i, msg in enumerate(chat_messages):
        if msg["role"] == "user":
            # Format user message
            if isinstance(msg["content"], list):
                text_content = next(
                    (part.get("text", "") for part in msg["content"]
                     if part.get("type") == "text"), 
                    ""
                )
                chat_history.append(f"user: \n{text_content}")
            else:
                chat_history.append(f"user: \n{msg['content']}")
        elif msg["role"] == "assistant":
            # Check if this is a rephraser response
            if i > 0 and chat_messages[i-1]["role"] == "user":
                last_user_msg = chat_messages[i-1]
                next_user_idx = next(
                    (j for j in range(i+1, len(chat_messages))
                     if chat_messages[j]["role"] == "user"), 
                    None
                )

                if next_user_idx is not None and next_user_idx < len(chat_messages):
                    rephraser_output = "not_needed"

                    # Extract content from assistant message
                    assistant_content = msg.get("content", "")
                    if isinstance(assistant_content, list):
                        assistant_content = next(
                            (part.get("text", "") for part in assistant_content
                             if part.get("type") == "text"), 
                            ""
                        )

                    # Check for question tags
                    question_match = re.search(
                        r'<question>\s*(.*?)\s*</question>', 
                        assistant_content, 
                        re.DOTALL
                    )
                    if question_match:
                        rephraser_output = question_match.group(1).strip()

                    chat_history.append(
                        f"rephraser response:\n```\n<question>\n"
                        f"{rephraser_output}\n</question>\n```"
                    )

            # Add assistant response
            if isinstance(msg["content"], list):
                text_content = next(
                    (part.get("text", "") for part in msg["content"]
                     if part.get("type") == "text"), 
                    ""
                )
                chat_history.append(f"assistant response:\n{text_content}")
            else:
                chat_history.append(f"assistant response:\n{msg['content']}")

    return "\n\n".join(chat_history)


async def rephrase_query(
    messages: List[Dict[str, Any]],
    cfg: Dict[str, Any],
    api_key_manager: APIKeyManager
) -> str:
    """
    Determine whether the user's query needs rephrasing for a web search,
    and return the rephrased query or 'not_needed'.

    Args:
        messages: The conversation messages.
        cfg: Configuration settings.
        api_key_manager: API key manager instance.

    Returns:
        The rephrased query or "not_needed".
    """
    # Find the latest user message
    latest_user_msg = None
    for msg in reversed(messages):
        if msg['role'] == 'user':
            latest_user_msg = msg
            break

    if not latest_user_msg:
        logger.warning("No user message found in conversation history")
        return 'not_needed'

    # Check if the message contains a text file (don't use internet in this case)
    has_text_file = _check_for_text_file(latest_user_msg)
    if has_text_file:
        logger.info("Text file detected in message, skipping rephrasing")
        return 'not_needed'

    # Format chat history
    chat_history = format_chat_history(messages)

    # Extract the latest query text
    latest_query = _extract_query_text(latest_user_msg)

    logger.info(
        f"Evaluating if web search is needed for query: "
        f"'{latest_query[:100]}{'...' if len(latest_query) > 100 else ''}'"
    )

    # Prepare the rephraser prompt
    rephraser_prompt = _get_rephraser_prompt()
    formatted_prompt = rephraser_prompt.format(
        chat_history=chat_history,
        query=latest_query
    )

    # Get rephraser settings from config
    rephraser_provider = cfg.get('rephraser_provider', 'openai')
    rephraser_model = cfg.get('rephraser_model', 'gpt-4')
    
    # Get API key
    api_key = await api_key_manager.get_next_api_key(rephraser_provider)
    if not api_key:
        logger.warning(
            f"No API key available for rephraser provider: {rephraser_provider}, "
            f"using placeholder"
        )
        api_key = 'sk-no-key-required'

    # Call the rephraser model
    result = await _call_rephraser_model(
        latest_user_msg,
        formatted_prompt,
        rephraser_provider,
        rephraser_model,
        api_key,
        cfg,
        api_key_manager
    )
    
    return result


def _check_for_text_file(message: Dict[str, Any]) -> bool:
    """
    Check if the message contains a text file attachment.
    
    Args:
        message: Message object to check
        
    Returns:
        True if the message contains a text file, False otherwise
    """
    if isinstance(message['content'], str):
        return bool(re.search(r'<text_file\s+name="[^"]+"\s*>', message['content']))
    elif isinstance(message['content'], list):
        return any(
            isinstance(part.get('text', ''), str) and
            bool(re.search(r'<text_file\s+name="[^"]+"\s*>', part.get('text', '')))
            for part in message['content']
        )
    return False


def _extract_query_text(message: Dict[str, Any]) -> str:
    """
    Extract the text content from a message.
    
    Args:
        message: Message object
        
    Returns:
        Extracted text content
    """
    if isinstance(message['content'], str):
        return message['content']
    elif isinstance(message['content'], list):
        for content_part in message['content']:
            if content_part.get('type') == 'text':
                return content_part.get('text', '')
    return ""


def _get_rephraser_prompt() -> str:
    """
    Get the prompt template for the rephraser.
    
    Returns:
        Prompt template as a string
    """
    return r'''# Question Rephraser Instructions

You are an AI question rephraser. Your task is to analyze a conversation and a follow-up question, then determine whether to rephrase the question for web search or return `not_needed`.

## When to Return `not_needed`

Return `not_needed` in ANY of these cases:

1. **No search needed**: The query is a simple writing task, greeting, or can be answered without external information
   - Examples: "Hi", "Hello", "How are you", "Write a poem", "Summarize what we discussed"

2. **User explicitly opts out of search**: The query contains ANY phrase indicating the user doesn't want web search
   - Phrases include (case-insensitive):
     - "don't search the net"
     - "no search"
     - "without searching"
     - "don't look online"
     - "don't use the internet"
     - "don't search the web"
     - "no need to search"
     - "use your knowledge"
     - "based on what you know"
     - "answer yourself"

3. **Contextual follow-up**: The query is a follow-up question that can be answered using the existing conversation context
   - Exception: If the follow-up explicitly requests web search with phrases like "search for this", "look this up", etc.

## Special Case: Platform-Specific Search Requests

If the follow-up query is directing to search on specific platforms or sources (like "Search Reddit and YouTube", "Check Twitter", etc.) about a topic from the previous query:

1. Combine the topic from the previous query with the specified platforms
2. Format as: "[Original query topic]? [Platforms mentioned]"
3. Example:
   - Previous query: "Is a tempered glass beneficial for CODM aiming?"
   - Follow-up: "Search Reddit and YouTube"
   - Rephrased: "Is tempered glass beneficial for Call of Duty Mobile (CODM) aiming? Reddit and YouTube"

## How to Rephrase Questions

When rephrasing is needed:
- Make the question standalone (no references to "I", "you", or previous context)
- Focus on the key search terms
- Remove unnecessary words while preserving the core question
- Maintain proper nouns, technical terms, and specific details
- Expand acronyms when appropriate (e.g., "CODM" to "Call of Duty Mobile (CODM)")

## Output Format

Always return your answer inside the `question` XML block:

```
<question>
Your rephrased question OR "not_needed"
</question>
```

## Examples

<examples>
1. Follow up question: What is the capital of France
Rephrased question:
```
<question>
Capital of france
</question>
```

2. Hi, how are you?
Rephrased question:
```
<question>
not_needed
</question>
```

3. Follow up question: What is Docker?
Rephrased question: 
```
<question>
What is Docker
</question>
```

4. Latest news don't search the net
Rephrased question:
```
<question>
not_needed
</question>
```

5. latest news
assistant: Here's a quick rundown of some of the top news stories as of...
Follow up question: what is the cause of his death?
Rephrased question:
```
<question>
not_needed
</question>
```

6. Tell me about quantum computing but don't use the internet
Rephrased question:
```
<question>
not_needed
</question>
```

7. What's the weather in New York?
assistant: As of my last update, I don't have real-time weather data.
Follow up question: Can you look that up?
Rephrased question:
```
<question>
Current weather in New York
</question>
```

8. Is a tempered glass beneficial for CODM aiming?
assistant: Based on my knowledge...
Follow up question: Search Reddit and YouTube
Rephrased question:
```
<question>
Is tempered glass beneficial for Call of Duty Mobile (CODM) aiming? Reddit and YouTube
</question>
```

9. What are the best settings for Valorant?
assistant: I can share some general recommendations...
Follow up question: Check Twitter for pro player settings
Rephrased question:
```
<question>
Best settings for Valorant pro players? Twitter
</question>
```
</examples>

Anything below is the part of the actual conversation and you need to use conversation and the follow-up question to rephrase the follow-up question as a standalone question based on the guidelines shared above.

<conversation>
{chat_history}
</conversation>

Follow up question: {query}

Rephrased question:'''


async def _call_rephraser_model(
    latest_user_msg: Dict[str, Any],
    formatted_prompt: str,
    rephraser_provider: str,
    rephraser_model: str,
    api_key: str,
    cfg: Dict[str, Any],
    api_key_manager: APIKeyManager
) -> str:
    """
    Call the rephraser model and process the response.
    
    Args:
        latest_user_msg: Latest user message
        formatted_prompt: Formatted prompt for the rephraser
        rephraser_provider: Provider to use
        rephraser_model: Model to use
        api_key: API key
        cfg: Configuration dictionary
        api_key_manager: API key manager
        
    Returns:
        Rephrased query or "not_needed"
    """
    # Prepare message for API
    api_messages = [
        {
            "role": "system", 
            "content": "You are a concise assistant that rephrases questions."
        }
    ]
    
    # Prepare user message
    user_message = {"role": "user", "content": formatted_prompt}

    # Handle vision models if applicable
    if (_is_vision_model(rephraser_model) and
        isinstance(latest_user_msg['content'], list)):

        images = [
            item for item in latest_user_msg['content']
            if item.get('type') == 'image_url'
        ]

        if images:
            logger.info(
                f"Including {len(images)} images in rephraser request for "
                f"vision model"
            )
            multimodal_content = [
                {"type": "text", "text": formatted_prompt}
            ]
            multimodal_content.extend(images)
            user_message["content"] = multimodal_content

    api_messages.append(user_message)

    # Prepare API request parameters
    kwargs = {
        "model": rephraser_model,
        "messages": api_messages,
        "stream": False,
        "api_key": api_key,
        **cfg.get("rephraser_extra_api_parameters", {})
    }

    # Add safety settings for Google models
    if rephraser_provider == "google":
        logger.debug("Adding safety settings for Google rephraser model")
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

    # Log request with redacted sensitive info
    _log_rephraser_request(kwargs, rephraser_provider, rephraser_model)
    
    # Call the API with retries
    return await _make_rephraser_call(
        kwargs, 
        rephraser_provider, 
        api_key_manager
    )


def _is_vision_model(model_name: str) -> bool:
    """
    Check if the model supports vision capabilities.
    
    Args:
        model_name: Name of the model
        
    Returns:
        True if the model supports vision, False otherwise
    """
    vision_keywords = ["gpt-4-vision", "gpt-4o", "claude-3", "gemini", "vision"]
    return any(keyword in model_name.lower() for keyword in vision_keywords)


def _log_rephraser_request(
    kwargs: Dict[str, Any],
    rephraser_provider: str,
    rephraser_model: str
) -> None:
    """
    Log the rephraser request with sensitive information redacted.
    
    Args:
        kwargs: Request parameters
        rephraser_provider: Provider name
        rephraser_model: Model name
    """
    # Create a copy for logging
    logging_kwargs = json.loads(json.dumps(kwargs, default=str))
    
    # Redact API key
    if 'api_key' in logging_kwargs:
        api_key_str = logging_kwargs['api_key']
        if isinstance(api_key_str, str) and len(api_key_str) > 8:
            logging_kwargs['api_key'] = api_key_str[:4] + '...' + api_key_str[-4:]
    
    # Redact image data
    for message in logging_kwargs.get('messages', []):
        if isinstance(message.get('content'), list):
            for item in message['content']:
                if (item.get('type') == 'image_url' and 
                        'url' in item.get('image_url', {})):
                    item['image_url']['url'] = truncate_base64(
                        item['image_url']['url']
                    )
    
    logger.debug(
        f"Rephraser request: provider={rephraser_provider}, "
        f"model={rephraser_model}"
    )


async def _make_rephraser_call(
    kwargs: Dict[str, Any],
    rephraser_provider: str,
    api_key_manager: APIKeyManager
) -> str:
    """
    Make the rephraser API call with retries.
    
    Args:
        kwargs: Request parameters
        rephraser_provider: Provider name
        api_key_manager: API key manager
        
    Returns:
        Rephrased query or "not_needed"
    """
    max_retries = 5
    response = None
    
    for i in range(max_retries):
        try:
            logger.info(
                f"Rephraser attempt {i+1}/{max_retries} using provider: "
                f"{rephraser_provider}"
            )
            response = await acompletion(**kwargs)
            break
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e).lower()
            
            if "rate limit" in error_msg or "too many requests" in error_msg:
                logger.warning(
                    f"Rate limit exceeded for rephraser "
                    f"(attempt {i+1}/{max_retries}): {str(e)}"
                )
            else:
                logger.error(
                    f"Error calling rephraser model "
                    f"(attempt {i+1}/{max_retries}): {error_type}: {str(e)}", 
                    exc_info=True
                )
            
            # Get a new API key for next attempt
            new_api_key = await api_key_manager.get_next_api_key(rephraser_provider)
            if new_api_key:
                kwargs["api_key"] = new_api_key
                logger.info(f"Retrying with new API key for {rephraser_provider}")
            
            # On last attempt, return not_needed
            if i == max_retries - 1:
                logger.warning(
                    f"All rephraser attempts failed, returning 'not_needed'"
                )
                return 'not_needed'

    if response is None:
        logger.warning("No response from rephraser, returning 'not_needed'")
        return 'not_needed'

    # Process the response
    content = response.choices[0].message.content.strip()
    
    # Look for <question> tags in the response
    match = re.search(r'<question>\s*(.*?)\s*</question>', content, re.DOTALL)
    if match:
        user_query = match.group(1).strip()
        if user_query.lower() == 'not_needed':
            logger.info("Rephraser determined web search is not needed")
            return 'not_needed'
        else:
            logger.info(f"Successfully rephrased query for web search: '{user_query}'")
            return user_query
    else:
        logger.warning(f"No <question> tags found in rephraser response: {content}")
        return 'not_needed'
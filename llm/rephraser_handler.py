"""
Rephraser Handler Module

This module provides a function to decide whether to rephrase the user's query for web search.
It calls an LLM with detailed instructions and returns either a rephrased query or 'not_needed'.
"""

import logging
import json
import re
from typing import List, Dict, Any, Optional
from litellm import acompletion

from config.api_key_manager import APIKeyManager

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

def truncate_base64(base64_string: str, max_length: int = 50) -> str:
    """Truncate a base64 string to a maximum length for logging."""
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
    chat_messages: List[Dict[str, Any]] = [msg for msg in messages if msg.get("role") != "system"]
    logger.debug(f"Formatting chat history from {len(chat_messages)} messages")

    chat_history: List[str] = []
    for i, msg in enumerate(chat_messages):
        if msg["role"] == "user":
            if isinstance(msg["content"], list):
                text_content: str = next((part.get("text", "") for part in msg["content"]
                                         if part.get("type") == "text"), "")
                chat_history.append(f"user: \n{text_content}")
            else:
                chat_history.append(f"user: \n{msg['content']}")
        elif msg["role"] == "assistant":
            if i > 0 and chat_messages[i-1]["role"] == "user":
                last_user_msg: Dict[str, Any] = chat_messages[i-1]
                next_user_idx: Optional[int] = next((j for j in range(i+1, len(chat_messages))
                                                    if chat_messages[j]["role"] == "user"), None)

                if next_user_idx is not None and next_user_idx < len(chat_messages):
                    rephraser_output: str = "not_needed"

                    assistant_content: Any = msg.get("content", "")
                    if isinstance(assistant_content, list):
                        assistant_content = next((part.get("text", "") for part in assistant_content
                                                 if part.get("type") == "text"), "")

                    question_match = re.search(r'<question>\s*(.*?)\s*</question>', assistant_content, re.DOTALL)
                    if question_match:
                        rephraser_output = question_match.group(1).strip()

                    chat_history.append(f"rephraser response:\n```\n<question>\n{rephraser_output}\n</question>\n```")

            if isinstance(msg["content"], list):
                text_content: str = next((part.get("text", "") for part in msg["content"]
                                         if part.get("type") == "text"), "")
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
    latest_user_msg: Optional[Dict[str, Any]] = None
    for msg in reversed(messages):
        if msg['role'] == 'user':
            latest_user_msg = msg
            break

    if not latest_user_msg:
        logger.warning("No user message found in conversation history")
        return 'not_needed'

    # Check if the message contains a text file (don't use internet in this case)
    has_text_file = False
    if latest_user_msg:
        if isinstance(latest_user_msg['content'], str):
            has_text_file = bool(re.search(r'<text_file\s+name="[^"]+"\s*>', latest_user_msg['content']))
        elif isinstance(latest_user_msg['content'], list):
            has_text_file = any(
                isinstance(part.get('text', ''), str) and
                bool(re.search(r'<text_file\s+name="[^"]+"\s*>', part.get('text', '')))
                for part in latest_user_msg['content']
            )

    if has_text_file:
        logger.info("Text file detected in message, skipping rephrasing")
        return 'not_needed'

    # Format chat history
    chat_history: str = format_chat_history(messages)

    # Extract the latest query text
    latest_query: str = ""
    if latest_user_msg:
        if isinstance(latest_user_msg['content'], str):
            latest_query = latest_user_msg['content']
        elif isinstance(latest_user_msg['content'], list):
            for content_part in latest_user_msg['content']:
                if content_part.get('type') == 'text':
                    latest_query = content_part.get('text', '')
                    break

    logger.info(f"Evaluating if web search is needed for query: '{latest_query[:100]}{'...' if len(latest_query) > 100 else ''}'")

    # Using a raw string for the prompt
    rephraser_prompt: str = r'''You are an AI question rephraser. You will be given a conversation and a follow-up question,  you will have to rephrase the follow up question so it is a standalone question and can be used by another LLM to search the web for information to answer it.
If it is a smple writing task or a greeting (unless the greeting contains a question after it) like Hi, Hello, How are you, etc. than a question then you need to return `not_needed` as the response (This is because the LLM won't need to search the web for finding information on this topic).
If it contains "don't search the net" or something similar, return `not_needed`. (This is because the user wants the LLM to respond without using information from the web.)
If the latest query is a follow-up to the previous one (unless the user says "search the web" or similar), return `not_needed`. (This is because the LLM can answer the query without information from the web, as the information is already provided, and the LLM can simply formulate an answer using the given information.)
You must always return the rephrased question inside the `question` XML block.

There are several examples attached for your reference inside the below `examples` XML block

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
</examples>

Anything below is the part of the actual conversation and you need to use conversation and the follow-up question to rephrase the follow-up question as a standalone question based on the guidelines shared above.

<conversation>
{chat_history}
</conversation>

Follow up question: {query}
Rephrased question:'''

    formatted_prompt: str = rephraser_prompt.format(
        chat_history=chat_history,
        query=latest_query
    )

    # Get rephraser settings from config
    rephraser_provider: str = cfg.get('rephraser_provider', 'openai')
    rephraser_model: str = cfg.get('rephraser_model', 'gpt-4')
    
    # Get API key
    api_key: str = await api_key_manager.get_next_api_key(rephraser_provider)
    if not api_key:
        logger.warning(f"No API key available for rephraser provider: {rephraser_provider}, using placeholder")
        api_key = 'sk-no-key-required'

    # Prepare message for API
    api_messages: List[Dict[str, Any]] = []
    api_messages.append({"role": "system", "content": "You are a concise assistant that rephrases questions."})
    user_message: Dict[str, Any] = {"role": "user", "content": formatted_prompt}

    # Handle vision models if applicable
    if (latest_user_msg and
        isinstance(latest_user_msg['content'], list) and
        any(x in rephraser_model.lower() for x in ["gpt-4-vision", "gpt-4o", "claude-3", "gemini", "vision"])):

        images: List[Dict[str, Any]] = [item for item in latest_user_msg['content']
                                       if item.get('type') == 'image_url']

        if images:
            logger.info(f"Including {len(images)} images in rephraser request for vision model")
            multimodal_content: List[Dict[str, Any]] = [{"type": "text", "text": formatted_prompt}]
            multimodal_content.extend(images)
            user_message["content"] = multimodal_content

    api_messages.append(user_message)

    # Prepare API request parameters
    kwargs: Dict[str, Any] = {
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

    # Log request (redacted for sensitive info)
    logging_kwargs: Dict[str, Any] = json.loads(json.dumps(kwargs, default=str))
    if 'api_key' in logging_kwargs:
        api_key_str = logging_kwargs['api_key']
        if isinstance(api_key_str, str) and len(api_key_str) > 8:
            logging_kwargs['api_key'] = api_key_str[:4] + '...' + api_key_str[-4:]
    
    # For messages with image content, truncate the image data
    for message in logging_kwargs.get('messages', []):
        if isinstance(message.get('content'), list):
            for item in message['content']:
                if item.get('type') == 'image_url' and 'url' in item.get('image_url', {}):
                    item['image_url']['url'] = truncate_base64(item['image_url']['url'])

    logger.debug(f"Rephraser request: provider={rephraser_provider}, model={rephraser_model}")

    # Call the API with retries
    max_retries: int = 5
    response: Any = None
    
    for i in range(max_retries):
        try:
            logger.info(f"Rephraser attempt {i+1}/{max_retries} using provider: {rephraser_provider}")
            response = await acompletion(**kwargs)
            break
        except Exception as e:
            error_type = type(e).__name__
            if "rate limit" in str(e).lower() or "too many requests" in str(e).lower():
                logger.warning(f"Rate limit exceeded for rephraser (attempt {i+1}/{max_retries}): {str(e)}")
            else:
                logger.error(f"Error calling rephraser model (attempt {i+1}/{max_retries}): {error_type}: {str(e)}", 
                             exc_info=True)
            
            # Get a new API key for next attempt
            new_api_key = await api_key_manager.get_next_api_key(rephraser_provider)
            if new_api_key:
                kwargs["api_key"] = new_api_key
                logger.info(f"Retrying with new API key for {rephraser_provider}")
            
            # On last attempt, return not_needed
            if i == max_retries - 1:
                logger.warning(f"All rephraser attempts failed, returning 'not_needed'")
                return 'not_needed'

    if response is None:
        logger.warning("No response from rephraser, returning 'not_needed'")
        return 'not_needed'

    # Process the response
    content: str = response.choices[0].message.content.strip()
    try:
        # Look for <question> tags in the response
        match = re.search(r'<question>\s*(.*?)\s*</question>', content, re.DOTALL)
        if match:
            latest_user_query: str = match.group(1).strip()
            if latest_user_query.lower() == 'not_needed':
                logger.info("Rephraser determined web search is not needed")
                return 'not_needed'
            else:
                logger.info(f"Successfully rephrased query for web search: '{latest_user_query}'")
                return latest_user_query
        else:
            logger.warning(f"No <question> tags found in rephraser response: {content}")
            return 'not_needed'
    except Exception as e:
        logger.error(f"Failed to parse rephraser response: {e}, content: {content}", exc_info=True)
        return 'not_needed'
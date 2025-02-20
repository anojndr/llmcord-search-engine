"""
Rephraser Handler Module

This module provides a function to decide whether to rephrase the user's query for web search.
It calls an LLM with detailed instructions and returns either a rephrased query or 'not_needed'.
"""

import logging
import json
import re
from datetime import datetime as dt

from litellm import acompletion

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

def truncate_base64(base64_string, max_length=50):
    """Truncate a base64 string to a maximum length for logging."""
    if len(base64_string) > max_length:
        return base64_string[:max_length] + "..."
    return base64_string

def format_chat_history(messages):
    """
    Format the messages into a chat history string from oldest to newest.
    
    Args:
        messages (list): The conversation messages.
        
    Returns:
        str: The formatted chat history.
    """
    # Filter out system messages and reverse to get chronological order
    chat_messages = [msg for msg in messages if msg.get("role") != "system"]
    
    chat_history = []
    for i, msg in enumerate(chat_messages):
        if msg["role"] == "user":
            if isinstance(msg["content"], list):
                # Handle multimodal content
                text_content = next((part.get("text", "") for part in msg["content"] 
                                    if part.get("type") == "text"), "")
                chat_history.append(f"user: \n{text_content}")
            else:
                chat_history.append(f"user: \n{msg['content']}")
        elif msg["role"] == "assistant":
            if i > 0 and chat_messages[i-1]["role"] == "user":
                # If this is an assistant response to the preceding user message,
                # include the rephraser response based on the pattern in previous messages
                last_user_msg = chat_messages[i-1]
                # Look for the next user message to find the full interaction pattern
                next_user_idx = next((j for j in range(i+1, len(chat_messages)) 
                                     if chat_messages[j]["role"] == "user"), None)
                
                if next_user_idx is not None and next_user_idx < len(chat_messages):
                    # We have found a complete interaction pattern
                    rephraser_output = "not_needed"
                    
                    # Find if the assistant response has a <question> tag pattern
                    assistant_content = msg.get("content", "")
                    if isinstance(assistant_content, list):
                        assistant_content = next((part.get("text", "") for part in assistant_content
                                                if part.get("type") == "text"), "")
                    
                    question_match = re.search(r'<question>\s*(.*?)\s*</question>', assistant_content, re.DOTALL)
                    if question_match:
                        rephraser_output = question_match.group(1).strip()
                    
                    chat_history.append(f"rephraser response:\n`\n<question>\n{rephraser_output}\n</question>\n`")
            
            # Add the assistant response
            if isinstance(msg["content"], list):
                # Handle multimodal content
                text_content = next((part.get("text", "") for part in msg["content"] 
                                    if part.get("type") == "text"), "")
                chat_history.append(f"assistant response:\n{text_content}")
            else:
                chat_history.append(f"assistant response:\n{msg['content']}")
    
    return "\n\n".join(chat_history)

async def rephrase_query(messages, cfg, api_key_manager):
    """
    Determine whether the user's query needs rephrasing for a web search,
    and return the rephrased query or 'not_needed'.

    Args:
        messages (list): The conversation messages.
        cfg (dict): Configuration settings.
        api_key_manager: API key manager instance.

    Returns:
        str: The rephrased query or "not_needed".
    """
    latest_user_msg = None
    for msg in reversed(messages):
        if msg['role'] == 'user':
            latest_user_msg = msg
            break
    
    if latest_user_msg:
        if isinstance(latest_user_msg['content'], str):
            has_text_file = bool(re.search(r'<text_file\s+name="[^"]+"\s*>', latest_user_msg['content']))
        elif isinstance(latest_user_msg['content'], list):
            has_text_file = any(
                isinstance(part.get('text', ''), str) and 
                bool(re.search(r'<text_file\s+name="[^"]+"\s*>', part.get('text', '')))
                for part in latest_user_msg['content']
            )
        else:
            has_text_file = False
            
        if has_text_file:
            logger.info("Text file detected in message, skipping rephrasing")
            return 'not_needed'
    
    # Format the chat history
    chat_history = format_chat_history(messages)
    
    # Get the latest user query
    latest_query = ""
    if latest_user_msg:
        if isinstance(latest_user_msg['content'], str):
            latest_query = latest_user_msg['content']
        elif isinstance(latest_user_msg['content'], list):
            for content_part in latest_user_msg['content']:
                if content_part.get('type') == 'text':
                    latest_query = content_part.get('text', '')
                    break
    
    # Construct the rephraser prompt with the chat history
    rephraser_prompt = '''You are an AI question rephraser. You will be given a conversation and a follow-up question,  you will have to rephrase the follow up question so it is a standalone question and can be used by another LLM to search the web for information to answer it.
If it is a smple writing task or a greeting (unless the greeting contains a question after it) like Hi, Hello, How are you, etc. than a question then you need to return `not_needed` as the response (This is because the LLM won't need to search the web for finding information on this topic).
You must always return the rephrased question inside the `question` XML block.

There are several examples attached for your reference inside the below \`examples\` XML block

<examples>
1. Follow up question: What is the capital of France
Rephrased question:`
<question>
Capital of france
</question>
`

2. Hi, how are you?
Rephrased question\`
<question>
not_needed
</question>
`

3. Follow up question: What is Docker?
Rephrased question: \`
<question>
What is Docker
</question>
`
</examples>

Anything below is the part of the actual conversation and you need to use conversation and the follow-up question to rephrase the follow-up question as a standalone question based on the guidelines shared above.

<conversation>
{chat_history}
</conversation>

Follow up question: {query}
Rephrased question:'''

    formatted_prompt = rephraser_prompt.format(
        chat_history=chat_history,
        query=latest_query
    )

    rephraser_provider = cfg.get('rephraser_provider', 'openai')
    rephraser_model = cfg.get('rephraser_model', 'gpt-4')
    api_key = await api_key_manager.get_next_api_key(rephraser_provider)
    if not api_key:
        api_key = 'sk-no-key-required'

    # Build messages for the LLM API, including multimodal content if present
    api_messages = []
    
    # Add the system message
    api_messages.append({"role": "system", "content": "You are a concise assistant that rephrases questions."})
    
    # Add the user message with the formatted prompt and any images
    user_message = {"role": "user", "content": formatted_prompt}
    
    # If the latest user message contains images and we're using a vision model,
    # add the images to the LLM API call
    if (latest_user_msg and 
        isinstance(latest_user_msg['content'], list) and 
        any(x in rephraser_model.lower() for x in ["gpt-4-vision", "gpt-4o", "claude-3", "gemini", "vision"])):
        
        # Extract images from the latest user message
        images = [item for item in latest_user_msg['content'] 
                 if item.get('type') == 'image_url']
        
        if images:
            # Construct multimodal content with the prompt text and images
            multimodal_content = [{"type": "text", "text": formatted_prompt}]
            multimodal_content.extend(images)
            user_message["content"] = multimodal_content
    
    api_messages.append(user_message)

    kwargs = {
        "model": rephraser_model,
        "messages": api_messages,
        "stream": False,
        "api_key": api_key,
        **cfg.get("rephraser_extra_api_parameters", {})
    }

    if rephraser_provider == "google":
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
    
    # Log the payload with sensitive data redacted
    logging_kwargs = json.loads(json.dumps(kwargs, default=str))
    for message in logging_kwargs.get('messages', []):
        if isinstance(message.get('content'), list):
            for item in message['content']:
                if item.get('type') == 'image_url' and 'url' in item.get('image_url', {}):
                    item['image_url']['url'] = truncate_base64(item['image_url']['url'])
        elif isinstance(message.get('content'), str):
            pass
            
    logger.info(f"Rephraser payload:\n{json.dumps(logging_kwargs, indent=2, default=str)}")
    
    # ---- RETRY LOOP FOR REPHRASER CALL ----
    max_retries = 5
    response = None
    for i in range(max_retries):
        try:
            logger.info("Attempt %d for rephraser model using API key: %s", i+1, kwargs.get("api_key"))
            response = await acompletion(**kwargs)
            break
        except Exception as e:
            logger.exception("Error while calling rephraser model, retrying with new API key. Attempt %d/%d", i+1, max_retries)
            kwargs["api_key"] = await api_key_manager.get_next_api_key(rephraser_provider)
            if i == max_retries - 1:
                return 'not_needed'
    # ---- END RETRY LOOP ----

    if response is None:
        return 'not_needed'

    content = response.choices[0].message.content.strip()
    try:
        match = re.search(r'<question>\s*(.*?)\s*</question>', content, re.DOTALL)
        if match:
            latest_user_query = match.group(1).strip()
            return latest_user_query
        else:
            logger.warning("No <question> tags found in rephraser response.")
            return 'not_needed'
    except Exception:
        logger.warning("Failed to parse response in rephraser response.")
        return 'not_needed'
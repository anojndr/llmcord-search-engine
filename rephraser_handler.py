import logging
import json
import re
from datetime import datetime as dt

from litellm import acompletion

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

def truncate_base64(base64_string, max_length=50):
    """Truncates a base64 string for logging purposes."""
    if len(base64_string) > max_length:
        return base64_string[:max_length] + "..."
    return base64_string

async def rephrase_query(messages, cfg, api_key_manager):
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

    rephraser_messages = [dict(m) for m in messages]

    rephraser_instruction = cfg.get('rephraser_instruction')
    if not rephraser_instruction:
        rephraser_instruction = '''You are {{Riley}}, an AI query rephraser. Your goal is to help {{user}} get accurate information by determining when web searches are needed and rephrasing queries appropriately.

- Local Information: If the questions require information about the user's location, such as the weather, local businesses, or events rephrase the query.
- Freshness: If up-to-date information on a topic could potentially change or enhance the answer, rehprase the query any time you would otherwise refuse to answer a question because your knowledge might be out of date.
- Niche Information: If the answer would benefit from detailed information not widely known or understood (which might be found on the internet), use web sources directly rather than relying on the distilled knowledge from pretraining.
- Accuracy: If the cost of a small mistake or outdated information is high (e.g., using an outdated version of a software library or not knowing the date of the next game for a sports team), then rephrase the query.

<example 1>
{{user}}: who was George Washington

{{Riley}}: 
<latest_user_query>
Who was George Washington?
</latest_user_query>
</example 1>

<example 2>
{{user}}: which app promotes more sexual thirst trap content, tiktok or instagram

{{Riley}}: 
<latest_user_query>
Which app promotes more sexual thirst trap content, tiktok or instagram?
</latest_user_query>

{{user}}: search reddit

{{Riley}}: 
<latest_user_query>
Which app promotes more sexual thirst trap content, tiktok or instagram? reddit
</latest_user_query>
</example 2>

<example 3>
{{user}}: Can you help me solve this math problem: 15 * 24?

{{Riley}}: 
<latest_user_query>
not_needed
</latest_user_query>
</example 3>

<example 4>
{{user}}: What's your favorite color?

{{Riley}}: 
<latest_user_query>
not_needed
</latest_user_query>

{{user}}: Why do you like that color?

{{Riley}}: 
<latest_user_query>
not_needed
</latest_user_query>
</example 4>

<example 5>
{{user}}: latest news

{{Riley}}: 
<latest_user_query>
Latest news
</latest_user_query>

{{user}}: summarize to 1 sentence

{{Riley}}: 
<latest_user_query>
not_needed
</latest_user_query>
</example 5>

### Chat History Integration:
- If the latest query is a follow-up, reuse context to form a complete query
- For short follow-ups, explicitly link them to the previous topic

### Output Format:
- Web search required: Return rephrased query in `<latest_user_query>`
- No web search needed: Return `<latest_user_query>not_needed</latest_user_query>`

Always output your final response within:
<latest_user_query>
...rephrased query or not_needed...
</latest_user_query>'''

    latest_user_idx = None
    for idx in reversed(range(len(rephraser_messages))):
        if rephraser_messages[idx]['role'] == 'user':
            latest_user_idx = idx
            break

    if latest_user_idx is not None:
        for idx, msg in enumerate(rephraser_messages):
            if msg['role'] == 'user':
                timestamp_str = msg.get('timestamp')
                if timestamp_str:
                    try:
                        timestamp = dt.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S.%f%z")
                    except ValueError:
                        try:
                            timestamp = dt.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S.%f")
                        except ValueError:
                            timestamp = dt.now()
                else:
                    timestamp = dt.now()
                
                formatted_timestamp = timestamp.strftime("%b %d, %Y %I:%M:%S %p")
                label = f"Latest Query ({formatted_timestamp}): " if idx == latest_user_idx else f"Previous Query ({formatted_timestamp}): "
                
                if isinstance(msg['content'], list):
                    for part in msg['content']:
                        if part.get('type') == 'text':
                            part['text'] = label + part.get('text', '')
                            break
                    else:
                        msg['content'].insert(0, {'type': 'text', 'text': label})
                elif isinstance(msg['content'], str):
                    msg['content'] = label + msg['content']

    for i in range(len(rephraser_messages) - 1, -1, -1):
        if rephraser_messages[i]['role'] == 'user':
            original_content = rephraser_messages[i]['content']
            if isinstance(original_content, list):
                rephraser_messages[i]['content'] = [{'type': 'text', 'text': rephraser_instruction + '\n'}] + original_content
            elif isinstance(original_content, str):
                rephraser_messages[i]['content'] = rephraser_instruction + '\n' + original_content
            else:
                rephraser_messages[i]['content'] = rephraser_instruction + '\n' + str(original_content)
            break

    rephraser_provider = cfg.get('rephraser_provider', 'openai')
    rephraser_model = cfg.get('rephraser_model', 'gpt-4')
    api_key = await api_key_manager.get_next_api_key(rephraser_provider)
    if not api_key:
        api_key = 'sk-no-key-required'

    kwargs = {
        "model": rephraser_model,
        "messages": rephraser_messages,
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

    # ---- RETRY LOOP FOR REPHRASER CALL ----
    max_retries = 3
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
        match = re.search(r'<latest_user_query>\s*(.*?)\s*</latest_user_query>', content, re.DOTALL)
        if match:
            latest_user_query = match.group(1).strip()
            return latest_user_query
        else:
            logger.warning("No <latest_user_query> tags found in rephraser response.")
            return 'not_needed'
    except Exception:
        logger.warning("Failed to parse response in rephraser response.")
        return 'not_needed'
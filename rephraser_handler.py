import logging
import json
import re
from datetime import datetime as dt

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

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
        rephraser_instruction = '''You are {{Riley}}, an AI query rephraser. Your goal is to help {{user}} get accurate information by determining when web searches are needed and rephrasing queries appropriately. You aim to be clear, concise, and helpful while maintaining a friendly demeanor.

### When to Search:
1. Queries about specific people, places, events, or facts
2. Current events, news, or recent developments
3. Statistical data, numbers, or metrics
4. Specific product information or reviews
5. Technical specifications or documentation
6. Academic research or scientific findings
7. Historical information or dates
8. Quotes or statements attributed to people
9. Market prices, rates, or economic data
10. Legal information or regulations

### When NOT to Search:
1. Basic greetings or conversation
2. Mathematical calculations
3. General concepts or theories
4. Hypothetical scenarios
5. Opinion-based questions
6. Creative writing requests
7. Logic puzzles
8. Personal preferences
9. Coding help (unless looking for specific documentation)
10. {{user}} explicitly requests no search

### Primary Override Rule:
If {{user}} indicates they don't want a web search (e.g., "don't search", "without looking it up", etc.), immediately return `not_needed` regardless of other conditions.

### Examples with Web Search:

<web search example 1>
{{user}}: who was George Washington

{{Riley}}: 
<latest_user_query>
Who was George Washington?
</latest_user_query>
</web search example 1>

<web search example 2>
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
</web search example 2>

### Examples without Web Search:

<no web search example 1>
{{user}}: Can you help me solve this math problem: 15 * 24?

{{Riley}}: 
<latest_user_query>
not_needed
</latest_user_query>
</no web search example 1>

<no web search example 2>
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
</no web search example 2>

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

    rephraser_model = cfg.get('rephraser_model', 'openai/gpt-4o')
    provider, model = rephraser_model.split('/', 1)
    base_url = cfg["providers"][provider]["base_url"]

    api_key = await api_key_manager.get_next_api_key(provider)
    if not api_key:
        api_key = 'sk-no-key-required'

    rephraser_openai_client = AsyncOpenAI(base_url=base_url, api_key=api_key)

    kwargs = dict(
        model=model,
        messages=rephraser_messages,
        stream=False,
        extra_body=cfg.get("rephraser_extra_api_parameters", {})
    )

    logger.info(f"Payload being sent to LLM API for rephraser:\n{json.dumps(kwargs, indent=2, default=str)}")

    try:
        response = await rephraser_openai_client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content.strip()
        try:
            match = re.search(r'<latest_user_query>\s*(.*?)\s*</latest_user_query>', content, re.DOTALL)
            if match:
                latest_user_query = match.group(1).strip()
                return latest_user_query
            else:
                logger.warning("No <latest_user_query> tags found in rephraser response.")
                return 'not_needed'
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON in rephraser response.")
            return 'not_needed'
    except Exception as e:
        logger.exception("Error while calling rephraser model")
        return 'not_needed'
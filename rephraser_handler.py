import logging
import json
import re
from datetime import datetime as dt

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

async def rephrase_query(messages, cfg, api_key_manager):
    rephraser_messages = [dict(m) for m in messages]

    rephraser_instruction = cfg.get('rephraser_instruction')
    if not rephraser_instruction:
        rephraser_instruction = '''You are an AI query rephraser. Your task is to analyze the latest user query and chat history (if available).

Rephrase the latest user query in these cases:
1. If it requires external or web-based information to be answered
2. If it mentions any person's name (even if the query seems answerable without a search)
3. If the user explicitly requests a web search
Do NOT rephrase if the user explicitly requests no web search.

If the query can be fully addressed using the chat history, or if it is a greeting, basic writing request, or task that doesn't necessitate a web search (and doesn't fall into cases 1-3 above), return `not_needed`.

### Key Rules:
1. **Mandatory Search Cases**:
   - Any query containing a person's name
   - Any query where the user requests a search
   - Any query requiring external information

2. **Chat History Integration**:  
   - If the latest query is a follow-up to a previous question or statement in the chat history, **reuse the context** to form a complete and accurate query.  
   - For short follow-ups (e.g., single words like "Diabetes?" or "Arizona?"), **explicitly link them to the previous query's topic**.  
   - Example 1:  
     Previous Query: *"Why do salty foods suddenly taste more salty to me?"*  
     Latest Query: *"Diabetes?"* → Rephrased: *"Does diabetes cause salty foods to taste more salty?"*  
   - Example 2:  
     Previous Query: *"What percentage of people in New York City own a car?"*  
     Latest Query: *"Arizona?"* → Rephrased: *"What is the percentage of people in Arizona who own a car?"*  
   - Example 3:  
     Previous Query: *"The sky is not blue"*  
     Latest Query: *"Fact check"* → Rephrased: *"Is the sky not blue?"*

3. **Website-Specific Requests**:  
   If the user requests focus on a specific website (e.g., Reddit), append the site name (e.g., `reddit`) to the rephrased query. Adapt this for any specified site.

4. **No-Search Override**:
   If the user explicitly requests no web search, return `not_needed` regardless of other conditions.

### Examples:
<examples>

<!-- Person name triggers search -->
Latest Query: Write a poem about trees like Robert Frost
Rephrased:
<latest_user_query>
Robert Frost tree poems
</latest_user_query>

<!-- User requests search -->
Latest Query: Can you search for information about photosynthesis?
Rephrased:
<latest_user_query>
photosynthesis process explanation
</latest_user_query>

<!-- User requests no search -->
Latest Query: Tell me about Einstein but don't search the web
Rephrased:
<latest_user_query>
not_needed
</latest_user_query>

<!-- Follow-up with chat history -->
Previous Query: Why do salty foods suddenly taste more salty to me?  
Latest Query: Diabetes?  
Rephrased:  
<latest_user_query>  
Does diabetes cause salty foods to taste more salty?  
</latest_user_query>  

Previous Query: What percentage of people in New York City own a car?  
Latest Query: Arizona?  
Rephrased:  
<latest_user_query>  
What is the percentage of people in Arizona who own a car?  
</latest_user_query>  

<!-- Website-specific -->  
Latest Query: Find Reddit opinions about electric cars  
Rephrased:  
<latest_user_query>  
Electric cars reddit  
</latest_user_query>  

<!-- Basic no-web cases -->  
Latest Query: Hi, how are you?  
Rephrased:  
<latest_user_query>  
not_needed  
</latest_user_query>  

<!-- Web-dependent with history -->  
Previous Query: When did NASA launch the James Webb Telescope?  
Latest Query: Any updates on its findings?  
Rephrased:  
<latest_user_query>  
James Webb Telescope recent findings 2023  
</latest_user_query>  
</examples>

### Output Format:
- **Web search required**: Return rephrased query in `<latest_user_query>`.  
- **No web search needed**: Return `<latest_user_query>not_needed</latest_user_query>`.  
- **User requests no search**: Return `<latest_user_query>not_needed</latest_user_query>` regardless of other conditions.

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
    base_url = cfg['providers'][provider]['base_url']

    api_key = await api_key_manager.get_next_api_key(provider)
    if not api_key:
        api_key = 'sk-no-key-required'

    rephraser_openai_client = AsyncOpenAI(base_url=base_url, api_key=api_key)

    kwargs = dict(
        model=model,
        messages=rephraser_messages,
        stream=False,
        extra_body=cfg.get('rephraser_extra_api_parameters', {})
    )

    logger.info(f"Payload being sent to LLM API for rephraser:\n{json.dumps(kwargs, indent=2, default=str)}")

    try:
        response = await rephraser_openai_client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content.strip()

        match = re.search(r'<latest_user_query>\s*(.*?)\s*</latest_user_query>', content, re.DOTALL)
        if match:
            latest_user_query = match.group(1).strip()
            return latest_user_query
        else:
            logger.warning("No <latest_user_query> tags found in rephraser response.")
            return 'not_needed'
    except Exception as e:
        logger.exception("Error while calling rephraser model")
        return 'not_needed'
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
        rephraser_instruction = '''You are {{Riley}}, an AI query rephraser. Your sole objective is to assist {{user}} by deciding whether a query must be rephrased to perform a web search, and then outputting the rephrased query in the proper format. Under no circumstances should you include a web search prompt if the query clearly relates to general factual, timeless, or internally solvable questions.

Your rules are as follows:

• Strict Local Information Requirement:
  – If the user’s query explicitly requests information regarding their or another location (e.g., weather forecasts, local business details, real-time events, public transit information), then you must rephrase the query for web search.
  – Do not perform a web search for questions that do not specify a geographic context.

• Strict Freshness Requirement:
  – If the query requests information that is likely to have changed recently (e.g., “current”, “latest”, “today”, “now”), or if you would otherwise have to state that your pretraining data might be outdated (e.g., current software versions, upcoming event schedules, stock prices), always rephrase the query to enforce a web search.
  – If no such timely qualifier is mentioned, assume no search is needed.

• Strict Niche or Specialized Data Requirement:
  – If the answer depends on detailed, specialized, or less widely-known knowledge that typically would only be found by consulting current web sources (for instance, obscure research results, detailed technical documentation for cutting-edge software, or niche community opinions), rephrase the query for a web search.
  – In the absence of clear niche or specialized requirements, do not add a search component.

• Accuracy Under High Risk:
  – Where the consequences of an inaccuracy are high (such as using an outdated code library, mis-timing a live event, or providing incorrect regulatory/legal details), always require a web search.
  – Only rely on your pretraining if the error risk is negligible.

• Explicit Web Search Instruction:
  – If the user explicitly provides a follow-up instruction that includes “search”, “find on”, “lookup”, or any similar command targeting a web search, then you must rephrase the original query and append it exactly as instructed (only if it meets one or more of the above conditions).
  – Otherwise, ignore such an instruction if the query does not meet the strict conditions outlined.

--------------------------------------------------

Examples:

Example 1:
{{user}}: Who was George Washington?

{{Riley}}:
<latest_user_query>
Who was George Washington?
</latest_user_query>

Explanation: This is a well-established factual question. No fresh or niche data is required, so use internal knowledge only.

Example 2:
{{user}}: Which app promotes more sexual thirst trap content, TikTok or Instagram?

{{Riley}}:
<latest_user_query>
Which app promotes more sexual thirst trap content, TikTok or Instagram?
</latest_user_query>

{{user}}: search reddit

{{Riley}}:
<latest_user_query>
Which app promotes more sexual thirst trap content, TikTok or Instagram? reddit
</latest_user_query>

Explanation: The explicit “search reddit” instruction (combined with a subjective or niche comparison) forces a web search.

Example 3:
{{user}}: Can you help me solve this math problem: 15 * 24?

{{Riley}}:
<latest_user_query>
not_needed
</latest_user_query>

Explanation: This calculation is straightforward and does not require external data.

Example 4:
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

Explanation: Personal or opinion-based questions do not trigger a web search.

Example 5:
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

Explanation: The query "latest news" requires current, up-to-date info so a web search is triggered. However, once a follow-up asks for summarization, which uses already retrieved information, no new search is needed.

--------------------------------------------------

Chat History Integration:
• If the latest query is a follow-up to a previous one, reuse the context to form a complete and self-contained query.
• For very short follow-ups, explicitly link them to the prior topic to maintain clarity.

--------------------------------------------------

Output Format:
• If a web search is required (by meeting any of the strict conditions above), return the rephrased query in the following format:
  <latest_user_query>
  …rephrased query…
  </latest_user_query>
 
• If no web search is required, output:
  <latest_user_query>
  not_needed
  </latest_user_query>

--------------------------------------------------

Always output your final response within the <latest_user_query> tags exactly as specified.'''

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
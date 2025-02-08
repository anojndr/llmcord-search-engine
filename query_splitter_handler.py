import logging
import json
import re

from litellm import acompletion

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

async def split_query(query, cfg, api_key_manager):
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

    formatted_prompt = query_splitter_prompt.format(query=query)

    query_splitter_provider = cfg.get('query_splitter_provider', 'openai')
    query_splitter_model = cfg.get('query_splitter_model', 'gpt-4')
    api_key = await api_key_manager.get_next_api_key(query_splitter_provider)
    if not api_key:
        api_key = 'sk-no-key-required'

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

    if query_splitter_provider == "google":
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

    logger.info(f"Payload being sent to LLM API for query_splitter:\n{json.dumps(kwargs, indent=2, default=str)}")

    try:
        response = await acompletion(**kwargs)
        content = response.choices[0].message.content.strip()
        try:
            match = re.search(r'\[.*\]', content, re.DOTALL)
            if match:
                json_content = match.group(0)
                queries = json.loads(json_content)
                if isinstance(queries, list) and all(isinstance(q, str) for q in queries):
                    return queries
                else:
                    logger.warning("Invalid JSON array format in query_splitter response.")
                    return [query]
            else:
                logger.warning("No JSON array found in query_splitter response.")
                return [query]
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON in query_splitter response.")
            return [query]
    except Exception as e:
        logger.exception("Error while calling query_splitter model")
        return [query]
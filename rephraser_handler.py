import logging
import json
import re

from openai import AsyncOpenAI

async def rephrase_query(messages, cfg):
    rephraser_messages = [dict(m) for m in messages]

    rephraser_instruction = cfg.get('rephraser_instruction')
    if not rephraser_instruction:
        rephraser_instruction = '''You are an AI question rephraser. You will be given the latest user query **and any relevant conversation context**, which may include the previous user query or the previous assistant response. **You must use that conversation context as much as possible** to understand and preserve any details necessary to form a standalone, self-contained question.

Only rephrase the latest user query if it **requires external or web-based information** to be answered. If the query can be fully answered using the current conversation context alone or is simply a greeting or a basic writing/task request that does not need a web search, then return `not_needed`.

You must always return the rephrased question inside the `latest_user_query` XML block if a rephrasing is necessary.

Below are several examples for your reference inside the `examples` XML block:

<examples>

Latest user query: Hi, how's it going?  
Rephrased Latest user query:  
<latest_user_query>  
not_needed  
</latest_user_query>  

Latest user query: Please multiply 6 by 7  
Rephrased Latest user query:  
<latest_user_query>  
not_needed  
</latest_user_query>  

Latest user query: Search for the 2023 NBA draft order  
Rephrased Latest user query:  
<latest_user_query>  
2023 NBA draft order  
</latest_user_query>  

Latest user query: I'd like to check if there's a new Android version release  
Rephrased Latest user query:  
<latest_user_query>  
New Android version release  
</latest_user_query>  

Previous user query: I want to find the best YouTube channel for learning piano  
Latest user query: Could you check if there’s any recent ranking of top piano channels?  
Rephrased Latest user query:  
<latest_user_query>  
Recent ranking of top piano channels  
</latest_user_query>  

Previous user query: How do I fold an origami crane?  
Latest user query: Can you walk me through that method again?  
Rephrased Latest user query:  
<latest_user_query>  
not_needed  
</latest_user_query>  

Previous assistant response: The singer Adele was born in 1988  
Latest user query: Can you see if she announced any new tour dates?  
Rephrased Latest user query:  
<latest_user_query>  
Adele new tour dates  
</latest_user_query>  

Previous assistant response: The Pythagorean theorem states that a² + b² = c²  
Latest user query: So how do I use that to check if my triangle is right-angled?  
Rephrased Latest user query:  
<latest_user_query>  
not_needed  
</latest_user_query>  

</examples>

You must ensure that if the latest user query or the context indicates no need for an external web search, you respond with `not_needed`. Otherwise, rephrase the query into a standalone question that accurately conveys the user’s intent using whatever context is available. Always output your final rephrased query within:

<latest_user_query>
...rephrased query...
</latest_user_query>

If no rephrasing is needed (i.e., a web search is not required), respond with:

<latest_user_query>
not_needed
</latest_user_query>

Latest user query:'''

    rephraser_model = cfg.get('rephraser_model', 'openai/gpt-4o')
    provider, model = rephraser_model.split('/', 1)
    base_url = cfg['providers'][provider]['base_url']
    api_key = cfg['providers'][provider].get('api_key', 'sk-no-key-required')

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
    else:
        logging.warning("No user message found to prepend the rephraser instruction.")

    rephraser_openai_client = AsyncOpenAI(base_url=base_url, api_key=api_key)

    kwargs = dict(
        model=model,
        messages=rephraser_messages,
        stream=False,
        extra_body=cfg.get('rephraser_extra_api_parameters', {})
    )

    logging.info(f"Payload being sent to LLM API for rephraser:\n{json.dumps(kwargs, indent=2, default=str)}")

    try:
        response = await rephraser_openai_client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content.strip()

        match = re.search(r'<latest_user_query>\s*(.*?)\s*</latest_user_query>', content, re.DOTALL)
        if match:
            latest_user_query = match.group(1).strip()
            return latest_user_query
        else:
            logging.warning("No <latest_user_query> tags found in rephraser response.")
            return 'not_needed'
    except Exception as e:
        logging.exception("Error while calling rephraser model")
        return 'not_needed'
import logging
import json
import re

from openai import AsyncOpenAI

async def rephrase_query(messages, cfg, api_key_manager):
    rephraser_messages = [dict(m) for m in messages]

    rephraser_instruction = cfg.get('rephraser_instruction')
    if not rephraser_instruction:
        rephraser_instruction = '''You are an AI query rephraser. Your task is to analyze the latest user query **along with any relevant conversation context**, which may include the previous user query or the assistant’s response. **Use this context as much as possible** to ensure the rephrased query is standalone and self-contained, preserving all necessary details.

Rephrase the latest user query **only if it requires external or web-based information** to be answered. If the query can be fully addressed using the current conversation context alone, or if it is a greeting, basic writing request, or task that doesn’t necessitate a web search, simply return `not_needed`.

**If the user specifically requests a focus on a particular website (e.g., Reddit), append `site:[website]` to the rephrased query to ensure results are limited to that site. For example, if the user asks for Reddit-focused information, append `site:reddit.com` to the query. This mechanism should be adaptable to any website specified by the user.**

When a rephrasing is necessary, always enclose the rephrased query within the `latest_user_query` XML block.

For reference, examples are provided within the `examples` XML block below:

<examples>

<!-- Case 1: Query that doesn't need web search -->  
Latest user query: Hi, how's it going?  
Rephrased Latest user query:  
<latest_user_query>  
not_needed  
</latest_user_query>  

Latest user query: Please add 15 and 20  
Rephrased Latest user query:  
<latest_user_query>  
not_needed  
</latest_user_query>  

<!-- Case 2: Query that needs web search -->  
Latest user query: Search for the 2023 NBA draft order  
Rephrased Latest user query:  
<latest_user_query>  
2023 NBA draft order  
</latest_user_query>  

Latest user query: Find the release date of the iPhone 15  
Rephrased Latest user query:  
<latest_user_query>  
iPhone 15 release date  
</latest_user_query>  

<!-- Case 3: Query that doesn't need web search with previous user query given -->  
Previous user query: How do I fold an origami crane?  
Latest user query: Can you walk me through that method again?  
Rephrased Latest user query:  
<latest_user_query>  
not_needed  
</latest_user_query>  

Previous user query: What’s the capital of France?  
Latest user query: Can you repeat that?  
Rephrased Latest user query:  
<latest_user_query>  
not_needed  
</latest_user_query>  

<!-- Case 4: Query that needs web search with previous user query given -->  
Previous user query: I want to find the best YouTube channel for learning piano  
Latest user query: Could you check if there’s any recent ranking of top piano channels?  
Rephrased Latest user query:  
<latest_user_query>  
Recent ranking of top piano channels  
</latest_user_query>  

Previous user query: What’s the best way to learn Python?  
Latest user query: Can you find beginner-friendly Python tutorials?  
Rephrased Latest user query:  
<latest_user_query>  
Beginner-friendly Python tutorials  
</latest_user_query>  

<!-- Case 5: Query that doesn't need web search with previous assistant response given -->  
Previous assistant response: The Pythagorean theorem states that a² + b² = c²  
Latest user query: So how do I use that to check if my triangle is right-angled?  
Rephrased Latest user query:  
<latest_user_query>  
not_needed  
</latest_user_query>  

Previous assistant response: The Earth’s circumference is approximately 40,075 km  
Latest user query: Can you convert that to miles?  
Rephrased Latest user query:  
<latest_user_query>  
not_needed  
</latest_user_query>  

<!-- Case 6: Query that needs web search with previous assistant response given -->  
Previous assistant response: The singer Adele was born in 1988  
Latest user query: Can you see if she announced any new tour dates?  
Rephrased Latest user query:  
<latest_user_query>  
Adele new tour dates  
</latest_user_query>  

Previous assistant response: The Mars Rover landed in February 2021  
Latest user query: Can you find updates on its recent discoveries?  
Rephrased Latest user query:  
<latest_user_query>  
Mars Rover recent discoveries 2023  
</latest_user_query>  

<!-- Case 7: Query that doesn't need web search with image given -->  
Latest user query: Can you describe this image of a cat?  
Rephrased Latest user query:  
<latest_user_query>  
not_needed  
</latest_user_query>  

Latest user query: What’s the color of the car in this picture?  
Rephrased Latest user query:  
<latest_user_query>  
not_needed  
</latest_user_query>  

<!-- Case 8: Query that needs web search with image given (text content focus) -->  
Latest user query: Can you fact-check the claim in this image?  
Rephrased Latest user query:  
<latest_user_query>  
Fact check [text in the image]  
</latest_user_query>  

Latest user query: What’s the source of the quote in this picture?  
Rephrased Latest user query:  
<latest_user_query>  
Source of the quote: [text in the image]  
</latest_user_query>    

<!-- Case 9: Query for the site:[site] feature -->  
Latest user query: Find Reddit discussions about the best budget laptops  
Rephrased Latest user query:  
<latest_user_query>  
Best budget laptops site:reddit.com  
</latest_user_query>  

Latest user query: Search for Quora answers about time management tips  
Rephrased Latest user query:  
<latest_user_query>  
Time management tips site:quora.com  
</latest_user_query>  

</examples>

You must ensure that if the latest user query or the context indicates no need for an external web search, you respond with `not_needed`. Otherwise, rephrase the query into a standalone query that accurately conveys the user’s intent using whatever context is available. Always output your final rephrased query within:

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

    api_key = await api_key_manager.get_next_api_key(provider)
    if not api_key:
        api_key = 'sk-no-key-required'

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
<h1 align="center">
  llmcord_search_engine
</h1>

<h3 align="center"><i>
  Talk to internet-connected LLMs with your friends on Discord!
</i></h3>

<p align="center">
  <img src="https://github.com/jakobdylanc/llmcord/assets/38699060/789d49fe-ef5c-470e-b60e-48ac03057443" alt="">
</p>

llmcord_search_engine transforms Discord into a collaborative AI frontend with real-time internet search capabilities. Building on the original llmcord project, this expanded version connects to virtually any LLM API and enhances interactions with web search, content extraction, and image processing.

## New Features in llmcord_search_engine

### 🔍 Internet Search Integration
- **Automatic search detection**: The bot intelligently determines when a query needs internet search and performs it automatically
- **Multi-provider search**: Uses SearxNG with fallbacks to Serper and Bing, feeding all search results to the LLM for intelligent answers
- **Image search results**: Search results include relevant images that can be displayed with a click
- **URL content extraction**: Automatically extracts content from web pages, PDFs, and other sources and feeds it to the LLM for processing

### 📱 Special Content Handlers
- **YouTube integration**: Extracts video content, transcripts, and comments to feed directly to the LLM for intelligent processing
- **Reddit integration**: Extracts post content, metadata, and comments for LLM analysis and summarization
- **Image analysis**: Use "sauce" keyword with an image for SauceNAO-based reverse image search results that are analyzed by the LLM
- **Image search**: Use "lens" keyword with an image for Google Lens-like visual search with LLM-processed results

### 🖼️ Image Generation
- **AI image generation**: Create images with the `/generateimage` command

### 🧠 Enhanced LLM Integration
- **Model switching**: Change models with the `/model` command
- **Query optimization**: Automatically splits and rephrases queries for better results
- **Multiple provider support**: Use OpenAI, Claude, Mistral, Google, xAI and more 
- **API key rotation**: Built-in key management to avoid rate limits

## Core Features (From Original llmcord)

### Reply-based chat system
Just @ the bot to start a conversation and reply to continue. Build conversations with reply chains!

You can:
- Branch conversations endlessly
- Continue other people's conversations
- @ the bot while replying to ANY message to include it in the conversation

Additionally:
- When DMing the bot, conversations continue automatically (no reply required). To start a fresh conversation, just @ the bot. You can still reply to continue from anywhere.
- You can branch conversations into [threads](https://support.discord.com/hc/en-us/articles/4403205878423-Threads-FAQ). Just create a thread from any message and @ the bot inside to continue.

### Choose any LLM
llmcord_search_engine supports remote models from:
- [OpenAI API](https://platform.openai.com/docs/models) (including GPT-4o)
- [Claude API](https://docs.anthropic.com/claude/reference/getting-started-with-the-api) (Claude 3 family)
- [xAI API](https://docs.x.ai/docs/models) (Grok models)
- [Mistral API](https://docs.mistral.ai/getting-started/models/models_overview)
- [Groq API](https://console.groq.com/docs/models)
- [Google API](https://ai.google.dev/models) (Gemini models)
- [TogetherAI API](https://docs.together.ai/reference/models)
- [OpenRouter API](https://openrouter.ai/models)

Or run a local model with:
- [Ollama](https://ollama.com)
- [LM Studio](https://lmstudio.ai)
- [vLLM](https://github.com/vllm-project/vllm)

## Project Structure

The codebase has been completely restructured from a single file into a modular architecture:

```
llmcord_search_engine
├── commands/           # Discord slash commands
├── config/             # Configuration handling
├── core/               # Core bot functionality
├── images/             # Image processing modules
├── llm/                # LLM service and handlers
├── providers/          # Content provider integrations
├── search/             # Search functionality
└── utils/              # Utility functions
```

## Setup Instructions

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/llmcord_search_engine
   cd llmcord_search_engine
   ```

2. Create a `.env` file from the example:
   ```bash
   cp .env.example .env
   ```

3. Edit the `.env` file with your Discord bot token, API keys, and settings:
   - Get a Discord bot token from [Discord Developer Portal](https://discord.com/developers/applications)
   - Add API keys for any providers you want to use (OpenAI, Claude, etc.)
   - Configure search settings (SearxNG, Serper, etc.)

4. (Optional) Set up a local SearxNG instance for search:
   ```bash
   docker run -d -p 4000:8080 searxng/searxng
   ```

5. Run the bot:

   **Without Docker:**
   ```bash
   pip install -r requirements.txt
   python main.py
   ```

   **With Docker:**
   ```bash
   docker compose up -d
   ```

## Configuration Reference

The `.env` file supports the following configuration options:

### Discord Bot Settings
```
BOT_TOKEN=your-discord-bot-token
CLIENT_ID=your-discord-client-id
STATUS_MESSAGE=your-bot-status-message
```

### Discord Permissions and Restrictions
```
ALLOW_DMS=true
ALLOWED_CHANNEL_IDS=12345,67890  # Comma-separated IDs
ALLOWED_ROLE_IDS=12345,67890     # Comma-separated IDs
BLOCKED_USER_IDS=12345,67890     # Comma-separated IDs
```

### Message Limits
```
MAX_TEXT=100000                  # Max characters per message
MAX_IMAGES=5                     # Max images per message
MAX_MESSAGES=25                  # Max messages in conversation chain
USE_PLAIN_RESPONSES=false        # Use plaintext or embeds
```

### LLM Provider Settings
```
# Each provider can have multiple comma-separated API keys
OPENAI_API_KEYS=key1,key2
CLAUDE_API_KEYS=key1,key2
XAI_API_KEYS=key1,key2
GOOGLE_API_KEYS=key1,key2
MISTRAL_API_KEYS=key1,key2
GROQ_API_KEYS=key1,key2
OPENROUTER_API_KEYS=key1,key2
```

### Default Model Configuration
```
PROVIDER=openai                     # Default provider
MODEL=gpt-4o                        # Default model
EXTRA_API_PARAMETERS_MAX_TOKENS=4096
EXTRA_API_PARAMETERS_TEMPERATURE=1
```

### Search Settings
```
SEARXNG_BASE_URL=http://localhost:4000  # Local SearxNG URL
SERPER_API_KEYS=your-serper-api-key     # Fallback search
BING_SEARCH_V7_SUBSCRIPTION_KEY=key     # Second fallback
MAX_URLS=5                              # URLs to fetch per search
```

### Special Service Settings
```
YOUTUBE_API_KEYS=your-youtube-api-key
REDDIT_CLIENT_ID=your-reddit-client-id
REDDIT_CLIENT_SECRET=your-reddit-client-secret
SAUCENAO_API_KEYS=your-saucenao-api-key
IMAGE_GEN_API_KEYS=your-image-gen-api-key
```

## Usage Examples

### Basic Conversation
Just @ the bot and chat naturally. The bot will automatically use internet search when needed.

### Custom Search
```
@bot please search for the latest updates on the James Webb Space Telescope
```

### Specialized Content Extraction
```
@bot summarize this YouTube video: https://www.youtube.com/watch?v=dQw4w9WgXcQ
```
The bot will extract the video content, transcript, and comments, then use the LLM to provide an intelligent analysis.

```
@bot what are people saying about this Reddit post: https://www.reddit.com/r/science/comments/...
```
The bot will extract the Reddit post content and comments, then use the LLM to analyze sentiment and key points.

### Image Analysis
```
@bot sauce [attach image]
@bot lens [attach image] What is this object?
```

### Image Generation
```
/generateimage A futuristic cityscape with flying cars and neon lights
```

### Model Switching
```
/model provider: openai model: gpt-4-turbo
/model provider: claude model: claude-3.7-sonnet
```

## Notes

- The bot uses a round-robin approach for API keys, so adding multiple keys per provider helps avoid rate limits.
- For best search results, set up a local SearxNG instance rather than relying on public instances.
- If using vision models (GPT-4o, Claude 3, Gemini, etc.), ensure the correct provider is set along with its image-capable model.
- The system prompt can be customized by editing `system_prompt.txt`.

## Credits

- Built upon the original [llmcord](https://github.com/jakobdylanc/llmcord) by jakobdylanc
- Uses [LiteLLM](https://github.com/BerriAI/litellm) for standardized LLM API access
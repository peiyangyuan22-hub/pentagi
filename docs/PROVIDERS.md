# LLM Provider Configuration

PentAGI supports multiple LLM backends. Set the corresponding environment variable in your `.env` file.

> Quick start: most users only need **OpenAI** or **Anthropic**. Set `OPEN_AI_KEY` or `ANTHROPIC_API_KEY` and you're done.

---

## OpenAI

| Variable | Default | Required |
|----------|---------|----------|
| `OPEN_AI_KEY` | — | Yes |
| `OPEN_AI_SERVER_URL` | `https://api.openai.com/v1` | No |

## Anthropic

| Variable | Default | Required |
|----------|---------|----------|
| `ANTHROPIC_API_KEY` | — | Yes |
| `ANTHROPIC_SERVER_URL` | `https://api.anthropic.com/v1` | No |

## Ollama (Local/Remote)

| Variable | Default | Required |
|----------|---------|----------|
| `OLLAMA_SERVER_URL` | — | Yes |
| `OLLAMA_SERVER_API_KEY` | — | No |
| `OLLAMA_SERVER_MODEL` | — | No |
| `OLLAMA_SERVER_CONFIG_PATH` | — | No |
| `OLLAMA_SERVER_PULL_MODELS_ENABLED` | `false` | No |
| `OLLAMA_SERVER_LOAD_MODELS_ENABLED` | `false` | No |
| `OLLAMA_SERVER_PULL_MODELS_TIMEOUT` | `600` | No |

Pre-built config files: `examples/configs/ollama-*.provider.yml`

## Google AI (Gemini)

| Variable | Default | Required |
|----------|---------|----------|
| `GEMINI_API_KEY` | — | Yes |
| `GEMINI_SERVER_URL` | `https://generativelanguage.googleapis.com` | No |

## AWS Bedrock

| Variable | Default | Required |
|----------|---------|----------|
| `BEDROCK_REGION` | `us-east-1` | No |
| `BEDROCK_DEFAULT_AUTH` | `false` | No |
| `BEDROCK_BEARER_TOKEN` | — | No |
| `BEDROCK_ACCESS_KEY_ID` | — | No |
| `BEDROCK_SECRET_ACCESS_KEY` | — | No |
| `BEDROCK_SESSION_TOKEN` | — | No |
| `BEDROCK_SERVER_URL` | — | No |

## DeepSeek

| Variable | Default | Required |
|----------|---------|----------|
| `DEEPSEEK_API_KEY` | — | Yes |
| `DEEPSEEK_SERVER_URL` | `https://api.deepseek.com` | No |

Config file: `examples/configs/deepseek.provider.yml`

## GLM (Zhipu AI)

| Variable | Default | Required |
|----------|---------|----------|
| `GLM_API_KEY` | — | Yes |
| `GLM_SERVER_URL` | `https://api.z.ai/api/paas/v4` | No |

## Kimi (Moonshot AI)

| Variable | Default | Required |
|----------|---------|----------|
| `KIMI_API_KEY` | — | Yes |
| `KIMI_SERVER_URL` | `https://api.moonshot.ai/v1` | No |

Config file: `examples/configs/moonshot.provider.yml`

## Qwen (Tongyi Qianwen)

| Variable | Default | Required |
|----------|---------|----------|
| `QWEN_API_KEY` | — | Yes |
| `QWEN_SERVER_URL` | `https://dashscope-us.aliyuncs.com/compatible-mode/v1` | No |

## Custom / Self-Hosted LLM

| Variable | Default | Required |
|----------|---------|----------|
| `LLM_SERVER_URL` | — | Yes |
| `LLM_SERVER_KEY` | — | No |
| `LLM_SERVER_MODEL` | — | No |
| `LLM_SERVER_PROVIDER` | — | No |
| `LLM_SERVER_CONFIG_PATH` | — | No |
| `LLM_SERVER_LEGACY_REASONING` | `false` | No |
| `LLM_SERVER_PRESERVE_REASONING` | `false` | No |

Pre-built config files in `examples/configs/`:
- `custom-openai.provider.yml`
- `deepinfra.provider.yml`
- `novita.provider.yml`
- `openrouter.provider.yml`
- `vllm-*.provider.yml`

## Embedding Models

| Variable | Default | Required |
|----------|---------|----------|
| `EMBEDDING_URL` | — | No (falls back to first LLM provider) |
| `EMBEDDING_KEY` | — | No |
| `EMBEDDING_MODEL` | — | No |
| `EMBEDDING_PROVIDER` | `openai` | No |
| `EMBEDDING_BATCH_SIZE` | `512` | No |
| `EMBEDDING_STRIP_NEW_LINES` | `true` | No |

---

## Additional Configuration

See [`backend/pkg/config/config.go`](../backend/pkg/config/config.go) for the full list of supported environment variables, including:

| Section | Key Variables |
|---------|--------------|
| **Search** | `GOOGLE_API_KEY`, `TAVILY_API_KEY`, `PERPLEXITY_API_KEY`, `SEARXNG_URL`, `DUCKDUCKGO_ENABLED` |
| **OAuth** | `OAUTH_GOOGLE_CLIENT_ID`, `OAUTH_GITHUB_CLIENT_ID` + secrets |
| **Observability** | `OTEL_HOST`, `LANGFUSE_BASE_URL`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` |
| **Knowledge Graph** | `GRAPHITI_URL`, `GRAPHITI_ENABLED` |
| **Docker** | `DOCKER_SOCKET`, `DOCKER_DEFAULT_IMAGE`, `DOCKER_DEFAULT_IMAGE_FOR_PENTEST` |
| **Proxy** | `PROXY_URL` |
| **Agent Limits** | `MAX_GENERAL_AGENT_TOOL_CALLS`, `MAX_LIMITED_AGENT_TOOL_CALLS` |
| **Execution Monitor** | `EXECUTION_MONITOR_ENABLED`, `EXECUTION_MONITOR_SAME_TOOL_LIMIT` |
| **Ollama Pull/Preload** | `OLLAMA_SERVER_PULL_MODELS_ENABLED`, `OLLAMA_SERVER_LOAD_MODELS_ENABLED` |

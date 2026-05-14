# PentAGI

<div align="center" style="font-size: 1.5em; margin: 20px 0;">
    <strong>P</strong>enetration testing <strong>A</strong>rtificial <strong>G</strong>eneral <strong>I</strong>ntelligence
</div>

<div align="center">

> Autonomous AI penetration testing — in a secure Docker sandbox.

[![Discord](https://img.shields.io/badge/Discord-7289DA?logo=discord&logoColor=white)](https://discord.gg/2xrMh7qX6m)
[![Telegram](https://img.shields.io/badge/Telegram-2CA5E0?logo=telegram&logoColor=white)](https://t.me/+Ka9i6CNwe71hMWQy)
[![Trendshift](https://trendshift.io/api/badge/repositories/15161)](https://trendshift.io/repositories/15161)
</div>

---

## Quick Start

```bash
# 1. Clone & enter
git clone https://github.com/vxcontrol/pentagi.git
cd pentagi

# 2. Configure LLM (pick one)
echo "OPEN_AI_KEY=sk-..." >> .env
# or: echo "ANTHROPIC_API_KEY=sk-..." >> .env

# 3. Launch
docker compose up
```

Open **http://localhost:8080** → tell the AI your target → it runs the pentest.

> See [docs/PROVIDERS.md](docs/PROVIDERS.md) for Ollama, Gemini, DeepSeek, GLM, Kimi, Qwen, Bedrock, custom LLM, and embedding config.

---

## Overview

PentAGI is an AI agent that autonomously plans and executes penetration tests. It uses a **supervisor + worker agent architecture**:

1. **Supervisor Agent** — plans the high-level strategy, selects tools
2. **Worker Agents** — execute individual tasks (scanning, exploitation, reporting)
3. **Sandbox** — all operations run in isolated Docker containers
4. **Memory** — knowledge graph (Graphiti) + vector embeddings for long-term context

All operations are fully autonomous — specify the target, get the report.

[▶️ Watch the overview video](https://youtu.be/R70x5Ddzs1o)

---

## Features

| Category | Details |
|----------|---------|
| 🛡 **Safe & Isolated** | Every operation runs in sandboxed Docker containers |
| 🤖 **Fully Autonomous** | AI plans, executes, and reports — no manual steps |
| 🧰 **20+ Pentest Tools** | nmap, metasploit, sqlmap, nuclei, hydra, gobuster, ffuf, and more — with step-by-step AI guidance |
| 🧠 **Knowledge Graph** | Graphiti-powered memory for cross-session context |
| 🔄 **Execution Monitor** | Optional guard rails — detects loops, tool abuse, stuck agents |
| 🗂 **Multi-module** | Reconnaissance, exploitation, privilege escalation, persistence, post-exploitation |
| 🔌 **Multi-LLM** | OpenAI, Anthropic, Ollama, Gemini, DeepSeek, GLM, Kimi, Qwen, Bedrock, self-hosted |
| 📊 **Observability** | OpenTelemetry + Langfuse tracing optional |
| 🔐 **OAuth** | Google & GitHub login optional |

---

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌────────────────┐
│  Web UI     │ ──→ │  PentAGI API  │ ──→ │  Supervisor     │
│  (React)    │     │  (Go 1.24)    │     │  Agent (LLM)    │
└─────────────┘     └──────────────┘     └───────┬────────┘
                                                  │
                         ┌────────────────────────┼────────────────────┐
                         ▼                        ▼                    ▼
                  ┌──────────────┐       ┌──────────────┐     ┌──────────────┐
                  │  Worker #1   │       │  Worker #2   │     │  Worker #N   │
                  │  nmap/scan   │       │  sqlmap/db   │     │  metasploit  │
                  └──────┬───────┘       └──────┬───────┘     └──────┬───────┘
                         │                      │                    │
                         └──────────────────────┴────────────────────┘
                                                  │
                                          ┌───────┴────────┐
                                          │  Docker Sandbox │
                                          │  (isolated net) │
                                          └────────────────┘
```

---

## Development

```bash
# Install pre-commit hooks
make pre-commit-install

# Run backend tests
make test

# Run linter
make lint

# Start dev environment
make dev

# Build binaries
make build
```

See the [Makefile](Makefile) for all targets (`make help`).

---

## Credits

- **Original Authors**: VXControl & PentAGI Team
- **License**: MIT — see [LICENSE](LICENSE)

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=vxcontrol/pentagi&type=Date)](https://star-history.com/#vxcontrol/pentagi&Date)

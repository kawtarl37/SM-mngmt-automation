# automation-EGF

Automation workflows built on a **3-layer agent architecture** that separates human intent from deterministic execution.

## Architecture

| Layer | Role | Location |
|-------|------|----------|
| **Directive** | SOPs — _what_ to do | `directives/` |
| **Orchestration** | AI decision-making — _how_ to route | (the LLM) |
| **Execution** | Deterministic Python scripts — _doing_ the work | `execution/` |

## Directory Structure

```
├── directives/      # Markdown SOPs (instruction set)
├── execution/       # Python scripts (deterministic tools)
├── .tmp/            # Intermediate files (never committed)
├── .env             # API keys & secrets (never committed)
├── credentials.json # Google OAuth credentials (never committed)
├── token.json       # Google OAuth token (never committed)
├── Agents.md        # Shared agent instructions
├── CLAUDE.md        # ↳ mirrored
├── GEMINI.md        # ↳ mirrored
└── README.md
```

## Getting Started

1. Copy `.env` and fill in your API keys.
2. Place Google OAuth `credentials.json` in the project root.
3. Add directives to `directives/` and scripts to `execution/`.

See **Agents.md** for the full operating guide.

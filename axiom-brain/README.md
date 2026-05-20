# axiom-brain

**Layer 4 — Inference orchestration.**

Multi-provider inference with intent routing, tool calls, and memory management. The decision layer that picks between Claude, GPT, and the local Qwen3 4B model based on the task.

## Responsibility

- Provider abstraction for Anthropic, OpenAI, and Ollama
- Intent classification and routing rules
- Tool-calling loop (inference → parse → execute → re-inject)
- Memory commands (read, write, summarize)
- Context overflow handling via summarization

## Status

Not yet implemented. Phase 4 (Weeks 12–15).

# Documentation index

| Document | What it covers | Status |
|---|---|---|
| [progress-log.md](progress-log.md) | Dated log of every step and decision | Ongoing |
| [ai-integration.md](ai-integration.md) | AI providers, free keys, limits, switching | Done |
| [decisions/](decisions/) | Architecture decision records | 8 accepted |
| [../reports/](../reports/README.md) | Published evaluation results | Done |
| [architecture.md](architecture.md) | Components and technology choices | Done (agent and tools) |
| [system-design.md](system-design.md) | Layers, tool catalogue, rule locations | Tool server done |
| [workflows.md](workflows.md) | How each kind of message is handled, with diagrams | Done |
| Diagrams | Mermaid diagrams live inline in architecture, workflows, system-design, error-handling and the README, next to the text that explains them | Done |
| [error-handling.md](error-handling.md) | Failures, retries, fallbacks, diagnostics | Done |
| [security.md](security.md) | Verification, privacy, secrets | Tool server done |
| [testing.md](testing.md) | Tests, evaluation harness, results, known failures, cost | Done |
| [troubleshooting.md](troubleshooting.md) | Common problems and fixes | Done |
| [deployment.md](deployment.md) | Free-tier deployment guide (Render, Vercel, local Docker) | Done |

## Decision records

- [0001 Language and stack](decisions/0001-language-and-stack.md)
- [0002 Free-tier LLM provider](decisions/0002-llm-provider.md)
- [0003 In-memory JSON data store](decisions/0003-data-store.md)
- [0004 Safety and policy in code](decisions/0004-safety-and-policy-in-code.md)
- [0005 Verification token](decisions/0005-verification-token.md)
- [0006 Planner-executor agent](decisions/0006-planner-executor-agent.md)
- [0007 Evaluation design](decisions/0007-evaluation-design.md)
- [0008 Dashboard and deployment](decisions/0008-dashboard-and-deployment.md)

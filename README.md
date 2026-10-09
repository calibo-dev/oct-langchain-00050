# LangChain Python Template

A FastAPI application that builds agents, models and workflow stages from YAML.
The included example uses a two-agent LangChain workflow: `content_drafting_agent`
creates a draft, then `content_review_agent` produces the final response.

## Startup and request flow

1. Read and validate environment settings.
2. Load `stages.yaml` and find its active agents.
3. Load the models those agents reference and detect any configured tool names.
4. Validate references and stage input/output contracts.
5. Build shared model and agent registries.
6. Register a POST route and request schema from the workflow definition.
7. Execute stages in YAML order and pass outputs to downstream agents.

Models and agents are created once per application process. Tool runtime modules
are optional and are loaded only when an agent configures tools.

## Layout

```text
src/latest_ai_development/
├── main.py                 # Uvicorn entry point and server command
├── application.py          # FastAPI assembly and shutdown lifecycle
├── api/                    # Dynamic route, health and error handling
├── core/                   # Settings, secrets, logging and container
├── agents/                 # Configuration, factories and fallback runtime
├── models/                 # Provider model builders and registry
├── stages/                 # Workflow schemas and dependency validation
├── workflow/               # Execution, prompts, response parsing and traces
└── config/
    ├── agents.yaml
    ├── models.yaml
    └── stages.yaml
```

The base template intentionally does not include a tool runtime. Code generation
adds the required tool modules, configuration and dependencies only when the
design assigns tools to an agent.

## Configuration

`models.yaml` stores one primary model and ordered fallback models per provider.
Providers are OpenAI, AnthropicAI, GeminiAI, BedrockAI and Ollama. `agents.yaml`
references models in primary-then-fallback order and declares prompts, tools,
inputs and outputs. Fallbacks run after invocation exceptions, not output-parsing
failures.

`stages.yaml` owns the workflow, endpoint name and initial input names:

```yaml
workflow:
  name: langchain_python_template
  execution: sequential
  inputs:
    - topic
  stages:
    # Keep the configured stages here.
```

All public inputs are required, nonblank strings. Declare inputs explicitly;
`inputs: []` is allowed when no external inputs are needed. Stage inputs must
come from the payload or dependency outputs and match the configured agents.
Stages execute in YAML order. A stage with `execution: parallel` runs its agents
concurrently against the same input snapshot; workflow stages remain sequential.

Agents return JSON containing their declared output fields. Intermediate values
can be structured JSON. Terminal-stage outputs form the API response, with their
values converted to strings to preserve the v1 response contract.

## Environment and running

Start with `.env.example`. Every field in `core/settings.py` must be supplied;
unused provider secret names and the unused cloud-backend field may be empty.
`OLLAMA_BASE_URL` may be omitted unless an active model uses Ollama.
`DEBUG`, `LOG_LEVEL`, `PORT` and `CONTEXT` have no code defaults. `CONTEXT` must be
nonblank; this runner does not automatically load retrieval files.

With Python 3.14:

```sh
uv sync --extra dev
uv run latest_ai_development
```

Host and port come from the environment. Docker startup and DevOps files are
unchanged. The configured endpoint replaces `/ask`:

```http
POST /langchain_python_template
Content-Type: application/json

{
  "topic": "Explain configuration-driven agent workflows."
}
```

Swagger at `/docs` shows the generated schema. Missing, blank, non-string or
unknown fields return 422; workflow failures return 502; unexpected failures
return 500. `/health` checks liveness; `/ready` checks container initialization,
not external connectivity. `API_ROOT_PATH` retains the proxy-prefix behavior.
Restart after YAML changes.

Use INFO for lifecycle logs and DEBUG for configuration details. LangSmith uses
native environment configuration: `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`,
`LANGSMITH_PROJECT` and optional `LANGSMITH_ENDPOINT`. The old custom
`TRACING_BACKEND` initializer is not included.

## Verification and migration

```sh
uv run --extra dev ruff check src
```

The OpenAI model setup needs `OPENAI_API_KEY_SECRET` and cloud authentication for
the configured secret backend.

This replaces the research/reporting classes, chain builders and separate
`workflow.yaml`. It returns JSON and does not automatically persist `report.md`.
Historical training/replay command entries were already declared without matching
functions; they are not validated server interfaces. Use `latest_ai_development`
to start the application.

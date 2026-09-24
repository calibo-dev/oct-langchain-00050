# LangChain Python Template

A FastAPI application that builds agents, models, tools and workflow stages from
YAML. The included example answers questions about Snowflake country data.

## Startup and request flow

1. Read and validate environment settings.
2. Load `stages.yaml` and find its active agents.
3. Load the models, tools and named connections those agents reference.
4. Validate references and stage input/output contracts.
5. Build shared connection, model, tool and agent registries.
6. Register a POST route and request schema from the workflow definition.
7. Execute stages in YAML order and pass outputs to downstream agents.

Models and agents are created once per application process. Snowflake connections
open lazily, are reused by name, and close at application shutdown.

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
├── connections/            # Connector-neutral loading, lifecycle and registry
├── tools/                  # Discovery, shared contracts and tool factories
│   └── snowflake/
│       ├── plugin.py       # Connector validation and construction entry point
│       ├── connections.py  # Schemas, PAT resolution and cached connections
│       └── tools.py        # Schemas, metadata discovery and SQL execution
├── workflow/               # Execution, prompts, response parsing and traces
└── config/
    ├── agents.yaml
    ├── models.yaml
    ├── stages.yaml
    ├── tools_connections.yaml
    └── tools_info.yaml
```

`config.py` loads YAML; `schema.py` defines its shape; `validator.py` checks
contracts; `factory.py` creates runtime objects; `registry.py` stores them for
lookup. Connector-specific implementations stay inside connector folders.

## Adding a connector

Add `tools/<connector>/plugin.py` exporting `plugin`, an instance of
`ConnectorPlugin` from `tools/base.py`. Its name must match the folder. It supplies
four functions: `validate_connections`, `validate_tool`, `build_manager`, and
`build_tool`. Keep connector-specific connection code in `connections.py` and
tool code in `tools.py`, following Snowflake's layout.

Add connection records to `config/tools_connections.yaml` and set their
`connector` value to the plugin name. Add tool descriptions to
`config/tools_info.yaml`; each tool selects its connector indirectly through its
globally unique `connectionName`. Tool names also remain globally unique, and
agents select them in `agents.yaml`. Add vendor dependencies separately when
required.

Discovery imports immediate installed connector folders once per process. YAML
cannot supply arbitrary import paths. Restart after adding a connector. Connection
configuration is loaded only for active tools during application startup. A
missing or invalid plugin/configuration produces a startup error.

## Configuration

`models.yaml` stores one primary model and ordered fallback models per provider.
Providers are OpenAI, AnthropicAI, GeminiAI, BedrockAI and Ollama. `agents.yaml`
references models in primary-then-fallback order and declares prompts, tools,
inputs and outputs. Fallbacks run after invocation exceptions, not output-parsing
failures.

`stages.yaml` owns the workflow, endpoint name and initial input names:

```yaml
workflow:
  name: country_data_query_workflow
  execution: sequential
  inputs:
    - user_natural_language_query
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

## Required tool execution

An agent can require evidence that a configured tool ran:

```yaml
# Require a tool response on every invocation (metadata fetching).
required_tool_when: {}
```

Or require it only when all configured input conditions match:

```yaml
# SQL execution can skip the tool when query validation is invalid.
required_tool_when:
  query_validation_status: valid
```

Omit the field for optional tool use. Missing required tool responses fail the
workflow instead of accepting invented execution results. This does not force a
model to call a tool or prove SQL/summary correctness. OpenAI strict tool schemas
validate call arguments; they do not guarantee execution.

## Snowflake

Connection properties and `connector: snowflake` live in
`tools_connections.yaml`. Tool descriptions live in `tools_info.yaml`. A tool's
`connectionName` selects a named connection; multiple tools can share it.
Populate exactly one environment variable referenced by `authentication`:

- `directPatToken`: its environment variable contains the PAT.
- `secret`: its environment variable contains a secret-manager name whose value
  is the PAT, resolved through AWS Secrets Manager or Azure Key Vault.

The tool discovers databases, schemas, tables or columns, or executes supplied
SQL with bounded result sizes. Use a Snowflake user with read-only permissions:
prompt instructions and row limits are not authorization controls. Model and tool
configuration is retained from the existing country workflow.

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
POST /country_data_query_workflow
Content-Type: application/json

{
  "user_natural_language_query": "How many countries are available?"
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
uv run --extra dev pytest -q
uv run --extra dev ruff check src tests
```

The test suite contains one placeholder test that prints `success`. It verifies
test-runner execution only. Use `pytest -q -s` to display the message.

This replaces the research/reporting classes, chain builders and separate
`workflow.yaml`. It returns JSON and does not automatically persist `report.md`.
Historical training/replay command entries were already declared without matching
functions; they are not validated server interfaces. Use `latest_ai_development`
to start the application.

# LangChain Python Template

A FastAPI application that builds agents, models, tools and workflow stages from
YAML. The included example exposes hospital, patient, and doctor Snowflake tools
through the existing two-agent LangChain workflow.

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
├── tools/
│   ├── connection.py       # YAML loading, connection resolution, .env, lifecycle
│   ├── tools_registry.py   # Resolve YAML, call factories, cache native LangChain tools
│   └── snowflake_connection.py  # One shared Snowflake factory and implementation
├── workflow/               # Execution, prompts, response parsing and traces
└── config/
    ├── agents.yaml
    ├── models.yaml
    ├── stages.yaml
    ├── connection.yml
    └── tools.yml
```

Tool metadata and connection properties have separate sources of truth. The
registry joins them by `connection_name`, calls the configured provider factory,
and stores the native LangChain tool it returns. Agents
reference the exact keys in `tools.yml`; all active agents reuse the same registry.

## Adding a connector

Add one provider module in `tools/`, exporting a factory with this contract:

```python
def create_tool(*, tool_name, tool_config, connection_manager) -> BaseTool:
    ...
```

`tool_config` contains the tool metadata plus its resolved `connector` and
`configuration` from `connection.yml`. The factory validates provider settings
and uses `connection_manager.get_or_create(connection_name, factory)` to share
connections by name. The factory returns a native LangChain `BaseTool` (for example,
`StructuredTool`) directly. There is no intermediate tool-definition model or
registry adapter. The registry retains the existing application shutdown lifecycle.
Providers build their own input schemas, descriptions, and error handling.

Add records to `connection.yml` and `tools.yml`, then assign tool names in
`agents.yaml`. Factories use `<module>:<attribute>` references, as in LangGraph.
The registry passes `tool_name`, resolved `tool_config`, and `connection_manager`
only when declared in the factory signature. Optional `factory_kwargs` supply
non-secret constructor parameters and cannot override these wiring arguments.
Tools without `connection_name` can use standalone factories. Multiple tools may
use the same factory and connection, or the same factory with different
connections. Restart after YAML changes. Add provider dependencies when needed.

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

Non-secret account, user, warehouse, optional host/database/schema, connection
options, and authentication variable names live in `connection.yml`:

```yaml
connections:
  hospital_core_connection:
    connector: {category: RDBMS, type: SNOWFLAKE}
    configuration:
      account: your_account
      user: your_user
      warehouse: your_warehouse
      database: your_database  # Optional
      schema: your_schema      # Optional
      authentication:
        directPatToken: SNOWFLAKE_HOSPITAL_CORE_PAT_TOKEN
        secret: SNOWFLAKE_HOSPITAL_CORE_PAT_SECRET_NAME
```

Tool metadata and the factory reference live in `tools.yml`:

```yaml
tools:
  snowflake_table_hospitals:
    factory: latest_ai_development.tools.snowflake_connection:create_tool
    connection_name: hospital_core_connection
    description: Query hospital profile and capacity data from Snowflake.
    purpose: Retrieve hospital names, locations, ownership, bed capacity, and facilities.
    tags: [snowflake, hospitals, read-only]
    usage_guidelines: [Discover tables and columns before writing SQL.]
    non_usage_guidelines: [Do not modify data.]
```

Populate exactly one environment variable referenced by each connection's
`authentication`:

- `directPatToken`: its environment variable contains the PAT.
- `secret`: its environment variable contains a secret-manager name whose value
  is the PAT, resolved through AWS Secrets Manager or Azure Key Vault.

Variable names are explicit YAML references, not automatically derived prefixes.
The connection manager reads them from the project `.env` with process environment
values taking precedence. Account/user/warehouse values are required in YAML;
no `SNOWFLAKE_*_ACCOUNT`, `*_USER`, or `*_WAREHOUSE` environment variables are read.

| Tool | Connection | Direct PAT variable |
| --- | --- | --- |
| `snowflake_table_hospitals` | `hospital_core_connection` | `SNOWFLAKE_HOSPITAL_CORE_PAT_TOKEN` |
| `snowflake_table_patients` | `hospital_core_connection` | Same core PAT |
| `snowflake_table_doctors` | `hospital_staff_connection` | `SNOWFLAKE_HOSPITAL_STAFF_PAT_TOKEN` |

All three use one Python implementation for authentication, metadata discovery,
read-only SQL execution, and formatting. Connection objects are reused by name;
actual Snowflake clients open on first use. Shutdown closes each shared connection
once. Missing references, mixed inline/named settings, duplicate YAML keys, and
invalid active provider settings fail during startup.

Tool purposes and guidelines guide the model; they do not restrict access to
specific tables. Use read-only Snowflake users with the required database grants.

## Environment and running

Start with `.env.example`. Every field in `core/settings.py` must be supplied;
unused provider secret names and the unused cloud-backend field may be empty.
`OLLAMA_BASE_URL` may be omitted unless an active model uses Ollama.
`DEBUG`, `LOG_LEVEL`, `PORT` and `CONTEXT` have no code defaults. `CONTEXT` must be
nonblank; this runner does not automatically load retrieval files.

With Python 3.14:

```sh
uv sync --extra dev --extra snowflake
uv run --extra snowflake latest_ai_development
```

Host and port come from the environment. Docker startup and DevOps files are
unchanged. The configured endpoint replaces `/ask`:

```http
POST /langchain_python_template
Content-Type: application/json

{
  "topic": "Discover hospital, patient, and doctor tables using all three Snowflake tools."
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
uv run --extra dev --extra snowflake pytest -q
uv run --extra dev ruff check src tests
```

Before running the real application, replace the example account/user/warehouse
values in `connection.yml` and populate the two PAT sources in `.env`. The existing
OpenAI model setup also needs `OPENAI_API_KEY_SECRET` and cloud authentication for
the configured secret backend; this tool change keeps that behavior.

`tests/test_configured_tools.py` verifies the three-tool/two-connection mapping,
credential selection, connection reuse/cleanup, SQL rejection, YAML validation,
and the actual FastAPI → LangChain agents → metadata/SQL tools → response flow.
Only the external LLM and Snowflake client are simulated. These tests do not prove
live Snowflake authentication or live model tool selection.

This replaces the research/reporting classes, chain builders and separate
`workflow.yaml`. It returns JSON and does not automatically persist `report.md`.
Historical training/replay command entries were already declared without matching
functions; they are not validated server interfaces. Use `latest_ai_development`
to start the application.

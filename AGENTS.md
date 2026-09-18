# Workflow and Agent Documentation

## Overview

This template implements a **FastAPI-based LangChain workflow** for automated topic research and report generation.

### Purpose
Execute a structured workflow that researches a topic and produces a markdown report.

### Workflow Pattern
Sequential workflow with explicit stage handoff.

### Core Stages

- **Research Stage**
  - gathers topic information
  - optionally invokes tools or retrieval
  - produces structured research notes

- **Reporting Stage**
  - converts research notes into a formatted markdown report

### Execution Model

A workflow controller orchestrates stage execution and passes structured outputs between stages.

### Output

Final report written to:

`report.md`

## Architecture

The system uses **FastAPI** and **LangChain Runnable pipelines** to implement deterministic workflow execution.

### High-Level Flow

Client → FastAPI → Workflow Controller → Research Stage → Reporting Stage → Markdown Report

### Framework

- FastAPI
- LangChain

### LLM Provider Selection

Controlled by each stage's `model.primary` and optional `model.fallback`
sections in `src/latest_ai_development/config/stages.yaml`.

Supported provider values:

- `OpenAI`
- `AnthropicAI`
- `GeminiAI`
- `BEDROCKAI`
- `MicrosoftFoundryAI`
- `Ollama`

### LLM Initialization

LLM configuration is centralized through an **LLM factory**.

Location:

`src/latest_ai_development/llm/llm_factory.py`

The factory reads stage-owned model configuration and returns the correct chat model.
Builders wrap fallback models with LangChain `with_fallbacks` when a fallback
section is present.

### Chain Construction

LLM pipelines are constructed using a **Chain Builder pattern**.

Location:

`src/latest_ai_development/chains/`

Examples:

- `research_chain_builder.py`
- `reporting_chain_builder.py`

Chain builders assemble LangChain Runnable pipelines combining:

- prompts
- models
- tools
- output parsers

Stages call these builders rather than constructing pipelines directly.

## Workflow Stages

The workflow contains two sequential stages.

### Research Stage

Purpose  
Collect relevant information for the requested topic.

Inputs

- topic
- runtime context
- optional knowledge sources

Execution Pipeline

Prompt → LLM(bind_tools) → Tool Execution → LLM → Output Parser

Output

Structured research notes including:

- topic overview
- key findings
- supporting details
- assumptions
- suggested report structure


### Reporting Stage

Purpose  
Convert research notes into a structured markdown report.

Inputs

- research notes

Execution Pipeline

Prompt → LLM → Output Parser

Output

Final markdown report written to `report.md`.

## Workflow Execution

The workflow executes stages sequentially.

### Execution Order

1. Research Stage  
2. Reporting Stage

### Workflow Controller

`LatestAiDevelopmentWorkflow`

Location

`src/latest_ai_development/workflow.py`

### Stage Interface

Each stage implements:

run(inputs: dict) → dict

The research stage output becomes the input for the reporting stage.

## Configuration Files

Runtime behavior is configured using YAML files.

### stages.yaml

Location  
`src/latest_ai_development/config/stages.yaml`

Purpose  
Defines stage prompts and execution instructions.

---

### workflow.yaml

Location  
`src/latest_ai_development/config/workflow.yaml`

Purpose  
Defines stage order and workflow configuration.

---

### Stage Model Configuration

Location  
`src/latest_ai_development/config/stages.yaml`

Purpose  
Defines each stage's mandatory primary model and optional fallback model:

- `model.primary.provider`
- `model.primary.modelId`
- `model.primary.generationDefaults`
- `model.fallback.provider`
- `model.fallback.modelId`
- `model.fallback.generationDefaults`

The runtime does not use a separate model defaults YAML file.

---

### settings.py

Location  
`src/latest_ai_development/config/settings.py`

Purpose  
Loads runtime configuration from environment variables.

## Usage

### Running the Workflow

The workflow can be executed through multiple interfaces.

### Direct Execution

```python
from latest_ai_development.workflow import LatestAiDevelopmentWorkflow
from datetime import datetime

inputs = {
    "topic": "Your Topic Here",
    "current_year": int(datetime.now().year),
    "save_output": True
}

LatestAiDevelopmentWorkflow().kickoff(inputs=inputs)
```
#### 2. FastAPI Endpoint
```bash
POST /ask
{
  "topic": "Your Topic Here"
}
```
#### 3. Command Line
```bash
# Run the workflow
latest_ai_development

# Train-style repeated execution
train <n_iterations> <filename>

# Replay from payload file or topic
replay <task_id>

# Test the workflow
test <n_iterations> <eval_llm>

# Run with trigger payload
run_with_trigger '<json_payload>'
```

## Environment Variables

The system uses environment variables to resolve runtime configuration.

- **`OPENAI_API_KEY_SECRET`**
  - **Purpose**: Secret name used to resolve the OpenAI API key from the configured secret manager

- **`ANTHROPICAI_API_KEY_SECRET`**
  - **Purpose**: Secret name used to resolve the Anthropic API key from the configured secret manager

- **`GEMINIAI_API_KEY_SECRET`**
  - **Purpose**: Secret name used to resolve the Gemini API key from the configured secret manager

- **`BEDROCKAI_API_KEY_SECRET`**
  - **Purpose**: Secret name used to resolve the AWS Bedrock API key from the configured secret manager

- **`MICROSOFTFOUNDRYAI_API_KEY_SECRET`**
  - **Purpose**: Secret name used to resolve the Microsoft Foundry AI API key from the configured secret manager

- **`MICROSOFTFOUNDRYAI_ENDPOINT`**
  - **Purpose**: Specifies the MICROSOFT FOUNDRY AI provider base endpoint

- **`CLOUD_PROVIDER`**
  - **Purpose**: Selects the secret backend
  - **Supported Values**:
    - `AWS`
    - `AZURE`

- **`AZURE_KEY_VAULT_URL`**
  - **Purpose**: Specifies the Azure Key Vault URL
  - **Required When**: `CLOUD_PROVIDER=AZURE`

- **`TRACING_BACKEND`**
  - **Purpose**: Selects the tracing backend
  - **Supported Values**:
    - `LANGSMITH`
    - `NONE`
  - **Default**: `NONE`

- **`LOG_LEVEL`**
  - **Purpose**: Controls application log verbosity for workflow, stage, and API logs
  - **Default**: `INFO`

- **`LANGSMITH_ENDPOINT`**
  - **Purpose**: Optional LangSmith API endpoint

- **`LANGSMITH_PROJECT`**
  - **Purpose**: LangSmith project name for trace grouping

- **`LANGSMITH_API_KEY_SECRET`**
  - **Purpose**: Secret name used to resolve the LangSmith API key through the configured secret manager

- **`OLLAMA_BASE_URL`**
  - **Purpose**: Specifies the base URL for the Ollama service

- **`PORT`**
  - **Purpose**: Specifies the FastAPI server port
  - **Default**: `8080`

- **`API_HOST`**
  - **Purpose**: Specifies the FastAPI server host
  - **Default**: `0.0.0.0`

- **`AWS_REGION`**
  - **Purpose**: Specifies the AWS region for secret resolution
  - **Default**: `us-east-1`

- **`CONTEXT`**
  - **Purpose**: Specifies the path for context, knowledge, or input files used by the workflow

- **`REPORT_OUTPUT_FILE`**
  - **Purpose**: Specifies the output filename for the final markdown report
  - **Default**: `report.md`

## Integration Features

The system includes integration points for API execution, secret resolution, and workflow extensibility.

- **FastAPI Integration**:
  - **Purpose**: Exposes the workflow through HTTP endpoints
  - **Endpoints**:
    - `GET /health`
    - `POST /ask`
  - **Root Path**:
    - `/testing`

- **Secret Manager Integration**:
  - **Purpose**: Resolves provider credentials securely at runtime
  - **Capabilities**:
    - retrieves secrets by name
    - supports secret-based API key resolution
    - selects AWS Secrets Manager or Azure Key Vault through `CLOUD_PROVIDER`
    - uses `AWS_REGION` for AWS
    - uses `AZURE_KEY_VAULT_URL` and `DefaultAzureCredential` for Azure

- **Tracing Integration**:
  - **Purpose**: Enables optional LangSmith tracing for LangChain workflows
  - **Capabilities**:
    - enables LangSmith when `TRACING_BACKEND=LANGSMITH`
    - resolves the LangSmith API key from `LANGSMITH_API_KEY_SECRET`
    - disables tracing when `TRACING_BACKEND=NONE` or tracing is unset

- **Context and Retrieval Integration**:
  - **Purpose**: Supports external context or knowledge inputs for research
  - **Capabilities**:
    - loads configured context inputs
    - supports retrieval-style enrichment where enabled
    - passes enriched context into workflow stages

- **Tool Integration**:
  - **Purpose**: Extend workflow stages with LangChain-compatible tools to access external capabilities such as search, APIs, or data processing.

  - **Capabilities**:
    - implements tools using the LangChain `@tool` decorator
    - allows tools to be attached to LLM pipelines using `bind_tools()`
    - enables the LLM to dynamically decide when a tool should be invoked
    - supports modular tool implementations that can be reused across stages
    - allows tools to be attached to the research stage or future stages without modifying the workflow controller

  - **Execution Model**:
    Tools are attached to the LLM during pipeline construction.

    Example execution pattern:

    Prompt → LLM(bind_tools) → Tool Execution → LLM → OutputParser

    In this model:
    - the LLM determines when a tool should be called
    - LangChain executes the tool
    - the tool result is returned to the LLM for final synthesis

- **Example Tool Location**:
  - `src/latest_ai_development/tools/custom_tool.py`

- **Example Tool Implementation**:

```python
from langchain.tools import tool

@tool
def search_tool(query: str) -> str:
    """Search external information sources."""
    return "Search results..."
```

## Output

The workflow produces a final markdown report as its primary output.

- **Output File**:
  - `report.md`

- **Output Type**:
  - Markdown document

- **Generated By**:
  - The reporting stage

- **Typical Content**:
  - topic summary
  - key findings
  - supporting analysis
  - insights and recommendations
  - clean markdown formatting for downstream use

- **Behavior**:
  - The final report is generated after successful completion of all workflow stages
  - Output persistence is controlled by workflow configuration and runtime settings
  - The output path can be overridden through configuration when needed

## Deployment

The project includes deployment and delivery assets for multiple environments.

- **Containerization**: Docker support with `Dockerfile` and `.dockerignore`
- **Kubernetes Deployment**: Helm chart support in `helm_chart/`
- **CI/CD Integration**: Jenkins pipeline files for build and deployment workflows


## Dependencies

The workflow relies on a set of core libraries for model integration, API serving, configuration, and runtime support.

- **`langchain`**
  - **Purpose**:
    - provides the core LangChain abstractions used for workflow composition
  
- **langchain-core**
  - Provides runnable pipelines and core abstractions

- **`langchain-openai`**
  - **Purpose**:
    - provides OpenAI model integration for LangChain

- **`langchain-aws`**
  - **Purpose**:
    - provides AWS Bedrock model integration for LangChain

- **`langchain-community`**
  - **Purpose**:
    - provides community-supported integrations and utilities

- **`langchain-ollama`**
  - **Purpose**:
    - provides Ollama model integration for LangChain

- **`fastapi`**
  - **Purpose**:
    - exposes the workflow through HTTP endpoints

- **`uvicorn`**
  - **Purpose**:
    - runs the FastAPI application as an ASGI server

- **`boto3`**
  - **Purpose**:
    - supports AWS service integration, including Secrets Manager access

- **`azure-identity`**
  - **Purpose**:
    - supports Azure authentication through `DefaultAzureCredential`

- **`azure-keyvault-secrets`**
  - **Purpose**:
    - supports Azure Key Vault secret retrieval

- **`pydantic`**
  - **Purpose**:
    - provides data validation and schema modeling

- **`pydantic-settings`**
  - **Purpose**:
    - supports environment-based configuration management

- **`PyYAML`**
  - **Purpose**:
    - loads YAML-based configuration files

## Extending the System

The template is designed so new capabilities can be added with minimal changes.

### Adding a New Stage

Create a new processing step in the workflow.

Typical steps:

1. Create a stage in `stages/`
2. Define the LLM pipeline in `chains/`
3. Update the stage order in `workflow.yaml`

Examples of new stages:

- validation
- enrichment
- summarization
- review

---

### Adding a Tool

Tools allow the workflow to call external systems such as APIs or search services.

Typical steps:

1. Implement a tool in `tools/` using the `@tool` decorator
2. Register the tool in `tool_registry.py`
3. Attach the tool to a chain using `bind_tools()`

---

### Adding Retrieval or Context

You can improve research results by adding external knowledge sources.

Typical steps:

1. Add or configure a retrieval source
2. Load the context during the research stage
3. Inject the retrieved information into the pipeline

---

### Using Tool-Enabled Agents (Optional)

If a stage requires dynamic decision-making, it can be replaced with a tool-enabled agent.

Typical steps:

1. Attach tools using `bind_tools()`
2. Allow the model to choose tools dynamically
3. Ensure outputs remain compatible with downstream stages

---

### Extension Guidelines

When extending the system:

- keep stages focused on a single responsibility
- keep tools modular and reusable
- use structured inputs and outputs between stages
- avoid tightly coupling stages together
  
## Restrictions and Guidelines

### Environment Variables

- **`PORT`**: Must be read from the environment variable. Do not hardcode port values.
- **`CONTEXT`**: Context path is mandatory for running the workflow. It must be set as an environment variable.

### Dockerfile

- The Dockerfile start command must not be modified.
- Any Dockerfile updates must remain compatible with the current startup process.

### Protected Files

The following files and directories are protected and should not be modified:

- `Jenkinsfile`
- `Jenkinsfile.ci`
- `Jenkinsfile.deploy`
- `helm_chart/`

These assets are managed by the DevOps team, and changes may affect the CI/CD pipeline or deployment process.

## Notes

- The workflow uses a deterministic sequential process
- All stages share the same LLM configuration
- Knowledge sources can enhance research quality
- Training, testing, and replay workflows are supported
- Research stages may invoke tools or retrieval when required

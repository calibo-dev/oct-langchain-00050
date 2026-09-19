"""Keep unit checks offline even when a developer's .env enables tracing."""

import os

os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["AWS_EC2_METADATA_DISABLED"] = "true"

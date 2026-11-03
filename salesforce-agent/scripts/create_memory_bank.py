# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Idempotently provision the Vertex AI Memory Bank for the Salesforce agent.

Reuses an existing Memory Bank (an Agent Engine resource) that has the configured
display name, or creates one with the default configuration (generation model
defaults to gemini-3.5-flash; similarity search to text-embedding-005). Prints the
MEMORY_BANK_ID to put in .env / deploy env vars.

Run once, out of band:
    GOOGLE_CLOUD_PROJECT=your-gcp-project-id \
        uv run python scripts/create_memory_bank.py

Uses ADC. Memory Bank uses a regional endpoint, so the location defaults to
"us-central1"; the global endpoint's memories subresource returns 404. Override
with MEMORY_BANK_LOCATION for a different region.
"""

import os

import vertexai

DISPLAY_NAME = os.environ.get("MEMORY_BANK_DISPLAY_NAME", "salesforce-agent-memory")
PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")
LOCATION = os.environ.get("MEMORY_BANK_LOCATION", "us-central1")


def main() -> None:
    if not PROJECT:
        raise SystemExit("Set GOOGLE_CLOUD_PROJECT.")

    client = vertexai.Client(project=PROJECT, location=LOCATION)

    # Reuse an existing Memory Bank with this display name if present (idempotent).
    # TODO(challenge): Idempotent: reuse the agent engine whose display_name matches, else client.agent_engines.create(...); print the resource name.
    for engine in client.agent_engines.list():
        if engine.api_resource and engine.api_resource.display_name == DISPLAY_NAME:
            resource_name = engine.api_resource.name
            print(f"Found existing Memory Bank '{DISPLAY_NAME}': {resource_name}")
            print(f"MEMORY_BANK_ID={resource_name.split('/')[-1]}")
            return

    print(f"Creating Memory Bank '{DISPLAY_NAME}'...")
    engine = client.agent_engines.create(config={"display_name": DISPLAY_NAME})
    resource_name = engine.api_resource.name
    print(f"Created Memory Bank '{DISPLAY_NAME}': {resource_name}")
    print(f"MEMORY_BANK_ID={resource_name.split('/')[-1]}")


if __name__ == "__main__":
    main()

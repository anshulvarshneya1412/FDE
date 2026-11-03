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

"""Bug Database specialist agent (ADK + BigQuery semantic search over A2A)."""

import os
from pathlib import Path

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

from app.tools import find_similar_bugs

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

MODEL = os.environ["MODEL"]

root_agent = Agent(
    # Keep in sync with create_params.root_agent_name in agents-cli-manifest.yaml:
    # telemetry reports this name as gen_ai.agent.name, and agents-cli reports the
    # manifest's value.
    name="bq_agent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    description=(
        "Semantic search specialist over the internal BigQuery bug database "
        "(`code_assist_bugs.known_bugs`) that finds similar past engineering "
        "incidents and their concrete resolutions."
    ),
    instruction=(
        "You are the internal Bug Database Specialist Agent. Your sole job is to "
        "answer: 'Have we seen this software problem before, and how was it fixed?'\n\n"
        "Rules:\n"
        "1. Always call `find_similar_bugs` with the reported problem description "
        "(exception, stack-trace terms, language/framework, and symptoms).\n"
        "2. Ground your response strictly in what `find_similar_bugs` returns. "
        "Never invent, guess, or fabricate incidents, bug IDs, resolutions, or details.\n"
        "3. For every relevant matching incident returned by `find_similar_bugs`, "
        "summarize the problem and its concrete resolution, and explicitly cite its "
        "`bug_id` (e.g. `BUG-1001`). Be concise and practical.\n"
        "4. If `find_similar_bugs` returns no matches, returns a temporary "
        "unavailability notice, or none of the returned incidents are relevant to "
        "the reported problem, state clearly that no relevant matching incidents "
        "were found in the bug database without fabricating any fix."
    ),
    tools=[find_similar_bugs],
)

app = App(
    root_agent=root_agent,
    name="app",
)

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

"""Offline config and A2A agent card tests for bq-agent."""

import pytest
from a2a.server.request_handlers.response_helpers import agent_card_to_dict

from app.agent import MODEL, app, root_agent
from app.app_utils.a2a import build_agent_card
from app.tools import find_similar_bugs


def test_agent_identity_and_model() -> None:
    """The agent and app are named properly and use the configured model."""
    assert root_agent.name == "bq_agent"
    assert app.name == "app"
    assert MODEL == "gemini-3.5-flash"
    assert root_agent.model.model == MODEL


def test_single_tool_is_wired() -> None:
    """The agent exposes only the find_similar_bugs tool."""
    assert root_agent.tools == [find_similar_bugs]


@pytest.mark.asyncio
async def test_agent_card_exposes_single_skill_and_reachable_url() -> None:
    """The A2A card exposes a single skill with an example and reachable URL."""
    card = await build_agent_card(
        root_agent,
        rpc_url="http://203.0.113.10:8080/a2a/app",
    )
    assert len(card.skills) == 1
    skill = card.skills[0]
    assert skill.id == "find_similar_bugs"
    assert skill.examples == [
        "FastAPI returns a 500 on startup after a dependency bump."
    ]

    card_dict = agent_card_to_dict(card)
    assert card_dict.get("url") == "http://203.0.113.10:8080/a2a/app"
    assert card_dict.get("preferredTransport") == "JSONRPC"
    versions = sorted(i.protocol_version for i in card.supported_interfaces)
    assert versions == ["0.3", "1.0"]

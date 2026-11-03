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

"""Unit tests for the find_similar_bugs BigQuery semantic search tool."""

from types import SimpleNamespace
from unittest import mock

from app import tools as tools_module
from app.tools import find_similar_bugs


def test_find_similar_bugs_formats_matches() -> None:
    """Returns bug_id, title, description, resolution, and cosine distance."""
    fake_vector = [0.1] * 768
    fake_rows = [
        SimpleNamespace(
            bug_id="BUG-1001",
            title="FastAPI service returns 500 on startup after dependency bump",
            description="Service fails on startup after upgrading pydantic.",
            resolution="Migrate models to Pydantic v2 and pin pydantic>=2.5.",
            distance=0.1359,
        ),
    ]

    with (
        mock.patch.object(
            tools_module, "_embed_query", return_value=fake_vector
        ) as mock_embed,
        mock.patch.object(
            tools_module, "_search_bigquery", return_value=fake_rows
        ) as mock_bq,
    ):
        output = find_similar_bugs(
            "FastAPI returns a 500 on startup after a dependency bump."
        )

    mock_embed.assert_called_once()
    mock_bq.assert_called_once()
    assert "BUG-1001" in output
    assert "FastAPI service returns 500 on startup after dependency bump" in output
    assert "Service fails on startup after upgrading pydantic." in output
    assert "Migrate models to Pydantic v2 and pin pydantic>=2.5." in output
    assert "0.1359" in output


def test_find_similar_bugs_empty_results() -> None:
    """Returns a clear 'no similar bugs found' message when BigQuery yields no rows."""
    with (
        mock.patch.object(tools_module, "_embed_query", return_value=[0.0] * 768),
        mock.patch.object(tools_module, "_search_bigquery", return_value=[]),
    ):
        output = find_similar_bugs("some problem")

    assert "no similar bugs found" in output.lower()


def test_find_similar_bugs_blank_query() -> None:
    """Blank query returns 'no similar bugs found' without calling external services."""
    output = find_similar_bugs("   ")
    assert "no similar bugs found" in output.lower()


def test_find_similar_bugs_embedding_unavailable_graceful_degradation() -> None:
    """Does not raise when the embedding model call fails."""
    with mock.patch.object(
        tools_module,
        "_embed_query",
        side_effect=RuntimeError("Vertex AI quota exceeded"),
    ):
        output = find_similar_bugs("FastAPI 500 error")

    assert "temporarily unavailable" in output.lower()
    assert "Vertex AI quota exceeded" in output


def test_find_similar_bugs_bigquery_unavailable_graceful_degradation() -> None:
    """Does not raise when BigQuery is temporarily unavailable."""
    with (
        mock.patch.object(tools_module, "_embed_query", return_value=[0.0] * 768),
        mock.patch.object(
            tools_module,
            "_search_bigquery",
            side_effect=RuntimeError("BigQuery service timeout"),
        ),
    ):
        output = find_similar_bugs("FastAPI 500 error")

    assert "temporarily unavailable" in output.lower()
    assert "BigQuery service timeout" in output


def test_embed_and_bigquery_clients_use_expected_parameters() -> None:
    """Verifies text-embedding-004 in us-central1 and VECTOR_SEARCH COSINE top_k=3."""
    fake_embedding_resp = SimpleNamespace(
        embeddings=[SimpleNamespace(values=[0.25] * 768)]
    )
    fake_genai_client = mock.MagicMock()
    fake_genai_client.models.embed_content.return_value = fake_embedding_resp

    fake_bq_client = mock.MagicMock()
    fake_bq_client.query.return_value.result.return_value = []

    with (
        mock.patch.object(
            tools_module.genai, "Client", return_value=fake_genai_client
        ) as genai_cls,
        mock.patch.object(tools_module.bigquery, "Client", return_value=fake_bq_client),
    ):
        output = find_similar_bugs("NullPointerException in payment worker")

    assert "no similar bugs found" in output.lower()
    genai_cls.assert_called_once_with(
        vertexai=True,
        project="qwiklabs-gcp-01-cb06168cab66",
        location="us-central1",
    )
    fake_genai_client.models.embed_content.assert_called_once_with(
        model="text-embedding-004",
        contents="NullPointerException in payment worker",
    )
    sql_arg = fake_bq_client.query.call_args.args[0]
    assert "VECTOR_SEARCH" in sql_arg
    assert "description_embedding" in sql_arg
    assert "COSINE" in sql_arg
    assert "top_k => 3" in sql_arg
    assert "ORDER BY distance ASC" in sql_arg

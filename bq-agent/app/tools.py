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

"""BigQuery semantic search tool for internal engineering incidents."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any

from google import genai
from google.cloud import bigquery

logger = logging.getLogger(__name__)

DEFAULT_BQ_DATASET = "code_assist_bugs"
DEFAULT_BQ_TABLE = "known_bugs"
DEFAULT_EMBEDDING_MODEL = "text-embedding-004"
DEFAULT_EMBEDDING_LOCATION = "us-central1"
TOP_K = 3


def _field(row: Any, name: str) -> Any:
    """Extracts a column value from a BigQuery Row, dict, or object."""
    if isinstance(row, Mapping):
        return row.get(name)
    try:
        return row[name]
    except Exception:
        return getattr(row, name, None)


def _embed_query(
    query: str,
    *,
    project: str | None,
    location: str,
    model: str,
) -> list[float]:
    """Embeds the query string using Vertex AI text embeddings."""
    client = genai.Client(
        vertexai=True,
        project=project,
        location=location,
    )
    response = client.models.embed_content(
        model=model,
        contents=query,
    )
    if not response.embeddings or not response.embeddings[0].values:
        raise ValueError("Embedding model returned an empty vector.")
    return list(response.embeddings[0].values)


def _search_bigquery(
    query_vector: list[float],
    *,
    project: str | None,
    dataset: str,
    table: str,
    top_k: int = TOP_K,
) -> list[Any]:
    """Runs BigQuery VECTOR_SEARCH with cosine distance over known_bugs."""
    table_ref = f"{project}.{dataset}.{table}" if project else f"{dataset}.{table}"
    sql = f"""
SELECT
  base.bug_id AS bug_id,
  base.title AS title,
  base.description AS description,
  base.resolution AS resolution,
  distance
FROM VECTOR_SEARCH(
  TABLE `{table_ref}`,
  'description_embedding',
  (SELECT @query_embedding AS embedding),
  distance_type => 'COSINE',
  top_k => {int(top_k)}
)
ORDER BY distance ASC
"""
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter(
                "query_embedding",
                "FLOAT64",
                query_vector,
            ),
        ]
    )
    client = bigquery.Client(project=project)
    query_job = client.query(sql, job_config=job_config)
    return list(query_job.result())


def find_similar_bugs(query: str) -> str:
    """Searches the internal BigQuery bug database for similar past incidents.

    Embeds the free-text problem description with ``text-embedding-004`` and
    runs a BigQuery ``VECTOR_SEARCH`` (cosine distance, top 3) over
    ``code_assist_bugs.known_bugs.description_embedding``.

    Args:
        query: A free-text software problem description (exception, key
            stack-trace terms, language/framework, symptom).

    Returns:
        A formatted summary of the top matching incidents (including ``bug_id``,
        ``title``, ``description``, ``resolution``, and cosine ``distance``),
        ``"No similar bugs found."`` when no matches are returned, or a graceful
        degradation message if the embedding service or BigQuery is unavailable.
    """
    if not query or not query.strip():
        return "No similar bugs found."

    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    dataset = os.environ.get("BQ_DATASET", DEFAULT_BQ_DATASET)
    table = os.environ.get("BQ_TABLE", DEFAULT_BQ_TABLE)
    embedding_model = os.environ.get("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
    embedding_location = os.environ.get(
        "EMBEDDING_LOCATION", DEFAULT_EMBEDDING_LOCATION
    )

    try:
        query_vector = _embed_query(
            query.strip(),
            project=project,
            location=embedding_location,
            model=embedding_model,
        )
    except Exception as exc:
        logger.warning("Failed to embed query for bug search: %s", exc)
        return (
            "Bug database search is temporarily unavailable: "
            f"failed to generate query embedding ({exc})."
        )

    try:
        rows = _search_bigquery(
            query_vector,
            project=project,
            dataset=dataset,
            table=table,
            top_k=TOP_K,
        )
    except Exception as exc:
        logger.warning("BigQuery vector search failed: %s", exc)
        return (
            "Bug database search is temporarily unavailable: "
            f"BigQuery query failed ({exc})."
        )

    if not rows:
        return "No similar bugs found."

    formatted_matches: list[str] = []
    for row in rows:
        bug_id = _field(row, "bug_id")
        title = _field(row, "title")
        description = _field(row, "description")
        resolution = _field(row, "resolution")
        distance = _field(row, "distance")
        distance_str = (
            f"{float(distance):.4f}"
            if isinstance(distance, (int, float))
            else str(distance)
        )
        formatted_matches.append(
            f"- bug_id: {bug_id}\n"
            f"  title: {title}\n"
            f"  cosine_distance: {distance_str}\n"
            f"  description: {description}\n"
            f"  resolution: {resolution}"
        )

    return "Similar bugs found:\n\n" + "\n\n".join(formatted_matches)

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

"""Test bootstrap: provide required env before ``app.agent`` is imported."""

import os

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "qwiklabs-gcp-01-cb06168cab66")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")
os.environ.setdefault("MODEL", "gemini-3.5-flash")
os.environ.setdefault("BQ_DATASET", "code_assist_bugs")
os.environ.setdefault("BQ_TABLE", "known_bugs")
os.environ.setdefault("EMBEDDING_MODEL", "text-embedding-004")
os.environ.setdefault("EMBEDDING_LOCATION", "us-central1")

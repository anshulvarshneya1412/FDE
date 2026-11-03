# Step-by-Step Lab Manual: Building & Deploying the Multi-Agent Code Assistant (FDE)

This step-by-step lab manual walks through the complete engineering workflow—from environment initialization and specialist agent implementation (**Tasks 1–7**) to end-to-end orchestration on **Vertex AI Agent Runtime** and publication to **Gemini Enterprise**.

---

## Lab Overview & Task Map

| Task | Component | Key Technologies | Target Runtime |
| :--- | :--- | :--- | :--- |
| **Task 1** | Environment & Datastore Setup | `google-agents-cli`, Discovery Engine API (`Vertex AI Search`), GCS | Local / GCP Global |
| **Task 2** | GitHub Specialist (`github-agent`) | ADK `Agent`, `McpToolset`, `StreamableHTTPConnectionParams`, GitHub PAT | Vertex AI Agent Runtime |
| **Task 3** | Stack Exchange Specialist (`stackexchange-agent`) | LangGraph `StateGraph`, `a2a-sdk` 1.x (`0.3` + `1.0` compat), Cloud Build | Cloud Run (or GKE) |
| **Task 4** | Bug DB Specialist (`bq-agent`) | ADK `Agent`, `text-embedding-004`, BigQuery `VECTOR_SEARCH` (`COSINE`) | GKE Autopilot |
| **Task 5** | Root Orchestrator (`code-assistant`) | ADK 2.0 `Workflow`, `JoinNode`, `RemoteA2aAgent`, `GCPSkillRegistry`, `SkillToolset` | Vertex AI Agent Runtime |
| **Task 6** | Publish to Gemini Enterprise | IAM Service Agent bindings, `agents-cli publish gemini-enterprise` | Gemini Enterprise |
| **Task 7** | Salesforce Specialist & Memory Bank (`salesforce-agent`) | Salesforce 2LO OAuth + SOSL `ContentVersion`, `VertexAiMemoryBankService`, `PreloadMemoryTool`, A2A `user_id` forwarding | Cloud Run + Vertex AI Memory Bank |

---

## Task 1: Environment Setup & Engineering Handbook Datastore Provisioning

### Step 1.1: Configure GCP Environment Variables & Authenticate

```bash
export PROJECT_ID=$(gcloud config get-value project)
export REGION=us-central1
export PATH="${HOME}/.local/bin:${PATH}"

gcloud config set project ${PROJECT_ID}
gcloud auth login
gcloud auth application-default login
```

### Step 1.2: Install `google-agents-cli` & Copy Starter Assets

```bash
uv tool install google-agents-cli
agents-cli info

# Copy agent templates from the lab bucket if not already in ~/agents
cd ~
gcloud storage cp -r gs://${PROJECT_ID}-bucket/agents .
agents-cli setup --agent all
```

### Step 1.3: Create & Populate the Vertex AI Search Datastore (`code-manuals-datastore`)

The `manual_search_agent` inside `code-assistant` searches the internal engineering handbook via Vertex AI Search (`Discovery Engine API`). Create the datastore and import the documents from Cloud Storage:

```bash
# 1. Create the 'code-manuals-datastore' unstructured search datastore
curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  -H "X-Goog-User-Project: ${PROJECT_ID}" \
  "https://discoveryengine.googleapis.com/v1/projects/${PROJECT_ID}/locations/global/collections/default_collection/dataStores?dataStoreId=code-manuals-datastore" \
  -d '{
    "displayName": "Code manuals",
    "industryVertical": "GENERIC",
    "solutionTypes": ["SOLUTION_TYPE_SEARCH"],
    "contentConfig": "CONTENT_REQUIRED"
  }'

# 2. Import handbook documents from gs://${PROJECT_ID}-bucket/code_manuals/*
curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  "https://discoveryengine.googleapis.com/v1/projects/${PROJECT_ID}/locations/global/collections/default_collection/dataStores/code-manuals-datastore/branches/0/documents:import" \
  -d '{
    "reconciliationMode": "INCREMENTAL",
    "gcsSource": {
      "inputUris": ["gs://'${PROJECT_ID}'-bucket/code_manuals/*"],
      "dataSchema": "content"
    }
  }'
```

---

## Task 2: Implement & Deploy the GitHub Specialist (`github-agent`)

The `github-agent` connects to the hosted **GitHub Copilot MCP Server** (`https://api.githubcopilot.com/mcp/`) using an ADK `McpToolset` authenticated with a GitHub Personal Access Token (PAT) and restricted to read-only repository/issue tools.

### Step 2.1: Implement `github_mcp_toolset` in `github-agent/app/agent.py`

Edit `~/agents/github-agent/app/agent.py` to configure `McpToolset` with `StreamableHTTPConnectionParams`, passing the Bearer token, read-only headers, and `tool_filter`:

```python
GITHUB_TOOL_FILTER = ["search_repositories", "search_issues", "list_issues"]

github_mcp_toolset = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="https://api.githubcopilot.com/mcp/",
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "X-MCP-Toolsets": "all",
            "X-MCP-Readonly": "true",
        },
    ),
    tool_filter=GITHUB_TOOL_FILTER,
)
```

### Step 2.2: Configure `.env` for `github-agent`

```bash
cd ~/agents/github-agent
cat << EOF > .env
GOOGLE_CLOUD_PROJECT=${PROJECT_ID}
GOOGLE_CLOUD_LOCATION=global
GOOGLE_GENAI_USE_VERTEXAI=True
MODEL=gemini-3.5-flash
GITHUB_PERSONAL_ACCESS_TOKEN=<YOUR_GITHUB_PAT>
GITHUB_MCP_URL=https://api.githubcopilot.com/mcp/
EOF
```

### Step 2.3: Run Unit Tests & Deploy `github-agent` to Vertex AI Agent Runtime

```bash
cd ~/agents/github-agent
uv run pytest tests/unit

agents-cli deploy --project ${PROJECT_ID} --no-confirm-project --no-wait \
  --update-env-vars "$(grep -v '^#' .env | grep -v '^$' | grep -v '^GOOGLE_CLOUD_PROJECT' | paste -sd,)"

# Monitor deployment status until DEPLOYED
agents-cli deploy --status
```

### Step 2.4: Verify the Deployed GitHub Agent Card & A2A Endpoint

Once deployed, export the Agent Card URL printed by `agents-cli deploy --status`:

```bash
export GITHUB_AGENT_URL="https://us-central1-aiplatform.googleapis.com/reasoningEngines/v1/projects/<PROJECT_NUMBER>/locations/us-central1/reasoningEngines/<ENGINE_ID>/api/a2a/app/.well-known/agent-card.json"
echo "export GITHUB_AGENT_URL='${GITHUB_AGENT_URL}'" >> ~/.bashrc

# Verify the authenticated Agent Card JSON
curl -sS -H "Authorization: Bearer $(gcloud auth print-access-token)" "${GITHUB_AGENT_URL}" | python3 -m json.tool

# Smoke test the deployed Reasoning Engine
export GITHUB_ENGINE_URL=$(echo "${GITHUB_AGENT_URL}" | sed -E 's#/reasoningEngines/v1/#/v1/#; s#/api/.*##')
agents-cli run --url "${GITHUB_ENGINE_URL}" --mode adk "Find the google/adk-python repository"
```

---

## Task 3: Implement & Deploy the Stack Exchange Specialist (`stackexchange-agent`)

The `stackexchange-agent` is a deterministic, non-LLM **LangGraph** agent served natively over **A2A 1.x** with backward compatibility for **A2A 0.3** clients.

### Step 3.1: Build the LangGraph `StateGraph` in `stackexchange-agent/app/agent.py`

Edit `~/agents/stackexchange-agent/app/agent.py` to wire the `search` node into the `StateGraph`:

```python
graph = (
    StateGraph(State)
    .add_node("search", search)
    .add_edge(START, "search")
    .add_edge("search", END)
    .compile()
)
```

### Step 3.2: Advertise Dual `1.0` and `0.3` Interfaces in `stackexchange-agent/app/server.py`

Because the root ADK `RemoteA2aAgent` uses `a2a-sdk` `0.3.x`, update `build_agent_card()` in `~/agents/stackexchange-agent/app/server.py` to advertise both protocol versions on `rpc_url` (while `create_jsonrpc_routes` has `enable_v0_3_compat=True`):

```python
        supported_interfaces=[
            AgentInterface(
                protocol_binding="JSONRPC",
                protocol_version="1.0",
                url=rpc_url,
            ),
            AgentInterface(
                protocol_binding="JSONRPC",
                protocol_version="0.3",
                url=rpc_url,
            ),
        ],
```

### Step 3.3: Run Unit Tests, Build Container Image, and Deploy to Cloud Run

```bash
cd ~/agents/stackexchange-agent
uv run pytest tests/unit

# Build image in Cloud Build and push to Artifact Registry
gcloud builds submit --tag ${REGION}-docker.pkg.dev/${PROJECT_ID}/agents/stackexchange-agent:latest

# Deploy to Cloud Run (public endpoint)
gcloud run deploy stackexchange-agent \
  --image ${REGION}-docker.pkg.dev/${PROJECT_ID}/agents/stackexchange-agent:latest \
  --region ${REGION} \
  --allow-unauthenticated \
  --port 8080

# Update PUBLIC_URL so /.well-known/agent-card.json advertises the external Cloud Run URL
export SE_URL=$(gcloud run services describe stackexchange-agent --region ${REGION} --format='value(status.url)')
gcloud run services update stackexchange-agent --region ${REGION} --set-env-vars PUBLIC_URL=${SE_URL}

export STACKEXCHANGE_AGENT_URL="${SE_URL}/.well-known/agent-card.json"
echo "export STACKEXCHANGE_AGENT_URL='${STACKEXCHANGE_AGENT_URL}'" >> ~/.bashrc

# Verify the Agent Card JSON
curl -sS "${STACKEXCHANGE_AGENT_URL}" | python3 -m json.tool
```

---

## Task 4: Inspect & Verify the BigQuery Bug Database Specialist (`bq-agent`)

The `bq-agent` runs on **GKE Autopilot** and provides semantic vector search over `code_assist_bugs.known_bugs` in BigQuery using `text-embedding-004`.

### Step 4.1: Review the Semantic Vector Search Tool (`bq-agent/app/tools.py`)

The tool `find_similar_bugs(query: str)`:
1. Embeds the query string via `genai.Client(vertexai=True).models.embed_content(model="text-embedding-004", contents=query)`.
2. Runs BigQuery `VECTOR_SEARCH` with `distance_type => 'COSINE'` and `top_k => 3` over `code_assist_bugs.known_bugs` (`description_embedding`).
3. Returns formatted matches with `bug_id` (e.g., `BUG-1001`), `title`, `cosine_distance`, `description`, and `resolution`.

### Step 4.2: Verify the Live GKE Service & Unit Tests

```bash
cd ~/agents/bq-agent
uv run pytest tests/unit

# Retrieve GKE LoadBalancer IP if deployed on GKE
kubectl get svc
# Verify the A2A agent card
curl -sS "http://<GKE_LB_IP>:8080/a2a/app/.well-known/agent-card.json" | python3 -m json.tool
```

---

## Task 5: Implement & Deploy the Root Orchestrator (`code-assistant`)

The root `code-assistant` orchestrates all five specialists in parallel using an ADK 2.0 `Workflow` graph, captures remote A2A responses into session state, and loads the `using-developer-knowledge-mcp` skill from the **GCP Skill Registry**.

### Step 5.1: Publish the `using-developer-knowledge-mcp` Skill to GCP Skill Registry

```bash
cd ~/agents/code-assistant
uv run python scripts/publish_skill.py \
  --project ${PROJECT_ID} \
  --location ${REGION}
```

### Step 5.2: Implement `capture_response_to_state` in `code-assistant/app/callbacks.py`

Because `RemoteA2aAgent` has no `output_key`, implement `capture_response_to_state(state_key)` in `~/agents/code-assistant/app/callbacks.py` so each remote specialist writes its final text into `callback_context.state[state_key]`:

```python
def capture_response_to_state(state_key: str) -> Callable:
    async def _after_agent_callback(callback_context: CallbackContext):
        name = callback_context.agent_name
        for event in reversed(callback_context.session.events):
            if event.author == name and event.content and event.content.parts:
                text = "\n".join(p.text for p in event.content.parts if p.text)
                if text:
                    callback_context.state[state_key] = text
                    break
        return None

    return _after_agent_callback
```

### Step 5.3: Wire Remote Specialists & Workflow Graph in `code-assistant/app/agent.py`

In `~/agents/code-assistant/app/agent.py`:
1. Configure `github_agent` with `httpx_client=google_authed_client()`, `use_legacy=False`, and `after_agent_callback=capture_response_to_state("github_findings")`.
2. Configure `stackexchange_agent` using `CleanQueryRemoteA2aAgent` (standard A2A client without `use_legacy`) and `after_agent_callback=capture_response_to_state("stackexchange_findings")`.
3. Configure `salesforce_agent` with `use_legacy=False`, `a2a_request_meta_provider=user_id_meta_provider`, and `after_agent_callback=capture_response_to_state("salesforce_findings")`.
4. Configure `bug_db_agent` with `use_legacy=False` and `after_agent_callback=capture_response_to_state("bug_findings")`.
5. Define the `Workflow` edges fanning out from `query_extractor` to all 5 specialists, fanning in to `merge = JoinNode(name="merge")`, and transitioning `(merge, synthesizer)`.

### Step 5.4: Configure `.env` and Deploy `code-assistant` to Agent Runtime

```bash
cd ~/agents/code-assistant
cat << EOF > .env
GOOGLE_CLOUD_PROJECT=${PROJECT_ID}
GOOGLE_CLOUD_LOCATION=global
GOOGLE_GENAI_USE_VERTEXAI=True
MODEL=gemini-3.5-flash
DATASTORE_ID=code-manuals-datastore
DEVELOPER_KNOWLEDGE_MCP_URL=https://developerknowledge.googleapis.com/mcp
SKILL_REGISTRY_LOCATION=us-central1
GITHUB_AGENT_URL=${GITHUB_AGENT_URL}
STACKEXCHANGE_AGENT_URL=${STACKEXCHANGE_AGENT_URL}
SALESFORCE_AGENT_URL=${SALESFORCE_AGENT_URL}
BQ_AGENT_URL=${BQ_AGENT_URL}
EOF

# Run unit tests
uv run pytest tests/unit

# Deploy to Vertex AI Agent Runtime
rm -rf .venv
agents-cli deploy --project ${PROJECT_ID} --no-confirm-project --no-wait \
  --update-env-vars "$(grep -v '^#' .env | grep -v '^$' | grep -v '^GOOGLE_CLOUD_PROJECT' | paste -sd,)"

agents-cli deploy --status
```

---

## Task 6: Grant IAM Permissions & Publish to Gemini Enterprise

### Step 6.1: Authorize the Reasoning Engine Service Agent

When `code-assistant` runs on Vertex AI Agent Runtime, it executes as the Reasoning Engine Service Agent (`service-<PROJECT_NUMBER>@gcp-sa-aiplatform-re.iam.gserviceaccount.com`). Grant it permission to invoke `github-agent` on Agent Runtime (`roles/aiplatform.user`) and search `code-manuals-datastore` on Vertex AI Search (`roles/discoveryengine.viewer`):

```bash
gcloud beta services identity create --service=aiplatform.googleapis.com --project=${PROJECT_ID}
export PROJECT_NUMBER=$(gcloud projects describe ${PROJECT_ID} --format='value(projectNumber)')

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com" \
  --role="roles/discoveryengine.viewer"
```

### Step 6.2: Register `code-assistant` with Gemini Enterprise

```bash
cd ~/agents/code-assistant
agents-cli publish gemini-enterprise \
  --gemini-enterprise-app-id "projects/${PROJECT_NUMBER}/locations/global/collections/default_collection/engines/enterprise-app" \
  --display-name "Code Assist" \
  --description "Researches a production error across a bug database, the engineering handbook, Salesforce, GitHub, and Stack Exchange, and returns one cited fix."
```

---

## Task 7: Implement Salesforce 2LO + Vertex AI Memory Bank (`salesforce-agent`)

In Task 7, you complete the `salesforce-agent` specialist so it searches architectural decision records (ADRs) and policies uploaded to **Salesforce Files** (`ContentVersion`) via **2-legged OAuth (`client_credentials`)**, and remembers per-user context across sessions using **Vertex AI Memory Bank**.

### Step 7.1: Implement 2LO Authentication in `salesforce-agent/app/salesforce_client.py`

In `SalesforceClient.authenticate()`, execute a POST request against `https://{self.domain}/services/oauth2/token` with `grant_type="client_credentials"`:

```python
    def authenticate(self) -> dict:
        resp = requests.post(
            f"https://{self.domain}/services/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=_TIMEOUT_SECONDS,
        )
        _raise_for_status(resp)
        return resp.json()
```

### Step 7.2: Provision the Vertex AI Memory Bank (`scripts/create_memory_bank.py`)

Implement idempotent Memory Bank creation in `~/agents/salesforce-agent/scripts/create_memory_bank.py`:

```python
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
```

Run the script to obtain `MEMORY_BANK_ID`:

```bash
cd ~/agents/salesforce-agent
GOOGLE_CLOUD_PROJECT=${PROJECT_ID} uv run python scripts/create_memory_bank.py
```

### Step 7.3: Wire `PreloadMemoryTool` & `generate_memories_callback` in `salesforce-agent/app/agent.py`

```python
async def generate_memories_callback(callback_context: CallbackContext) -> None:
    await callback_context.add_session_to_memory()

root_agent = Agent(
    name="salesforce_agent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    # ...
    after_agent_callback=generate_memories_callback,
    tools=[search_salesforce, PreloadMemoryTool()],
)
```

### Step 7.4: Scope A2A Requests to Forwarded `user_id`

1. In `code-assistant/app/app_utils/a2a.py`, return the caller's `user_id` in A2A metadata:
   ```python
   def user_id_meta_provider(ctx: InvocationContext, a2a_message) -> dict[str, str]:
       return {"user_id": ctx.user_id}
   ```
2. In `salesforce-agent/app/app_utils/a2a.py`, override `run_request.user_id` when `request.metadata["user_id"]` is present:
   ```python
   def _user_scoped_request_converter(
       request, part_converter=convert_a2a_part_to_genai_part
   ):
       run_request = convert_a2a_request_to_agent_run_request(
           request, part_converter=part_converter
       )
       forwarded_user_id = (request.metadata or {}).get("user_id")
       if forwarded_user_id:
           run_request.user_id = forwarded_user_id
       return run_request
   ```

### Step 7.5: Deploy `salesforce-agent` to Cloud Run & Redeploy `code-assistant`

```bash
cd ~/agents/salesforce-agent
uv run pytest tests/unit

agents-cli deploy --project ${PROJECT_ID} --region ${REGION} --no-confirm-project \
  --update-env-vars "$(grep -v '^#' .env | grep -v '^$' | grep -v '^GOOGLE_CLOUD_PROJECT' | paste -sd,)"

gcloud run services add-iam-policy-binding salesforce-agent \
  --region=${REGION} --member=allUsers --role=roles/run.invoker

export SF_URL=$(gcloud run services describe salesforce-agent --region ${REGION} --format='value(status.url)')
export SALESFORCE_AGENT_URL="${SF_URL}/a2a/app/.well-known/agent-card.json"

# Verify Agent Card and test ADR lookup over A2A
curl -sS "${SALESFORCE_AGENT_URL}" | python3 -m json.tool
agents-cli run --url "${SF_URL}" --mode a2a "ADR-007"

# Update SALESFORCE_AGENT_URL in ~/agents/code-assistant/.env and redeploy root
cd ~/agents/code-assistant
agents-cli deploy --project ${PROJECT_ID} --no-confirm-project --no-wait \
  --update-env-vars "$(grep -v '^#' .env | grep -v '^$' | grep -v '^GOOGLE_CLOUD_PROJECT' | paste -sd,)"
```

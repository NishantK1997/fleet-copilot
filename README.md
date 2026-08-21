# Rayda Fleet Copilot

Agentic AI fleet management copilot built with FastAPI, LangGraph, Streamlit, SQLAlchemy, Alembic, and SQLite.

## Phase 1 Status

Implemented:

- Project structure
- SQLite-backed SQLAlchemy session setup
- FastAPI `/health` endpoint
- Alembic configuration
- Dockerfile and Docker Compose for API and Streamlit
- `.env.example` with Hugging Face Llama configuration placeholders
- Phase 2 database schema and migration
- Phase 3 idempotent NDJSON telemetry ingestion
- Phase 4 demo admin seeding and JWT login
- Phase 5 tenant isolation helpers and verification tests
- Phase 6 tenant-scoped deterministic read tools
- Phase 7 LangGraph agent loop and authenticated chat endpoint
- Phase 8 deterministic insight and trend detection
- Phase 9 evidence-backed action proposals
- Phase 10 human approval and action execution
- Phase 11 Streamlit login, chat, evidence, and approval UI

## Local Setup

```bash
cp .env.example .env
```

Edit `.env` and set:

```env
HUGGINGFACE_API_KEY=your-key
JWT_SECRET=your-long-random-secret
```

Run the API locally:

```bash
uvicorn app.main:app --reload
```

Check health:

```bash
curl http://localhost:8000/health
```

Run migrations and seed telemetry:

```bash
python3 -m alembic upgrade head
python3 scripts/seed_telemetry.py
python3 scripts/seed_users.py
```

Expected telemetry summary:

- `3` companies
- `25` devices
- `750` telemetry snapshots
- `750` disk volume rows
- `734` network interface rows
- `3855` installed software rows
- `2250` compliance result rows

<!-- Login Credentials -->
company Acme
email = admin@acme.example
password = AcmeAdmin123! 


company Globex
email = admin@globex.example
password = GlobexAdmin123! 

company Initech
email = admin@globex.example
password = InitechAdmin123! 


## Demo Login Credentials

The seed script creates one admin per company.

| Company | Email | Password |
| --- | --- | --- |
| Acme | `admin@acme.example` | `AcmeAdmin123!` |
| Globex | `admin@globex.example` | `GlobexAdmin123!` |
| Initech | `admin@initech.example` | `InitechAdmin123!` |

Passwords can be overridden before seeding with:

```env
ACME_ADMIN_PASSWORD=your-password
GLOBEX_ADMIN_PASSWORD=your-password
INITECH_ADMIN_PASSWORD=your-password
```

Login API:

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@acme.example","password":"AcmeAdmin123!"}'
```

## Tenant Isolation Check

Run the standalone Phase 5 check:

```bash
python3 scripts/check_phase5_tenant_isolation.py
```

Expected output:

```text
forged company_id ignored: PASS
tenant list scoped to acme-001: PASS
cross-tenant device blocked: PASS
```

Run the pytest coverage:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_phase5_tenant_isolation.py
```

## Policy Configuration

Thresholds live in [config/policies.yaml](config/policies.yaml). The app loads this file for default read-tool and insight/action evidence policies.

Examples:

```yaml
read_tools:
  low_disk_percent: 10
  persistent_ratio: 0.5
  memory_used_percent: 85
  battery_cycle_count: 900
  battery_capacity_low: 5000
```

Run the policy config tests:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_policy_config.py
```

## Read Tool Check

Run the Phase 6 read-tool smoke check:

```bash
python3 scripts/check_phase6_read_tools.py
```

Run the pytest coverage:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_phase6_read_tools.py
```

Implemented read tools:

- `get_fleet_summary`
- `search_devices`
- `get_device_details`
- `get_device_metric_history`
- `get_low_disk_devices`
- `get_memory_pressure_devices`
- `get_battery_risk_devices`
- `get_compliance_failures`
- `search_software_inventory`
- `search_telemetry`

## Chat Agent Check

Phase 7 adds an authenticated LangGraph flow:

```text
planner -> read tools -> evidence collector -> response
```

The planner is LLM-first when Hugging Face is configured:

```text
Hugging Face JSON planner -> Python validation -> allowlisted tool execution
```

If the model is unavailable, returns invalid JSON, selects an unknown tool, or tries to pass `company_id`, the app falls back to the deterministic planner.

Run the smoke check:

```bash
python3 scripts/check_phase7_agent.py
```

Run the tests:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_phase7_agent.py
```

Check the planner:

```bash
python3 scripts/check_llm_planner.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_llm_planner.py
```

Chat endpoint:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@acme.example","password":"AcmeAdmin123!"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

curl -X POST http://localhost:8000/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"Which devices are low on disk space?"}'
```

Hugging Face is optional at runtime. Add these values to `.env` when ready:

```env
LLM_PROVIDER=huggingface
LLM_MODEL=meta-llama/Llama-3.1-8B-Instruct
HUGGINGFACE_API_KEY=your_key
```

If the key is missing or the Hugging Face call fails, the agent still returns deterministic grounded answers from tool evidence.

## Insight Detection Check

Phase 8 detects:

- persistent low disk
- persistent RAM pressure
- battery replacement risk
- compliance drift

Run the smoke check:

```bash
python3 scripts/check_phase8_insights.py
```

Run the tests:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_phase8_insights.py
```

## Action Proposal Check

Phase 9 creates `PENDING_APPROVAL` proposals only. It does not execute operational actions.

Run the smoke check:

```bash
python3 scripts/check_phase9_proposals.py
```

Run the tests:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_phase9_proposals.py
```

Supported proposal action types:

- `create_upgrade_order`
- `open_remediation_ticket`
- `flag_device_for_replacement`
- `notify_employee`

## Approval and Action Execution Check

Phase 10 adds:

- `GET /actions/{proposal_id}`
- `POST /actions/{proposal_id}/approve`
- `POST /actions/{proposal_id}/reject`

Actions execute only after approval and revalidation.

Run the smoke check:

```bash
python3 scripts/check_phase10_actions.py
```

Run the tests:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_phase10_actions.py
```

## Streamlit UI

Run the API and Streamlit app:

```bash
python3 -m alembic upgrade head
python3 scripts/seed_telemetry.py
python3 scripts/seed_users.py
uvicorn app.main:app --reload
```

In another terminal:

```bash
streamlit run streamlit_app/app.py
```

Open http://localhost:8501 and log in with one of the demo admins.

The UI supports:

- login/logout
- tenant display
- chat
- tool trace display
- evidence display
- pending proposal Approve/Reject controls

Run the backend contract check used by the UI:

```bash
python3 scripts/check_phase11_streamlit_contract.py
```

Run the test:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_phase11_streamlit_contract.py
```

Run with Docker:

```bash
docker compose up --build
```

API: http://localhost:8000

Streamlit: http://localhost:8501

## Notes

SQLite is used for this take-home submission to avoid external database provisioning. The DB file is generated at `data/fleet_copilot.db` and is ignored by Git.

architecture

START
  ↓
Request Context
  ↓
Planner
  ↓
Agent / Tool Loop
  ↓
Read Tool(s)
  ↓
Evidence Collector
  ↓
Evidence Validator
  ↓
Question only?
  ├── YES → Response → END
  │
  └── NO / Action requested
            ↓
       Action Proposal Node
            ↓
       Evidence Policy Check
            ↓
       enough evidence?
        ├── NO → refuse action → END
        │
        └── YES
              ↓
        Store action_proposal
              ↓
        Human Approval Interrupt
              ↓
          Approve / Reject
            /        \
         Reject      Approve
           ↓            ↓
          END      Revalidate:
                   authentication
                   authorization
                   tenant
                   evidence
                   approval
                       ↓
                  Action Tool
                       ↓
                Operational Table
                       ↓
                   Audit Log
                       ↓
                      END
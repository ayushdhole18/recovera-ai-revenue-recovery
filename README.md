# ⚡ Recovera AI — Autonomous Revenue Recovery & Payment Failure Resolution Platform

Recovera AI is an intelligent, safety-first revenue recovery platform that detects failed payments, diagnoses failure root causes using Gemini 2.5 Flash, validates recovery strategies through a deterministic Merchant Rule Engine, and executes recovery workflows with real-time financial telemetry in Indian Rupees (INR ₹).

---

##  Problem Statement

Involuntary churn caused by payment failures accounts for **up to 40% of customer churn** in subscription and e-commerce businesses. Payments fail due to diverse reasons—insufficient funds, expired cards, stolen card blocks, bank downtime, or incorrect billing addresses. 

Traditional payment recovery relies on blunt force automated retries or manual outreach, leading to:
- **Excessive Gateway Fees**: Repeatedly retrying hard declines (e.g., stolen cards or closed accounts).
- **Customer Friction**: Spamming customers with billing alerts during quiet hours or for temporary bank glitches.
- **Uncontrolled Financial Risk**: Deploying unconstrained AI agents that could issue unauthorized discounts, bypass fraud controls, or trigger unauthorized financial retries.

---

##  Solution Overview

Recovera AI bridges advanced AI diagnostics with strict financial governance using a **Safety-First Architecture**:
1. **Automated Failure Detection**: Categorizes transaction declines into recoverable (`SOFT_DECLINE`) and unrecoverable (`HARD_DECLINE`) categories.
2. **Advisory AI Diagnosis Agent**: Employs **Gemini 2.5 Flash** (with a sub-500ms deterministic fallback engine) to analyze failure telemetry, estimate recovery probabilities, and draft personalized outreach messages.
3. **Deterministic Safety Rule Engine**: Functions as the **FINAL AUTHORITY**. AI recommendations are strictly advisory payloads that must pass merchant business constraints (`MAX_RETRIES`, `HARD_DECLINE_BLOCK`, `MIN_PROBABILITY`, `MAX_DISCOUNT_PCT`, `QUIET_HOURS`, `ALREADY_RECOVERED`) before execution.
4. **Explicit Recovery Execution**: Previews are strictly read-only. Payment retry execution and simulator calls occur **only** when explicitly triggered by user intervention.
5. **Immutable Audit Trail**: Preserves an append-only ledger enforced by SQLite database triggers prohibiting record modification or deletion.

---

##  Key Features

- **8 Operational Workspace Screens**:
  1. **Executive Dashboard**: Real-time financial telemetry in INR (`₹`), revenue leakage breakdown, recovery funnel, and action performance.
  2. **At-Risk Transactions Workspace**: Multi-column filterable grid (Merchant, Status, Decline Category, Recoverability) with search capabilities and read-only inspection.
  3. **8-Step Recovery Stepper**: Step-by-step visual telemetry tracking payment failure, detection, AI diagnosis, probability estimation, proposed action, safety check, explicit execution, and revenue impact.
  4. **AI Recovery Agent Inspector**: Deep dive into failure root causes, confidence scores, message drafts, and active model status (`GEMINI 2.5 FLASH LIVE` vs `DETERMINISTIC FALLBACK`).
  5. **Safety Rule Engine**: Merchant policy manager displaying active rules, evaluation statistics (Allowed, Modified, Blocked), and rule decision logs.
  6. **Recovery Executor & Simulator**: Execution control sandbox with pre-execution safety validation, duplicate recovery locking, and gateway simulation.
  7. **Audit Trail Inspector**: Searchable chronological timeline with actor filtering (`DETECTOR`, `AI_AGENT`, `RULE_ENGINE`, `EXECUTOR`, `SYSTEM`) and expandable JSON payload viewer.
  8. **Analytics & Model Evaluation**: Benchmark model evaluation displaying Mean Absolute Error (MAE), probability calibration buckets, safety metrics, and Plotly calibration charts.
- **Centralized INR (₹) Formatting**: All financial values across cards, tables, steppers, and charts are standardized in Indian Rupees (`₹83.50 = $1.00 USD`).
- **Sub-500ms Fallback Engine**: Guarantees zero system downtime if API keys are missing or external network requests time out.

---

##  Application Workflow

```
[ Failed Payment Event ]
          │
          ▼
[ Step 1: Recovery Detector ] ──► Classifies decline (SOFT_DECLINE vs HARD_DECLINE)
          │
          ▼
[ Step 2: AI Diagnosis Agent ] ──► Generates root cause, probability & outreach draft (Advisory)
          │
          ▼
[ Step 3: Safety Rule Engine ] ──► Deterministic validation against merchant rules (FINAL AUTHORITY)
          │
     ┌────┴───────────────────────────┐
     │                                │
[ ALLOWED / MODIFIED ]        [ BLOCKED ] ──► Execution prohibited
     │
     ▼
[ Step 4: User Explicit Action ] ──► Click "Execute Recovery Strategy"
          │
          ▼
[ Step 5: Gateway Simulator ] ──► Executes payment attempt & records result
          │
          ▼
[ Step 6: Append-Only Audit Log ] ──► Appends immutable timeline record in SQLite
```

---

##  System Architecture

```
                                  +---------------------------------------+
                                  |         Streamlit Operational UI      |
                                  |         (8 Operational Screens)        |
                                  +-------------------+-------------------+
                                                      |
                                                      v
                                  +-------------------+-------------------+
                                  |    Recovery Detector Service          |
                                  |    (Soft vs Hard Decline Classifier)  |
                                  +-------------------+-------------------+
                                                      |
                                                      v
                                  +-------------------+-------------------+
                                  |    AI Recovery Agent (Gemini 2.5)     |
                                  |    (Sub-500ms Fallback Engine)        |
                                  +-------------------+-------------------+
                                                      | (Advisory Proposal)
                                                      v
                                  +-------------------+-------------------+
                                  |    Safety Rule Engine (FINAL AUTH)    |
                                  |    (Business Policy Validation)       |
                                  +-------------------+-------------------+
                                                      | (Approved / Modified Payload)
                                                      v
                                  +-------------------+-------------------+
                                  |    User-Triggered Executor Engine     |
                                  |    (Deterministic Gateway Simulator)  |
                                  +-------------------+-------------------+
                                                      |
                                                      v
                                  +-------------------+-------------------+
                                  |    SQLite Database & Audit Triggers   |
                                  |    (Immutable Append-Only Ledger)     |
                                  +---------------------------------------+
```

---

##  AI/ML Functionality & Fallback Architecture

- **Primary Model**: Powered by **Google Gemini 2.5 Flash** (`google-genai` SDK) utilizing structured JSON response schema enforcement.
- **Diagnostic Capabilities**:
  - Failure root cause analysis based on decline codes, attempt counts, customer tier, and card brand.
  - Estimated recovery probability score (`0.00` to `1.00`) and confidence score (`0.00` to `1.00`).
  - Recommended recovery action selection (`SMART_RETRY`, `DUNNING_EMAIL`, `PAYMENT_LINK_SMS`, `INCENTIVIZED_RETRY`, `MANUAL_REVIEW`, `NO_ACTION_BLOCK`).
  - Personalized customer outreach message generation.
- **Deterministic Fallback Engine**: If `GEMINI_API_KEY` is not configured, or if an API call exceeds latency thresholds/fails, Recovera AI automatically engages a rule-based deterministic fallback (`is_fallback=True`). This guarantees zero application crashes and sub-500ms response guarantees.
- **Advisory Boundary**: The AI model is strictly advisory. It generates candidate recommendations that are parsed into Pydantic models and handed over to the Safety Rule Engine.

---

##  Safety Architecture & Governance

The **Rule Engine** is the non-bypassable final authority before financial execution:
- **`MAX_RETRY_COUNT`**: Enforces merchant cap on cumulative retry attempts.
- **`HARD_DECLINE_BLOCK`**: Automatically blocks retries on fraud, stolen cards, or closed accounts.
- **`MIN_PROBABILITY`**: Prevents retry execution if estimated recovery probability falls below merchant threshold.
- **`MAX_DISCOUNT_PCT`**: Caps promotional discounts offered during incentivized retries.
- **`QUIET_HOURS`**: Shifts customer outreach actions to silent background retries during configured UTC hours.
- **`ALREADY_RECOVERED`**: Prevents double-execution on transactions already in `RECOVERED` or `SUCCESS` status.

---

##  Recovery Execution Flow (Simulated Gateway)

To evaluate recovery strategies without real-world credit card processing risks, Recovera AI integrates a **Deterministic Payment Gateway Simulator** (`app/services/executor.py`):
1. **Pre-Execution Check**: Verifies that `rule_validation.is_allowed == True`.
2. **Explicit Trigger**: Execution occurs **only** on user action (`execute_single_transaction_recovery`). Page browsing and transaction inspections are strictly read-only.
3. **Simulation Logic**: Evaluates gateway response codes (e.g., `200_SUCCESS`, `402_INSUFFICIENT_FUNDS`, `403_STOLEN_CARD`), latency (ms), and recovered amounts.
4. **State Transition**: Updates transaction status in SQLite (`FAILED` $\rightarrow$ `RECOVERED` / `SOFT_FAILED` / `HARD_FAILED`).

*Note: Payment processing in this repository is executed via a deterministic simulator designed for evaluation and demonstration.*

---

## Append-Only Audit Trail

Recovera AI implements an immutable governance ledger stored in the SQLite `audit_trail` table:
- **Database-Level Triggers**:
  - `prevent_audit_update`: Aborts any SQL `UPDATE` queries on `audit_trail`.
  - `prevent_audit_delete`: Aborts any SQL `DELETE` queries on `audit_trail`.
- **Standardized Event Types**: Logs timestamps, transaction IDs, actor names (`DETECTOR`, `AI_AGENT`, `RULE_ENGINE`, `EXECUTOR`, `SYSTEM`), status transitions, and raw JSON payload details.

---

##  Analytics & Model Evaluation

The evaluation suite (`app/services/evaluation.py`) measures framework performance:
- **Revenue Metrics**: Revenue at risk, potentially recoverable revenue, recovered revenue, and recovery rate percentage formatted in INR (`₹`).
- **AI Probability Calibration**: Compares AI probability predictions against actual simulator outcomes across 5 probability calibration buckets (`0-20%`, `20-40%`, `40-60%`, `60-80%`, `80-100%`).
- **Mean Absolute Error (MAE)**: Measures calibration accuracy between predicted probabilities and actual binary outcomes.
- **Safety Violation Breakdown**: Computes recommendation approval, modification, and block rates along with rule violation frequency statistics.

---

##  Technology Stack

- **Frontend & Visualization**: Streamlit (v1.30+), Plotly (v5.0+), Custom Vanilla CSS (`assets/style.css` with Copperplate Gothic Light typography).
- **Backend & Core Logic**: Python 3.10+, Pydantic (v2.0+), Pandas, NumPy.
- **Database & Governance**: SQLite3 with foreign keys & database-level triggers.
- **AI Engine**: Google GenAI SDK (`google-genai>=0.1.0`), Gemini 2.5 Flash.
- **Testing**: Pytest (v7.0+).

---

##  Project Structure

```
recovera-ai/
├── app/
│   ├── __init__.py
│   ├── config.py                 # Configuration & environment variables
│   ├── main.py                   # Streamlit operational frontend (8 screens)
│   ├── components/               # UI components (Metric cards, badges, banners, charts)
│   │   ├── charts.py             # Plotly dark fintech chart builders
│   │   ├── metric_card.py        # Metric card renderer
│   │   ├── safety_banner.py      # Safety rule outcome banner renderer
│   │   ├── status_badge.py       # Status badge renderer
│   │   └── workflow_stepper.py   # 8-step stepper component
│   ├── core/                     # Database & core data models
│   │   ├── database.py           # SQLite connection, schema, & audit triggers
│   │   └── models.py             # Pydantic data schemas & enums
│   ├── services/                 # Core domain services
│   │   ├── ai_agent.py           # Gemini AI Diagnostic Agent & Fallback engine
│   │   ├── analytics.py          # Revenue telemetry & audit timeline helpers
│   │   ├── detector.py           # Recovery Detector classifier
│   │   ├── evaluation.py         # AI Calibration & MAE Evaluator
│   │   ├── executor.py           # Recovery Executor & Gateway Simulator
│   │   ├── prompts.py            # System prompts & structured JSON instructions
│   │   ├── rule_engine.py        # Safety Business Rule Engine
│   │   └── ui_helpers.py         # Streamlit state helpers & grid filtering
│   └── utils/
│       ├── currency.py           # Centralized INR (₹) formatting utility
│       └── __init__.py
├── assets/
│   └── style.css                 # Visual design system & typography overrides
├── data/
│   ├── recovera.db               # SQLite database file
│   ├── evaluation_results.json   # Benchmark evaluation output
│   └── evaluation_report.md      # Formatted evaluation report
├── tests/
│   ├── test_ai_agent.py          # AI agent & fallback unit tests
│   ├── test_analytics.py         # Analytics calculation tests
│   ├── test_currency.py          # INR currency utility unit tests
│   ├── test_database.py          # SQLite schema & trigger immutability tests
│   ├── test_detector.py          # Decline classification tests
│   ├── test_evaluation.py        # Calibration & MAE evaluator tests
│   ├── test_executor.py          # Recovery simulator & execution safety tests
│   ├── test_models.py            # Pydantic schema validation tests
│   ├── test_rule_engine.py       # Rule engine validation & quiet hours tests
│   └── test_ui_helpers.py        # UI helpers & grid filter tests
├── .env.example                  # Environment configuration template
├── .gitignore                    # Git exclusion rules
├── requirements.txt              # Production Python dependencies
└── README.md                     # Project documentation
```

---

## 🖼️ Application Screenshots

*(Placeholders — Add screenshots after launching the live application)*

| Executive Dashboard | At-Risk Workspace |
|:---:|:---:|
| ![Executive Dashboard Placeholder](https://via.placeholder.com/600x350/141C2B/F8FAFC?text=Executive+Dashboard+INR+Telemetry) | ![At-Risk Workspace Placeholder](https://via.placeholder.com/600x350/141C2B/F8FAFC?text=At-Risk+Transactions+Filterable+Grid) |

| 8-Step Recovery Stepper | AI Recovery Agent |
|:---:|:---:|
| ![8-Step Stepper Placeholder](https://via.placeholder.com/600x350/141C2B/F8FAFC?text=8-Step+Interactive+Recovery+Stepper) | ![AI Recovery Agent Placeholder](https://via.placeholder.com/600x350/141C2B/F8FAFC?text=AI+Agent+Diagnosis+%26+Advisory+Banner) |

| Safety Rule Engine | Audit Trail Inspector |
|:---:|:---:|
| ![Safety Rule Engine Placeholder](https://via.placeholder.com/600x350/141C2B/F8FAFC?text=Safety+Rule+Engine+Configuration) | ![Audit Trail Inspector Placeholder](https://via.placeholder.com/600x350/141C2B/F8FAFC?text=Immutable+Audit+Trail+Timeline) |

---

## 💻 Local Installation Instructions

### Prerequisites
- Python 3.10 or higher
- Git

### Step 1: Clone Repository
```bash
git clone https://github.com/ayushdhole18/recovera-ai-revenue-recovery.git
cd recovera-ai-revenue-recovery
```

### Step 2: Create & Activate Virtual Environment
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### Step 3: Install Dependencies
```bash
pip install -r requirements.txt
```

---

## 🔑 Environment Variables

Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Configure settings in `.env`:
```ini
# Gemini API Key (Optional: system uses deterministic fallback if blank)
GEMINI_API_KEY=your_gemini_api_key_here

# Database path (Optional: defaults to data/recovera.db)
DATABASE_PATH=data/recovera.db
```

---

## 🚀 Running the Streamlit Application

Launch the operational dashboard locally:
```bash
streamlit run app/main.py
```

Open your browser at `http://localhost:8501`.

---

## 🧪 Testing Instructions

Run the full automated test suite (75 unit and integration tests):
```bash
python -m pytest
```

Run test suite with detailed output and coverage:
```bash
python -m pytest -v --tb=short
```

---

## ☁️ Deployment Information

Recovera AI can be deployed to cloud hosting platforms:

### Deploying on Streamlit Community Cloud
1. Push repository to GitHub.
2. Connect repository to [Streamlit Community Cloud](https://streamlit.io/cloud).
3. Set Main file path to `app/main.py`.
4. Add `GEMINI_API_KEY` under Advanced Settings $\rightarrow$ Secrets.

### Deploying on Render / Railway / Docker
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `streamlit run app/main.py --server.port $PORT --server.address 0.0.0.0`

---

## ⚠️ Known Limitations

1. **Simulated Gateway**: Credit card retries, dunning outreach, and payment links are executed through a deterministic simulator (`executor.py`) rather than live payment processor APIs (Stripe/Razorpay).
2. **Local SQLite Storage**: In cloud hosting environments with ephemeral filesystems (e.g., Heroku or basic Render instances), SQLite database writes persist during runtime but reset on container restarts unless a persistent storage volume is attached.
3. **Batch Dataset**: The demo synthetic dataset includes 1,200 seeded transactions for evaluation purposes.

---

## 🔮 Future Improvements

- **Live Gateway Adapters**: Build production API adapters for Stripe Billing, Razorpay Subscription Webhooks, and Chargebee.
- **Multi-Tenant Authentication**: Add role-based authentication (RBAC) and merchant account isolation.
- **RL Delay Optimization**: Train reinforcement learning agents to predict optimal outreach hour windows per individual customer timezone.

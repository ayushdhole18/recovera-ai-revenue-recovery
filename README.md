# Recovera AI - AI-Powered Revenue Recovery Platform

Recovera AI is an AI-powered revenue recovery platform built for subscription and e-commerce merchants to automatically detect, diagnose, validate, execute, and track payment failure recovery workflows.

---

## Capabilities Overview

- **Phase 1: Foundation & Data Layer**
  - **Relational Database Schema**: 6 core tables (`merchants`, `customers`, `transactions`, `diagnostics`, `business_rules`, `audit_trail`).
  - **Pydantic Type Validation**: Strict models with `Decimal` 2-place currency precision (`ROUND_HALF_UP`) and enum validation.
  - **Append-Only Audit Trail**: SQLite database triggers preventing modification/deletion of audit entries.
  - **Synthetic Data Generator**: Deterministic seed generator producing 10 merchants, 248 customers, 1,200 transactions, 40 business rules, and 354 audit log entries.

- **Phase 2: Detection & Safety Business Rule Engine**
  - **Recovery Detector (`app/services/detector.py`)**: Classifies failed transactions deterministically into `SOFT_DECLINE`, `HARD_DECLINE`, and `DATA_MISMATCH`.
  - **Safety Rule Engine (`app/services/rule_engine.py`)**: Final authority enforcing merchant constraints (`MAX_RETRY_COUNT`, `HARD_DECLINE_BLOCK`, `MIN_PROBABILITY`, `MAX_DISCOUNT_PCT`, `QUIET_HOURS`, `ALREADY_RECOVERED`). Actions violating safety rules are modified to safe alternatives or blocked.

- **Phase 3: AI Diagnostic Agent using Gemini**
  - **Prompt Engine (`app/services/prompts.py`)**: Instructions guiding Gemini to diagnose root causes, estimate recovery probabilities, recommend allowed actions, and draft outreach messages.
  - **Gemini Service (`app/services/ai_agent.py`)**: Structured JSON diagnostic agent powered by Gemini 2.5 Flash API.
  - **Deterministic Fallback Engine**: System defaults gracefully to rule-based fallback (`is_fallback=True`) if `GEMINI_API_KEY` is missing, or if the API times out or errors.
  - **Safety Boundary Guarantee**: AI recommendations are strictly advisory payloads. AI never executes financial actions directly.

- **Phase 4: Recovery Execution Engine & Payment Simulator**
  - **Recovery Executor (`app/services/executor.py`)**: Executes ONLY actions approved by the Rule Engine (`rule_validation.final_action`). Blocked actions (`is_allowed=False`) are never executed (`NO_ACTION_BLOCK`).
  - **Deterministic Simulator**: Reproducible mock payment gateway simulating payment retries, dunning outreach, SMS payment links, and decline behaviors.

- **Phase 5: Audit, Analytics & Recovery Evaluation**
  - **Audit Investigation Helper (`get_transaction_audit_timeline`)**: Reconstructs the complete lifecycle timeline for any transaction ID across 11 standardized audit event types.
  - **Recovery Metric Definitions**:
    - **Transaction Recovery Rate**: `(successful_recovered_transactions / recoverable_transactions) * 100`
    - **Revenue Recovery Rate**: `(recovered_revenue / potentially_recoverable_revenue) * 100`
    - **Average Recovered Value**: `recovered_revenue / successful_recoveries`
  - **AI Probability Calibration & MAE (`app/services/evaluation.py`)**: Evaluates AI prediction accuracy against actual outcomes using Mean Absolute Error (MAE) and 5 probability calibration buckets (`0-20%`, `20-40%`, `40-60%`, `60-80%`, `80-100%`).
  - **Safety Rule Enforcement Metrics**: Tracks approved, modified, and blocked recommendation counts and rule violation frequency statistics.
  - **Reproducible Evaluation Pipeline**: Exports evaluation metrics idempotently to `data/evaluation_results.json` and `data/evaluation_report.md` without mutating database states or double-counting revenue.

---

## 📁 Project Structure

```
recovera-ai/
├── app/
│   ├── __init__.py
│   ├── config.py                 # App settings & path configuration
│   ├── core/
│   │   ├── __init__.py
│   │   ├── models.py             # Pydantic data schemas & enums
│   │   ├── database.py           # SQLite connection, schema initialization & CRUD helpers
│   │   └── seed_data.py          # Synthetic data generator & database seeder
│   ├── components/               # Streamlit UI widgets (Phase 6)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── detector.py           # Recovery Detector service
│   │   ├── rule_engine.py        # Safety Business Rule Engine service
│   │   ├── prompts.py            # Gemini AI prompt templates & system instructions
│   │   ├── ai_agent.py           # Gemini AI Diagnostic Agent service & fallback engine
│   │   ├── executor.py           # Recovery Execution Engine & Payment Simulator
│   │   ├── analytics.py          # Revenue Analytics & Breakdown Summaries
│   │   └── evaluation.py         # AI Calibration, MAE & Batch Evaluator Engine
│   └── utils/                    # Shared formatting & logging helpers
├── data/
│   ├── recovera.db               # SQLite database file
│   ├── evaluation_results.json   # Machine-readable evaluation metrics output
│   └── evaluation_report.md      # Human-readable markdown evaluation report
├── tests/
│   ├── test_models.py            # Unit tests for Pydantic models & validation
│   ├── test_database.py          # Unit tests for SQLite database & append-only triggers
│   ├── test_detector.py          # Unit tests for recovery detection service
│   ├── test_rule_engine.py       # Unit tests for safety rule engine & determinism
│   ├── test_ai_agent.py          # Unit tests for AI agent, fallback, & safety boundary
│   ├── test_executor.py          # Unit tests for simulator, executor safety, & E2E integration
│   ├── test_analytics.py         # Unit tests for revenue analytics & audit timeline reconstruction
│   └── test_evaluation.py        # Unit tests for MAE, calibration buckets & evaluation reproducibility
├── .env.example                  # Environment configuration template
├── .gitignore                    # Version control exclusion rules
├── requirements.txt              # Project dependencies
└── README.md                     # Documentation
```

---

## 🚀 Quickstart & Evaluation Commands

### 1. Install Dependencies

Ensure Python 3.10+ is installed, then run:

```bash
pip install -r requirements.txt
```

### 2. Run Automated Test Suite

Execute the complete pytest test suite (60 unit & integration tests across Phases 1–5):

```bash
python -m pytest tests/ -v
```

### 3. Run Batch Evaluation Pipeline

Generate evaluation reports (`data/evaluation_results.json` and `data/evaluation_report.md`):

```bash
python -c "from app.services.evaluation import run_full_evaluation; run_full_evaluation()"
```

> **Disclaimer**: Evaluation metrics are computed against synthetic transaction data and a deterministic payment simulator. They demonstrate framework measurability and calibration design for hackathon evaluation and should not be construed as real-world production performance guarantees.

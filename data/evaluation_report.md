# Recovera AI - Batch Recovery Evaluation Report

## 1. Executive Summary & Recovery Metrics

- **Total Failed Transactions Analyzed**: 354
- **Potentially Recoverable Transactions**: 332 (classified by Detector)
- **Unrecoverable Transactions**: 22 (hard declines / permanent errors)
- **Total Failed Revenue (At Risk)**: $88,724.33
- **Potentially Recoverable Revenue**: $81,545.24
- **Revenue Recovered**: $30,452.52

### Explicit Recovery Rate Metric Breakdown:
- **Recoverable Transaction Recovery Rate**: **38.86%** (`129 / 332` recoverable transactions)
- **Overall Failed-Transaction Recovery Rate**: **36.44%** (`129 / 354` total failed transactions)
- **Revenue Recovery Rate**: **37.34%** (`$30,452.52 / $81,545.24` recoverable revenue)
- **Average Recovered Transaction Value**: **$236.07** (`$30,452.52 / 129` recoveries)

## 2. Safety & Business Rule Enforcement Metrics

- **Total AI Recommendations Evaluated**: 354
- **Approved Recommendations**: 276
- **Modified Recommendations**: 0 (0.00%)
- **Blocked Recommendations**: 78 (22.03%)

### Rule Violation Frequency (Non-Mutually-Exclusive)

> *Note: A single proposed recovery action may violate multiple safety rules simultaneously. Therefore, total rule violations may exceed total blocked recommendations.*

- `MAX_RETRY_COUNT`: 56 violations
- `HARD_DECLINE_BLOCK`: 22 violations
- `MIN_PROBABILITY`: 22 violations

## 3. AI Probability Calibration & Evaluation

- **Evaluation Population**: All 354 evaluated failed transactions in evaluation population
- **Average Predicted Probability**: 0.6116
- **AI Prediction Outcome Rate**: **36.44%** (`128 / 354` total evaluated predictions)
- **Mean Absolute Error (MAE)**: **0.4641**

> *Methodological Limitation Note: Probability estimates reflect uncalibrated synthetic heuristic recommendations. High MAE (0.4641) indicates model overconfidence, which is expected for raw heuristic models before empirical calibration models are trained on real merchant payment data.*

| Probability Bucket | Predictions | Avg Predicted Prob | Actual Recovery Rate |
|--------------------|-------------|--------------------|----------------------|
| 0-20% | 22 | 0.0000 | 0.00% |
| 20-40% | 0 | 0.0000 | 0.00% |
| 40-60% | 27 | 0.5000 | 0.00% |
| 60-80% | 242 | 0.6306 | 34.71% |
| 80-100% | 63 | 0.8000 | 71.43% |

## 4. Source Breakdown (Gemini AI vs Fallback Heuristic Engine)

- **Gemini AI Diagnoses**: 0 (Recovered: $0.00)
- **Fallback Engine Diagnoses**: 354 (Recovered: $30,452.52)

> *Configuration Note: Offline evaluation run defaulted to the deterministic fallback engine (`is_fallback=True`) because `GEMINI_API_KEY` was omitted during benchmark execution to ensure offline speed, reproducibility, and zero API costs. Live execution uses Gemini 2.5 Flash when `GEMINI_API_KEY` is provided in `.env`.*

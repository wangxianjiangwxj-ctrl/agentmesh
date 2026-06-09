# AgentMesh E2E Stress Test Report

- **Date**: 2026-06-07 08:32:23 (Asia/Shanghai)
- **Total scenarios**: 4
- **Passed**: 4
- **Failed**: 0
- **Total duration**: 0.42s

---

## Scenario 1: scenario1_50_agents_concurrent

**Description**: 50 Agents register -> create tasks -> assign -> deliver -> verify -> reputation
**Status**: PASSED
**Duration**: 0.15s

### Execution Steps

| Step | Elapsed (s) | OK | Detail |
|------|------------|----|--------|
| service_init | 0.0145 | Yes |  |
| register_50_agents | 0.0198 | Yes | 50 agents |
| execute_25_tasks | 0.1127 | Yes | 25 tasks settled |
| verify_chains | 0.0 | Yes | evidence 125/125, audit 125/125 |

### Assertion Results

| Check | Expected | Actual | Passed |
|-------|----------|--------|--------|
| agents_registered | 50 | 50 | Yes |
| tasks_completed | 25 | 25 | Yes |
| evidence_chain_valid | True | True | Yes |
| audit_chain_valid | True | True | Yes |
| all_chains_ok | True | True | Yes |

### Performance Metrics

- **total_duration_s**: 0.147
- **agents**: 50
- **tasks**: 25
- **avg_time_per_task_s**: 0.0045
- **avg_reputation**: 3.36
- **evidence_entries**: 125
- **audit_entries**: 125
- **evidence_valid_pct**: 100.0
- **audit_valid_pct**: 100.0

---

## Scenario 2: scenario2_multi_round_economy

**Description**: 5 rounds x 20 agents cyclic economy (create task -> assign -> deliver -> verify -> new round)
**Status**: PASSED
**Duration**: 0.23s

### Execution Steps

| Step | Elapsed (s) | OK | Detail |
|------|------------|----|--------|
| service_init | 0.005 | Yes |  |
| register_20_agents | 0.0039 | Yes |  |
| round_1 | 0.0438 | Yes | 10 tasks |
| round_2 | 0.0442 | Yes | 10 tasks |
| round_3 | 0.0458 | Yes | 10 tasks |
| round_4 | 0.0406 | Yes | 10 tasks |
| round_5 | 0.0443 | Yes | 10 tasks |

### Assertion Results

| Check | Expected | Actual | Passed |
|-------|----------|--------|--------|
| five_rounds_completed | 5 | 5 | Yes |
| evidence_chain_all_valid | 250 | 250 | Yes |
| audit_chain_all_valid | 250 | 250 | Yes |
| reputation_above_prior | >2.0 | 3.80 | Yes |

### Performance Metrics

- **total_duration_s**: 0.228
- **rounds**: 5
- **agents**: 20
- **tasks_per_round**: 10
- **total_tasks**: 50
- **avg_round_time_s**: 0.046
- **avg_reputation**: 3.8
- **evidence_valid_pct**: 100.0
- **audit_valid_pct**: 100.0

---

## Scenario 3: scenario3_malicious_detection

**Description**: Fraud detection: false evidence, duplicate claim, escrow default
**Status**: PASSED
**Duration**: 0.01s

### Execution Steps

| Step | Elapsed (s) | OK | Detail |
|------|------------|----|--------|
| service_init | 0.0051 | Yes |  |
| fraud1_tampered_evidence | 0.002 | Yes | Tampered chain detected: True |
| fraud2_duplicate_claim | 0.0001 | Yes | Duplicate claim detected: True |
| fraud3_escrow_default | 0.0009 | Yes | Escrow default detected: True |
| fraud4_signature_mismatch | 0.0018 | Yes | Signature integrity verified: True |

### Assertion Results

| Check | Expected | Actual | Passed |
|-------|----------|--------|--------|
| tampered_evidence_detected | True | True | Yes |
| duplicate_claim_detected | True | True | Yes |
| escrow_default_detected | True | True | Yes |
| evidence_signature_integrity | True | True | Yes |
| detection_rate | 4/4 | 4/4 | Yes |

### Performance Metrics

- **total_duration_s**: 0.012
- **fraud_patterns_tested**: 4
- **fraud_patterns_detected**: 4
- **detection_rate_pct**: 100.0
- **honest_agents**: 6
- **fraud_agents**: 3
- **detection_details**:
  - tampered_evidence: DETECTED (Tampered payload_digest in evidence chain)
  - duplicate_claim: DETECTED (Duplicate active task assignments)
  - escrow_default: DETECTED (Missing deliver/verify/settle entries)
  - evidence_signature_mismatch: DETECTED (All evidence entries from legitimate actors only)

---

## Scenario 4: scenario4_chained_tasks

**Description**: TaskA -> TaskB -> TaskC chained dependency with sequential verification
**Status**: PASSED
**Duration**: 0.02s

### Execution Steps

| Step | Elapsed (s) | OK | Detail |
|------|------------|----|--------|
| service_init | 0.0037 | Yes |  |
| execute_chained_tasks | 0.0129 | Yes | Tasks executed: ['s4-task-A', 's4-task-B', 's4-task-C'] |
| verify_dependency_order | 0.0 | Yes | Order: ['s4-task-A', 's4-task-B', 's4-task-C'], valid: True |
| verify_dependency_reference | 0.0001 | Yes | Dependency ref from B->A: True |

### Assertion Results

| Check | Expected | Actual | Passed |
|-------|----------|--------|--------|
| task_a_executed | True | True | Yes |
| task_b_executed | True | True | Yes |
| task_c_executed | True | True | Yes |
| chain_order_valid | True | True | Yes |
| evidence_chain_all_valid | True | True | Yes |
| dependency_evidence_reference | True | True | Yes |

### Performance Metrics

- **total_duration_s**: 0.017
- **chained_tasks**: 3
- **execution_order**: ['s4-task-A', 's4-task-B', 's4-task-C']
- **dependencies_satisfied**: 3
- **chain_order_valid**: True
- **dependency_references_found**: True

---

## Summary

| Scenario | Status | Duration (s) | Key Metric |
|----------|--------|-------------|-----------|
| scenario1_50_agents_concurrent | Yes | 0.147 | agents: 50 |
| scenario2_multi_round_economy | Yes | 0.228 | 50 tasks |
| scenario3_malicious_detection | Yes | 0.012 | Detection: 100.0% |
| scenario4_chained_tasks | Yes | 0.017 | Order: s4-task-A, s4-task-B, s4-task-C |

---
_Report generated at 2026-06-07 08:32:23._

# AgentMesh Phase 35C Level 1 — Multi-Company Stress Test Report

- **Date**: 2026-06-08 21:06:10 (Asia/Shanghai)
- **Status**: PASSED
- **Total duration**: 0.03s

---

## Execution Steps

| # | Step | Elapsed (s) | OK | Detail |
|---|------|------------|----|--------|
| 1 | service_init | 0.010 | Yes |  |
| 2 | register_companies | 0.011 | Yes | A=1e43210827fb, B=a0b59afd20ec |
| 3 | issue_shares | 0.000 | Yes | A(1000) B(500) |
| 4 | equity_transfer | 0.001 | Yes | A_holds_in_B=100, B_owns=400, total=500 |
| 5 | create_escrow | 0.000 | Yes | task=stress-mc-task-001, amount=500 |
| 6 | dividend_distribution | 0.000 | Yes | fund=fbe31e1dc931., A_dividend=40, B_dividend=160 |
| 7 | verification | 0.000 | Yes | 9 assertions |

## Assertion Results

| Check | Expected | Actual | Passed |
|-------|----------|--------|--------|
| a_escrow_balance | 1540 | 1540 | Yes |
| b_escrow_balance | 1160 | 1160 | Yes |
| equity_a_in_b | 100 | 100 | Yes |
| equity_b_in_b | 400 | 400 | Yes |
| total_equity_b | 500 | 500 | Yes |
| equity_ledger_balance | 500 | 500 | Yes |
| balance_sheet_identity | sum(equity)=total_outstanding | A=100, B=400, total=500 | Yes |
| dividend_a_correct | 40 | 40 | Yes |
| dividend_b_correct | 160 | 160 | Yes |

## Performance Metrics

- **total_duration_s**: 0.023
- **company_a_id**: 1e43210827fb4ea6
- **company_b_id**: a0b59afd20ec41ca
- **agent_a_id**: fdf7327df5c545fb
- **agent_b_id**: cfee678c3be74c57
- **a_equity_in_a**: 1000
- **a_equity_in_b**: 100
- **b_equity_in_b**: 400
- **total_equity_b**: 500
- **a_escrow_final**: 1540
- **b_escrow_final**: 1160
- **b_company_escrow_final**: 1200
- **a_dividend_received**: 40
- **b_dividend_received**: 160
- **a_expected_escrow**: 1540
- **b_expected_escrow**: 1160

## Balance Sheet Verification

### B Ltd (Company B)

```
Assets:
  Escrow balance: 1160

Liabilities:
  0 (all escrow released)

Equity:
  Agent A (shareholder): 100 shares
  Agent B (founder):     400 shares
  Total outstanding:     500 shares

Balance sheet identity: Σ(Assets) = Σ(Liabilities) + Σ(Equity)
  Equity sum: 500 = Total outstanding: 500 => CONSISTENT
```

### Agent A

```
  A Inc shares held: 1000
  B Ltd shares held: 100
  Escrow balance: 1540
  Expected: 1540
  Dividend received: 40
```

### Agent B

```
  B Ltd shares held: 400
  Escrow balance: 1160
  Expected: 1160
  Dividend received: 160
```

---
_Report generated at 2026-06-08 21:06:10._


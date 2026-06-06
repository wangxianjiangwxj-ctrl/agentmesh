# AgentMesh Demo Guide

## Quick Start

```bash
./demo/run.sh full
```

This runs the complete end-to-end workflow:
1. Register two agents (Alice & Bob)
2. Escrow hold (Alice locks 300 points)
3. Evidence chain (5 signed entries)
4. Escrow release (30:70 split)
5. Reputation (mutual review, Bayesian scoring)

## What It Demonstrates

| Step | Module | Action |
|------|--------|--------|
| 1 | Identity | Agent registration + DID generation |
| 2 | Escrow | Deposit, hold, frozen balance |
| 3 | Evidence Chain | Publish, assign, deliver, verify — all dual-signed |
| 4 | Escrow | Release with configurable split ratio |
| 5 | Reputation | Mutual review + Bayesian reputation scoring |

## Requirements

- Python 3.10+
- No network required

## Running Manually

```bash
python demo/demo_workflow.py
```

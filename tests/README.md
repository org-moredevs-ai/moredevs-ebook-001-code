# tests/

End-to-end integration tests, one per recipe-tier.

| File | Tier | Purpose |
|---|---|---|
| `test_r1_n1_e2e.py` | R1 N1 | MQTT → TimescaleDB → Grafana data populated |
| `test_r1_n2_e2e.py` | R1 N2 | Modbus + OPC-UA collectors → alerts fire |
| `test_r2_n1_e2e.py` | R2 N1 | FFT alert triggers above threshold |
| ... | ... | One file per recipe-tier |

Run with: `make test-integration` (requires `make up`).

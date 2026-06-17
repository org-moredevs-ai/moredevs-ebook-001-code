# Receita 5 — Nível 1 (DIY)

> Companion code para o Capítulo 5 do ebook *Fábrica Inteligente: Receitas de IA*.

Escalonamento *job-shop* por **regra de despacho** (EDD — a data prometida mais
próxima primeiro). Modela a fábrica como encomendas que passam por máquinas, em
sequências e tempos conhecidos, e calcula as datas de saída previstas e os
atrasos — antes de eles acontecerem.

EN: Job-shop scheduling via a **dispatching rule** (EDD). Models the factory as
orders flowing through machines and computes predicted ship dates and lateness.

## Componentes

| Ficheiro | Função |
|---|---|
| `lib_comum/scheduling.py` | `schedule_dispatch` (regra EDD/SPT/FIFO), `total_tardiness`, dados de demo. |
| `app.py` | Interface Streamlit (Gantt + atrasos + "what-if"). |

## Correr

```bash
make demo-r5        # abre a interface em http://localhost:8501
```

O Nível 2 (optimizador CP-SAT e "se aceitar isto, o que atrasa?") está em
`lib_comum/scheduling_cpsat.py` e no separador "Optimizado" da interface.

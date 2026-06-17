# Receita 5 — Nível 2 (Pro)

> Companion code para o Capítulo 5 do ebook *Fábrica Inteligente: Receitas de IA*.

Escalonamento *job-shop* **optimizado** com OR-Tools CP-SAT, e a pergunta que
vale dinheiro: **"se aceitar esta encomenda, o que atrasa?"**.

EN: **Optimised** job-shop scheduling with OR-Tools CP-SAT, plus the money
question: **"if I accept this order, what slips?"**.

## Componentes

| Ficheiro | Função |
|---|---|
| `lib_comum/scheduling_cpsat.py` | `schedule_cpsat` (minimiza atraso total, depois conclusão total) e `what_if_accept` (impacto de aceitar uma encomenda). |
| `../nivel-1-diy/app.py` | Separador "Optimizado (Nível 2)" com Gantt e "what-if". |

## Correr

```bash
make demo-r5        # interface — abra o separador "Optimizado (Nível 2)"
```

## Notas

- O objectivo é **lexicográfico**: primeiro minimiza a soma dos atrasos, depois
  faz cada encomenda sair o mais cedo possível. Sem o segundo termo, o optimizador
  baralharia planos com o mesmo atraso e o "what-if" reportaria deslizes falsos.
- `what_if_accept` optimiza com e sem a encomenda nova e compara as datas de
  saída de cada encomenda existente — transformando "conseguimos?" numa resposta
  com dados.
- O solver corre com `num_search_workers = 1` (determinístico e portável). Em
  produção, com problemas grandes, pode aumentar-se para acelerar.

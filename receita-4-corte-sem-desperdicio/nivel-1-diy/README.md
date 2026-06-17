# Receita 4 — Nível 1 (DIY)

> Companion code para o Capítulo 4 do ebook *Fábrica Inteligente: Receitas de IA*.

Encaixe de peças **rectangulares** numa ou mais folhas (MDF, vidro, chapa) com a
biblioteca `rectpack`, com largura de corte (*kerf*) e medição de aproveitamento,
e um visualizador SVG.

EN: Rectangular nesting into one or more sheets with `rectpack`, cut width
(*kerf*) and utilisation measurement, plus an SVG viewer.

## Componentes

| Ficheiro | Função |
|---|---|
| `lib_comum/nesting.py` | Motor de encaixe rectangular (`pack_rectangles`, `utilisation`). |
| `svg_render.py` | Desenha o layout em SVG (rectangular e irregular). |
| `app.py` | Interface Streamlit (separadores rectangular e irregular). |

## Correr

```bash
make demo-r4        # abre a interface em http://localhost:8501
```

Ajuste o *kerf* e a rotação e veja o aproveitamento mudar em tempo real.
O encaixe **irregular** (com grão e zonas de defeito) está no separador Nível 2
e em `lib_comum/nesting_irregular.py`.

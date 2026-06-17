# Receita 4 — Nível 2 (Pro)

> Companion code para o Capítulo 4 do ebook *Fábrica Inteligente: Receitas de IA*.

Encaixe de peças **irregulares** (pele, tecido) respeitando o **grão** (apenas
certas rotações permitidas) e evitando **zonas de defeito**. Usa uma variante por
rasterização do *bottom-left*: discretiza a folha numa grelha, infla cada peça
por *spacing* (com `pyclipper`) e coloca-a na posição mais baixa e mais à esquerda
onde cabe sem chocar com outra peça nem com um defeito.

EN: Irregular nesting (leather, fabric) honouring the **grain** (only certain
rotations) and avoiding **defect zones**, via a bottom-left raster placement that
inflates each piece by *spacing* (`pyclipper`).

## Componentes

| Ficheiro | Função |
|---|---|
| `lib_comum/nesting_irregular.py` | `place_irregular` — encaixe irregular com grão e defeitos. |
| `../nivel-1-diy/svg_render.py` | `irregular_svg_string` — desenha o layout irregular. |
| `../nivel-1-diy/app.py` | Separador "Irregular (Nível 2)" da interface. |

## Correr

```bash
make demo-r4        # interface — abra o separador "Irregular (Nível 2)"
```

## Notas

- As `allowed_angles` codificam o grão: `(0, 180)` para um material com sentido,
  ângulos livres para um material isotrópico.
- As `defects` são polígonos a evitar (cicatrizes na pele, zonas oxidadas na
  chapa). No Nível 3, uma câmara detecta-os automaticamente.
- As peças maiores são colocadas primeiro — heurística simples e eficaz, porque
  as pequenas preenchem os interstícios.

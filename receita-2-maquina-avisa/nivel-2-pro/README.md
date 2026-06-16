# Receita 2 — Nível 2 (Pro)

> Vibração contínua + Isolation Forest + alertas multi-canal.

🇵🇹 PT (este ficheiro) · [🇬🇧 EN](README.en.md)

## O que muda em relação ao Nível 1

| Aspecto | Nível 1 (DIY) | Nível 2 (Pro) |
|---|---|---|
| Detector | Banda BPFO + baseline fixo | **Isolation Forest** em 21 features (7 × 3 eixos) por máquina |
| Robustez | Reage a uma única banda; vulnerável a ruído | Aprende a "forma" da máquina saudável; detecta combinações anómalas |
| Alertas | Log apenas | Apprise: Telegram, email, Slack, MS Teams (via `APPRISE_URLS`) |
| Falsos positivos | Baixos (mínimo absoluto evita ruído em quietas) | Muito baixos: a prensa-1 domina 50× sobre máquinas saudáveis |
| Adaptação | Re-calibração manual após manutenção | Idem (modelo congelado por design) |

A receita não substitui a Nível 1 — coexistem. A N1 dá uma primeira linha de detecção barata e simples; a N2 adiciona inteligência por cima. Em produção, normalmente correm em paralelo e os alertas correlacionam-se.

## Componentes

| Pasta / módulo | Função |
|---|---|
| [`feature_extractor/extractor.py`](feature_extractor/extractor.py) | Subscreve raw vibration, calcula 7 features por eixo (RMS, peak, crest, kurtosis, dom. freq., banda 1×, banda BPFO), persiste em `vibration_features`, republica em `fabrica/<line>/<machine>/vibration-features`. |
| [`isoforest_detector/detector.py`](isoforest_detector/detector.py) | Subscreve features, treina IsolationForest por máquina, congela o modelo após warmup, persiste alertas. |
| [`grafana-dashboards/`](grafana-dashboards/) | Dashboard "Receita 2 N2 — Anomalia (Isolation Forest)". |

Acrescentado a `lib_comum`:

- [`lib_comum/alerting.py`](../../lib_comum/alerting.py) — wrapper Apprise.
- [`lib_comum/sql/init/05_vibration_features.sql`](../../lib_comum/sql/init/05_vibration_features.sql) — hypertable `vibration_features` (10 colunas + `anomaly_score`).
- [`lib_comum/db.py`](../../lib_comum/db.py) — `VibrationFeatureRow` e `insert_vibration_features`.

## Demo em <2 minutos (sem hardware)

```bash
make up                  # stack base
make seed-data           # alimentar + moldes
make demo-r2-n2          # simulator + extractor + detector, ~75 segundos
# → abre http://localhost:3000
# → dashboard "Receita 2 N2 — Anomalia (Isolation Forest)"
```

O `demo-r2-n2` reproduz **10 dias simulados** começando 4 dias antes da janela de wear da prensa-1. O detector congela o modelo durante os primeiros ~20 snapshots (que apanham o estado saudável da prensa) e depois pontua cada novo vector. À medida que a chumaceira se degrada, o score da prensa cai para -0.10/-0.14 enquanto as outras 5 máquinas mantêm-se acima de -0.07. Tipicamente, a prensa dispara >600 alertas warning vs <13 nas máquinas saudáveis.

## Arquitectura

```
[ESP32+ADXL345]
      ▼ MQTT (raw vibration)
      ┌─────────────────┐
      │ Feature         │  → TimescaleDB (vibration_features)
      │ Extractor       │
      └────────┬────────┘
               ▼ MQTT (vibration-features)
      ┌─────────────────┐
      │ Isolation       │  → TimescaleDB (vibration_alerts band='anomaly')
      │ Forest          │  → Apprise (Telegram / email / Teams)
      └─────────────────┘
```

A separação `Extractor` ↔ `Detector` permite escalar verticalmente (mais máquinas = mais extractors no mesmo broker) e horizontalmente (vários algoritmos em paralelo a consumir as mesmas features — IF, autoencoder, SVM).

## Feature vector (por máquina × eixo)

```
[ rms_g, peak_g, crest_factor, kurtosis,
  dominant_freq_hz, band_rotation_1x_g, band_bpfo_g ]
```

3 eixos × 7 features = **21 dimensões por máquina**. A IsolationForest treina sobre este espaço.

## Modelo IsolationForest

Por máquina:

- `n_estimators=80`, `contamination=0.05`, `random_state` fixo para reprodutibilidade.
- Warmup: acumula `--warmup-window` snapshots saudáveis, treina **uma vez** e congela.
- Re-fit online está **desactivado por defeito** (`--refit-every 0`). Re-treinar continuamente faria com que a deriva lenta de uma chumaceira em wear fosse absorvida como o "novo normal" — exactamente o oposto do que queremos.
- Para re-treinar após manutenção: parar o detector, limpar o estado em memória (reiniciar) ou passar `--refit-every N` quando se tem certeza de saúde mecânica.

## Alertas multi-canal

Configuração via env:

```bash
export APPRISE_URLS="tgram://BOT_TOKEN/CHAT_ID,mailto://smtp.example.com?to=director@fabrica.pt"
```

`lib_comum.alerting.AlertSender` cuida do dispatch. Quando `APPRISE_URLS` não está definido (caso da demo), o alerta vai só para log — mas continua a ser persistido em `vibration_alerts`.

## Limites do Nível 2

- IsolationForest é não-supervisionado, sem rótulos. Para classificar a falha (BPFO vs BPFI vs FTF vs BSF) ou estimar RUL, salta para **Nível 3** (autoencoder + supervisão).
- O modelo é per-máquina. Frotas grandes (50+) beneficiam de modelos partilhados por família — também N3.
- Sem retraining automático "consciente" (precisa de confirmar fim de manutenção a partir de um sistema externo).

Voltar à [Receita 2](../README.md).

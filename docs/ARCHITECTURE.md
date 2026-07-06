# Arquitetura — WFM Segurança Patrimonial

Sistema de Gestão de Força de Trabalho para segurança patrimonial, focado em
**garantir que o funcionário está no local certo, é quem diz ser e permanece
ativo** — combatendo fraude de ponto.

> **Fase atual:** Backend + Webapp PoC. O app nativo (Flutter/APK) é a Fase 2,
> necessária para as garantias anti-fraude fortes (ver "Limitações do webapp").

---

## 1. Visão geral

```
┌─────────────────┐        HTTPS/JWT        ┌──────────────────────────┐
│  Cliente         │ ─────────────────────▶ │  Backend  (FastAPI)      │
│                  │                         │                          │
│  Fase 1: Webapp  │   check-in (GPS+selfie) │  ┌────────────────────┐  │
│  (este repo)     │   deadman ack           │  │ Pipeline validação │  │
│                  │   panic / telemetria    │  │ 1 anti-mock        │  │
│  Fase 2: Flutter │◀──── webhook / push ────│  │ 2 geofence         │  │
│  (APK nativo)    │                         │  │ 3 plausibilidade   │  │
└─────────────────┘                         │  │ 4 liveness+face    │  │
                                             │  └────────────────────┘  │
                                             │  Scheduler homem-morto   │
                                             └───────────┬──────────────┘
                                                         │
                        ┌────────────────────────────────┼───────────────┐
                        ▼                ▼                ▼               ▼
                 PostgreSQL+PostGIS    Redis         Webhook Central   AWS Rekognition
                 (dados/geofence)   (filas/deadman)  (pânico/deadman)  (liveness/face)
```

### Princípio central: **o servidor é a fonte da verdade**
O cliente é sempre tratado como não-confiável. Ele só coleta e envia sinais; o
backend **recalcula** distância ao geofence, valida plausibilidade de
deslocamento, verifica liveness/rosto e — crucialmente — é quem detecta a
ausência de resposta no homem-morto. Nada de segurança é decidido no dispositivo.

---

## 2. Stack

| Camada | Tecnologia | Motivo |
|---|---|---|
| Mobile (Fase 2) | **Flutter** | Foreground service, integração nativa (mock/root, background) |
| Webapp (Fase 1) | HTML/JS PWA (`/webapp`) | Roda hoje, deploy simples; consome a mesma API |
| Backend | **FastAPI (Python 3.11+)** | Async, tipado, OpenAPI automático |
| Banco | **PostgreSQL + PostGIS** | Geofencing real (`ST_DWithin`) e índices GIST |
| Filas/agendamento | **Redis + Celery** (prod) / APScheduler (PoC) | Timeout do homem-morto, sync, webhooks |
| Biometria | **AWS Rekognition Face Liveness** (sa-east-1) | Liveness gerenciado; não construir do zero |
| Attestation (Fase 2) | Play Integrity / App Attest | Anti-emulador/fake device |

---

## 3. Modelo de dados

Ver `backend/app/models/models.py`. Entidades principais:

- **User** — funcionário/operador/admin. Guarda `face_embedding` (vetor), **não a foto**. Campos de consentimento LGPD.
- **Site** — posto pré-cadastrado: `latitude`, `longitude`, `radius_m` (o "raio X").
- **Shift** — turno; `active` dispara o ciclo do homem-morto.
- **CheckEvent** — cada tentativa de ponto com evidências: GPS, distância, flags de mock/root, scores de liveness/match, status (approved/rejected/pending_review).
- **DeadManChallenge** — desafio periódico; `scheduled_at`, `deadline_at`, `status`, `webhook_fired`.
- **PanicAlert**, **Telemetry** — pânico e telemetria de bateria/rede.

---

## 4. As 4 funcionalidades essenciais

### 4.1 Controle geográfico (geofencing + anti-fake GPS)
- Cliente envia `lat/lon/accuracy` + sinais (`is_mock_location`, `is_rooted`).
- Servidor **recalcula** distância (Haversine no PoC; `ST_DWithin` no PostGIS) e rejeita se `> radius_m`.
- **Anti-fake GPS em camadas** (a defesa não é só o flag do cliente):
  1. `is_mock_location` (nativo: `Location.isFromMockProvider` / plugin `safe_device`).
  2. **Attestation** (Play Integrity / App Attest) — prova device/app legítimo.
  3. **Plausibilidade server-side**: velocidade implícita entre dois check-ins; "teletransporte" = rejeitado. *É a defesa que funciona mesmo no navegador.*

### 4.2 Reconhecimento facial + liveness
- Selfie no check-in/out → `LivenessProvider.verify()`.
- Produção: AWS Rekognition — `create_face_liveness_session` (cliente conduz o desafio via SDK Amplify) → `get_face_liveness_session_results` (Confidence) → `compare_faces` (Similarity).
- Thresholds configuráveis (`LIVENESS_THRESHOLD`, `FACE_MATCH_THRESHOLD`).
- **LGPD:** a selfie do check-in **não é persistida** — guardamos só os scores.

### 4.3 Sensor de homem-morto (check-in periódico)
- Ao iniciar turno, agenda-se um `DeadManChallenge` a cada **30 min ± jitter aleatório** (evita virar hábito).
- App recebe push/notificação e tem uma **janela (ex.: 2 min)** para dar `ack`.
- O **scheduler no servidor** (`_sweep`) marca como `missed` e **dispara o webhook** se não houver ack — independente do app estar vivo. Ver `services/deadman.py`.

### 4.4 Retaguarda
- **Offline**: app guarda check-ins criptografados (SQLCipher) e reenvia em `/api/sync/offline`; o servidor **revalida** cada um (não confia no que foi aprovado offline).
- **Pânico**: `/api/panic` grava e dispara webhook imediato com geolocalização.
- **Telemetria**: `/api/telemetry` recebe bateria/rede periodicamente.

---

## 5. ⚠️ Limitações do webapp (por que a Fase 2 nativa importa)

| Recurso | Webapp (navegador) | App nativo (Flutter) |
|---|---|---|
| Detecção de Fake GPS (mock) | ❌ Impossível no browser | ✅ `isFromMockProvider` + attestation |
| Homem-morto em background | ⚠️ Limitado (SW+Push; iOS mata) | ✅ Foreground service + push |
| Attestation de device | ❌ | ✅ Play Integrity / App Attest |
| Câmera/selfie/liveness | ✅ `getUserMedia` | ✅ |
| GPS/geofence | ✅ (sem detectar spoof) | ✅ |

Mitigação na Fase 1: a **validação de plausibilidade server-side** pega boa
parte da fraude de GPS mesmo sem o flag de mock.

---

## 6. Conformidade (LGPD) — não é opcional

- **Biometria = dado sensível** (Art. 5, II): base legal específica, consentimento destacado, **RIPD**.
- **Minimização**: não armazenar selfies; guardar apenas embedding base + scores.
- **Monitoramento de trabalhador** (geolocalização contínua + homem-morto): implicações trabalhistas — validar com jurídico.
- Trilha de consentimento versionada por usuário (`consent_version`, `consent_granted_at`).
- Criptografia em trânsito (TLS) e em repouso; segregar dados biométricos.

*Não constitui aconselhamento jurídico — validar com o DPO/jurídico de vocês.*

---

## 7. Deploy (VPS Hostinger)

FastAPI **exige VPS** (não roda em hospedagem compartilhada PHP/MySQL). Ver `README.md`.

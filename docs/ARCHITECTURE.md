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

### 4.0 Camadas anti-fraude no webapp (defense-in-depth)
Como o navegador não detecta Fake GPS nem impede injeção de câmera, a defesa é
empilhar camadas baratas e **decidir tudo no servidor**:

| # | Camada | Onde |
|---|---|---|
| 1 | Servidor é a verdade (recalcula geofence, valida liveness, timing) | ✅ |
| 2 | Selfie só capturada na sessão (sem upload de arquivo) | webapp |
| 3 | Desafio de movimento aleatório + nonce de uso único | `face_liveness.py` |
| 4 | Gate de qualidade do GPS (precisão + frescor do fix) | `checkin.py` |
| 5 | Cruzamento GPS × IP (divergência grosseira → rejeita/flag) | `geoip.py` |
| 8 | Janela de turno (check-in só dentro da escala) | `checkin.py` + `shifts.py` |
| 9 | Anomalia: 1 check-in ativo por vez | `checkin.py` |
| — | Auditoria total (aprovados e rejeitados com scores + IP) | `CheckEvent` |

Teto: nada disso para injeção de câmera/deepfake — só **app nativo +
attestation (Fase 2)**. No webapp, o objetivo é tornar a fraude cara e detectável.

### 4.1 Controle geográfico (geofencing + anti-fake GPS)
- Cliente envia `lat/lon/accuracy` + sinais (`is_mock_location`, `is_rooted`).
- Servidor **recalcula** distância (Haversine no PoC; `ST_DWithin` no PostGIS) e rejeita se `> radius_m`.
- **Anti-fake GPS em camadas** (a defesa não é só o flag do cliente):
  1. `is_mock_location` (nativo: `Location.isFromMockProvider` / plugin `safe_device`).
  2. **Attestation** (Play Integrity / App Attest) — prova device/app legítimo.
  3. **Plausibilidade server-side**: velocidade implícita entre dois check-ins; "teletransporte" = rejeitado. *É a defesa que funciona mesmo no navegador.*

### 4.2 Reconhecimento facial + liveness
- Selfie no check-in/out → `LivenessProvider.verify(selfie, cpf=..., base_embedding=...)`.
- Provedores de **match** plugáveis por `LIVENESS_PROVIDER` (nenhuma rota muda):
  - `stub` — PoC.
  - `deepface` — **matcher self-hosted** (ArcFace) + anti-spoofing passivo. Custo R$0/consulta, dado no BR. Requer `pip install deepface`.
  - `serpro_datavalid` — **valida contra a base oficial do governo** (Senatran) por CPF; o fluxo `v4/pf-facial` já contempla prova de vida na captura. Ver `services/datavalid.py`.
  - `aws_rekognition` — liveness gerenciado (⚠️ não roda em sa-east-1; dado sai do BR).

**Liveness ATIVA por desafio de movimento** (`services/face_liveness.py`): o
servidor emite um desafio com sequência aleatória de ações (piscar/virar/sorrir)
e um `nonce` de uso único; o webapp usa **MediaPipe FaceLandmarker** para medir
os movimentos e envia as métricas; o **servidor valida** (não confia num "fiz
sim" do cliente). Defesa em camadas recomendada, dentro do orçamento: liveness
passiva (DeepFace) + ativa (desafio) + contexto server-side, escalando para
Datavalid só em check-ins de risco. Garantia forte contra injeção de câmera/
deepfake exige o app nativo com attestation (Fase 2).
- Thresholds configuráveis (`LIVENESS_THRESHOLD`, `FACE_MATCH_THRESHOLD`).
- **LGPD:** a selfie do check-in **não é persistida** — guardamos só os scores.

#### Estratégia de custo com Datavalid (recomendada)
Datavalid é cobrado **por consulta** — usar em todo ponto diário (ex.: 300
pessoas × 2/dia ≈ 15,6 mil/mês) fica caro. Separe as camadas:

1. **Onboarding (1× por pessoa):** `serpro_datavalid` valida o rosto contra a
   base oficial → prova forte de "é quem diz ser". ~300 consultas únicas (cabe
   no tier gratuito). Guarde o resultado/embedding aprovado.
2. **Check-in diário:** faça match contra a referência aprovada no onboarding
   (matcher barato/self-hosted) + prova de vida; use Datavalid de novo só em
   **check-ins de risco** ou revalidação periódica.

**Auth Datavalid:** OAuth2 `client_credentials` em `/token` (Basic com Consumer
Key/Secret; Bearer válido ~1h, com cache no cliente). Resposta da validação é um
**JWS** com `face_similaridade`. Em produção, **verifique a assinatura** do JWS
com a chave pública do Serpro.

### 4.3 Sensor de homem-morto (check-in periódico)
- Ao iniciar turno, agenda-se um `DeadManChallenge` a cada **30 min ± jitter aleatório** (evita virar hábito).
- App recebe push/notificação e tem uma **janela (ex.: 2 min)** para dar `ack`.
- O **scheduler no servidor** (`_sweep`) marca como `missed` e **dispara o webhook** se não houver ack — independente do app estar vivo. Ver `services/deadman.py`.

### 4.3b Painel da central (`/panel`)
Dashboard operador/admin (RBAC via `require_operator`) que consome `/api/admin/*`:
- **KPIs**: turnos ativos, pânicos abertos, homem-morto perdido, check-ins 24h.
- **Mapa** (Leaflet + OpenStreetMap): postos com círculos de geofence + marcadores de check-in (verde/vermelho).
- **Alertas em tempo real**: pânico e homem-morto perdido, com polling em `/api/admin/live` (WebSocket é evolução futura); botão de resolver pânico.
- **Feed de eventos** de ponto (aprovados/rejeitados com scores/motivo/IP) e **cadastro** de posto/turno.

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

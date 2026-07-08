# WFM — Segurança Patrimonial (Workforce Management)

Gestão de Força de Trabalho para segurança patrimonial e controle de operações
de campo. Objetivo: **garantir que o funcionário está no local certo, é quem diz
ser e permanece ativo durante o turno**, combatendo fraude de ponto.

> **Fase 1 (este repo):** Backend FastAPI + Webapp PoC funcionando de ponta a
> ponta. O app nativo (Flutter/APK) é a Fase 2 — necessário para as garantias
> anti-fraude fortes (detecção de Fake GPS, homem-morto em background,
> attestation). Ver [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Funcionalidades (todas testadas no PoC)

1. **Controle geográfico** — geofence recalculado no servidor + anti-fake GPS em camadas (flag de mock, plausibilidade de deslocamento).
2. **Reconhecimento facial + liveness** — matcher plugável (`stub` / `deepface` self-hosted / `serpro_datavalid` / `aws_rekognition`) **+ liveness ativa por desafio de movimento** (piscar/virar/sorrir) validada no servidor via MediaPipe. Selfies **não são armazenadas** (LGPD).
3. **Sensor de homem-morto** — desafios a cada 30 min ± jitter; o **servidor** detecta ausência de resposta e dispara webhook à central.
4. **Retaguarda** — sync offline revalidado, botão de pânico, telemetria de bateria/rede.

## Estrutura

```
backend/          API FastAPI
  app/
    core/         config, segurança (JWT/bcrypt)
    db/           sessão SQLAlchemy
    models/       modelos de dados
    schemas/      Pydantic (I/O)
    services/     geofencing, liveness, deepface, datavalid, deadman,
                  face_liveness (desafio), geoip, webhook
    api/routes/   auth, sites, shifts, checkin, deadman, panic, telemetry,
                  sync, admin (painel)
  seed.py         dados de exemplo
  test_*.py       datavalid, antifraude, e2e (webapp) e panel (Playwright)
webapp/           app do funcionário (mobile-first PWA): login + GPS + selfie
                  + desafio de movimento + check-in + pânico + homem-morto
panel/            painel da central: mapa (Leaflet), KPIs, alertas em tempo
                  real (pânico/homem-morto), eventos, cadastro de posto/turno
docs/             arquitetura
```

- **App do funcionário:** `http://localhost:8000/app/`  (login `guarda@wfm.local` / `senha123`)
- **Painel da central:** `http://localhost:8000/panel/`  (login `operador@wfm.local` / `senha123`)

## Rodar localmente (PoC)

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # ajuste SECRET_KEY

python seed.py                  # cria usuários e 1 posto de exemplo
uvicorn app.main:app --reload   # API em http://localhost:8000  (docs em /docs)
```

Servir o webapp (mesma origem, evita CORS): abra **http://localhost:8000/app/**
> A câmera (`getUserMedia`) exige **HTTPS** ou `localhost`. Em produção use TLS.

**Credenciais do seed:** `guarda@wfm.local` / `senha123` (funcionário) ·
`operador@wfm.local` / `senha123` (central).

### Testar o check-in por linha de comando
```bash
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login \
  -d "username=guarda@wfm.local&password=senha123" | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# Dentro do raio -> approved
curl -s -X POST localhost:8000/api/checkin -H "Authorization: Bearer $TOKEN" \
  -F site_id=1 -F type=checkin -F latitude=-23.561414 -F longitude=-46.655881 \
  -F selfie=@qualquer_imagem.jpg
```

### Testes automatizados
```bash
python test_datavalid.py     # adaptador Serpro Datavalid (HTTP simulado)
python test_antifraud.py     # cruzamento GPS x IP (#5)
pip install playwright       # E2E de navegador (usa o Chromium do ambiente)
BASE_URL=http://localhost:8000 python test_e2e.py        # app do funcionário
BASE_URL=http://localhost:8000 python test_panel_e2e.py  # painel da central
```

### Testar o homem-morto rápido
Rode com janelas curtas e um webhook local:
```bash
python3 -c "from http.server import *;import sys;
h=type('H',(BaseHTTPRequestHandler,),{'do_POST':lambda s:(print(s.rfile.read(int(s.headers['content-length']))),s.send_response(200),s.end_headers())});
HTTPServer(('127.0.0.1',9000),h).serve_forever()" &

DEADMAN_INTERVAL_MINUTES=1 DEADMAN_RESPONSE_WINDOW_SECONDS=15 \
CENTRAL_WEBHOOK_URL=http://127.0.0.1:9000 uvicorn app.main:app
# Faça um check-in e NÃO dê ack: ~90s depois o webhook 'deadman_missed' chega.
```

## Deploy em produção (VPS Hostinger)

FastAPI **não roda em hospedagem compartilhada** (PHP/MySQL). Use um **VPS**:

1. **Banco**: PostgreSQL + PostGIS. Ajuste `DATABASE_URL` e descomente
   `psycopg2-binary`/`geoalchemy2` em `requirements.txt`; troque o Haversine por
   `ST_DWithin` (ver comentários em `services/geofencing.py`).
2. **App**: `gunicorn -k uvicorn.workers.UvicornWorker app.main:app` atrás de
   **nginx** (TLS via Let's Encrypt) como serviço `systemd`.
3. **Homem-morto em escala/HA**: troque APScheduler por **Celery + Redis**
   (beat para o sweep) — evita depender de um único processo.
4. **Migrações**: adote **Alembic** (o PoC usa `create_all`).
5. **Segredos**: `SECRET_KEY` forte (`openssl rand -hex 32`), credenciais AWS
   para o Rekognition. Nunca versione `.env`.

## Roadmap — Fase 2 (app nativo Flutter)

Pacotes recomendados:
- Geofencing/GPS: `geolocator`, `flutter_background_geolocation`
- Câmera/face: `camera`, `google_mlkit_face_detection`, Amplify (Rekognition Liveness)
- Background/homem-morto: `flutter_foreground_task`, `flutter_local_notifications` + FCM
- Offline criptografado: `sqflite_sqlcipher`, `flutter_secure_storage`
- Anti-fraude: `safe_device` (mock/root) + Play Integrity / App Attest

## Status do projeto

**Pronto e testado (Fase 1 — webapp):**
- ✅ Geofencing server-side + anti-fake-GPS em camadas (mock, plausibilidade, GPS×IP, gate de qualidade)
- ✅ Reconhecimento facial plugável (stub / DeepFace self-hosted / Serpro Datavalid / AWS) + **liveness ativa por desafio de movimento** (validada no servidor)
- ✅ Sensor de homem-morto (30 min ± jitter) com webhook disparado pelo servidor
- ✅ Retaguarda: sync offline (revalidado), botão de pânico, telemetria
- ✅ Janela de turno + anomalia (1 check-in ativo por vez) + auditoria com IP
- ✅ **App do funcionário** mobile-first (PWA) e **painel da central** (mapa + alertas em tempo real)
- ✅ Testes: unitários (Datavalid, anti-fraude) e E2E de navegador (app + painel via Playwright)

**Fase 2 (app nativo Flutter/APK) — para garantias fortes:**
- ⏭️ Attestation (Play Integrity / App Attest) contra injeção de câmera/deepfake
- ⏭️ Detecção nativa de Mock Location e background confiável do homem-morto
- ⏭️ Fila offline **criptografada** no dispositivo (o backend `/api/sync/offline` já está pronto)

## Conformidade

Biometria e geolocalização contínua são **dados sensíveis/monitoramento** sob a
LGPD. Requer consentimento destacado, RIPD e validação trabalhista. Ver seção 6
de [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Não constitui aconselhamento jurídico.

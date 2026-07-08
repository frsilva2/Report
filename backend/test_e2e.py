"""E2E do webapp com Playwright (Chromium do ambiente).

Dirige o app mobile-first servido em /app: login, GPS (falso via Playwright),
câmera (fake device do Chromium), check-in aprovado e pânico. Tira screenshots.

Requisitos: backend rodando com REQUIRE_LIVENESS_CHALLENGE=false (o MediaPipe
do desafio precisa de CDN/navegador real; a liveness ativa é testada à parte).

Uso: BASE_URL=http://localhost:8009 python test_e2e.py
"""
import os
import pathlib

from playwright.sync_api import sync_playwright

BASE = os.environ.get("BASE_URL", "http://localhost:8009")
SHOTS = pathlib.Path(os.environ.get("SHOTS_DIR", "/tmp/shots"))
SHOTS.mkdir(parents=True, exist_ok=True)
SITE = {"latitude": -23.561414, "longitude": -46.655881, "accuracy": 8}
# Usa o Chromium já instalado no ambiente (evita 'playwright install').
CHROME = os.environ.get("CHROME_PATH", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, args=[
            "--use-fake-device-for-media-stream",   # câmera sintética
            "--use-fake-ui-for-media-stream",        # auto-permite a câmera
            "--no-sandbox",
        ])
        ctx = browser.new_context(
            viewport={"width": 390, "height": 844},   # iPhone 12/13 mobile-first
            device_scale_factor=3,
            permissions=["geolocation", "camera"],
            geolocation=SITE, locale="pt-BR",
        )
        page = ctx.new_page()
        page.on("console", lambda m: print("  [console]", m.type, m.text))
        page.on("pageerror", lambda e: print("  [pageerror]", e))
        page.goto(f"{BASE}/app/", wait_until="networkidle")
        page.screenshot(path=str(SHOTS / "01-login.png"))

        # Login (valores já preenchidos no PoC)
        page.click("#loginBtn")
        try:
            page.wait_for_selector("#appView:not(.hidden)", timeout=15000)
        except Exception:
            print("  loginMsg:", page.inner_text("#loginMsg"))
            print("  url:", page.url)
            raise
        page.wait_for_timeout(1500)  # câmera/GPS estabilizarem
        page.screenshot(path=str(SHOTS / "02-app.png"))

        # Aceitar o confirm() do pânico automaticamente (só quando usado)
        page.on("dialog", lambda d: d.accept())

        # Check-in
        page.click("#checkinBtn")
        page.wait_for_selector("#result.ok, #result.bad", timeout=20000)
        result_text = page.inner_text("#result")
        page.screenshot(path=str(SHOTS / "03-checkin.png"))
        print("CHECK-IN RESULT:", result_text.replace("\n", " "))
        assert "aprovado" in result_text.lower(), f"esperado aprovado, veio: {result_text}"

        # Pânico
        page.click("#panicBtn")
        page.wait_for_timeout(800)
        panic_text = page.inner_text("#result")
        page.screenshot(path=str(SHOTS / "04-panic.png"))
        print("PANIC RESULT:", panic_text.replace("\n", " "))
        assert "pânico" in panic_text.lower()

        browser.close()
    print("\nE2E OK ✅  screenshots em", SHOTS)


if __name__ == "__main__":
    run()

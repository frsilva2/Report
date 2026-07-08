"""E2E do painel da central com Playwright.

Cria um pânico via API, abre o painel como operador, confirma que o alerta
aparece, resolve pela UI, cadastra um posto e tira screenshots.

Uso: BASE_URL=http://localhost:8012 python test_panel_e2e.py
"""
import os
import pathlib

import httpx
from playwright.sync_api import sync_playwright

BASE = os.environ.get("BASE_URL", "http://localhost:8012")
SHOTS = pathlib.Path(os.environ.get("SHOTS_DIR", "/tmp/shots"))
SHOTS.mkdir(parents=True, exist_ok=True)
CHROME = os.environ.get("CHROME_PATH", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")


def make_panic():
    tok = httpx.post(f"{BASE}/api/auth/login",
                     data={"username": "guarda@wfm.local", "password": "senha123"}).json()["access_token"]
    httpx.post(f"{BASE}/api/panic", headers={"Authorization": f"Bearer {tok}"},
               json={"latitude": -23.5614, "longitude": -46.6558})


def run():
    make_panic()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="pt-BR")
        page = ctx.new_page()
        page.on("pageerror", lambda e: print("  [pageerror]", e))
        page.goto(f"{BASE}/panel/", wait_until="networkidle")
        page.screenshot(path=str(SHOTS / "10-panel-login.png"))

        page.click("#loginBtn")
        page.wait_for_selector("#dashView:not(.hidden)", timeout=15000)
        page.wait_for_selector(".alert.panic", timeout=8000)  # o pânico deve aparecer
        page.wait_for_timeout(800)
        page.screenshot(path=str(SHOTS / "11-panel-dash.png"), full_page=True)
        print("KPIs:", page.inner_text("#kActive"), "/", page.inner_text("#kPanic"), "pânicos")
        assert page.inner_text("#kPanic").strip() != "0", "esperava pânico aberto no KPI"

        # Resolver o pânico pela UI
        page.click(".alert.panic button")
        page.wait_for_timeout(1200)
        assert page.query_selector(".alert.panic") is None, "pânico deveria sumir após resolver"
        print("Pânico resolvido pela UI ✓")

        # Cadastrar um posto
        page.fill("#sName", "Posto Teste E2E")
        page.fill("#sLat", "-23.55")
        page.fill("#sLon", "-46.64")
        page.fill("#sRad", "120")
        page.click("#siteForm button")
        page.wait_for_timeout(800)
        page.screenshot(path=str(SHOTS / "12-panel-after.png"), full_page=True)
        print("Posto cadastrado pela UI ✓")

        browser.close()
    print("\nPANEL E2E OK ✅")


if __name__ == "__main__":
    run()

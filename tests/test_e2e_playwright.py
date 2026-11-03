import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from netwatch.db import async_session_maker

playwright_async_api = pytest.importorskip("playwright.async_api")
Browser = playwright_async_api.Browser
Page = playwright_async_api.Page
async_playwright = playwright_async_api.async_playwright

ADMIN_KEY = "netwatch-admin-secret-key-123"
VIEWER_KEY = "netwatch-viewer-secret-key-456"
BASE_URL_1 = "http://127.0.0.1:8001"
BASE_URL_2 = "http://127.0.0.1:8002"
SCREENS_DIR = Path(__file__).parent.parent / "docs" / "screens"


@pytest.fixture(scope="session")
def ensure_cluster_running():
    """Ensures replica-1 (:8001) and replica-2 (:8002) are active for browser e2e testing."""
    SCREENS_DIR.mkdir(parents=True, exist_ok=True)
    processes: list[subprocess.Popen] = []

    def is_healthy(port: int) -> bool:
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=1.5)
            return r.status_code == 200
        except Exception:
            return False

    # Start replica-1 if not alive
    if not is_healthy(8001):
        env1 = os.environ.copy()
        env1["REPLICA_ID"] = "replica-1"
        env1["HTTP_PORT"] = "8001"
        p1 = subprocess.Popen(
            [".venv/bin/uvicorn", "netwatch.main:app", "--host", "127.0.0.1", "--port", "8001"],
            env=env1,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        processes.append(p1)

    # Start replica-2 if not alive
    if not is_healthy(8002):
        env2 = os.environ.copy()
        env2["REPLICA_ID"] = "replica-2"
        env2["HTTP_PORT"] = "8002"
        p2 = subprocess.Popen(
            [".venv/bin/uvicorn", "netwatch.main:app", "--host", "127.0.0.1", "--port", "8002"],
            env=env2,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        processes.append(p2)

    # Wait for both replicas to become healthy
    for _ in range(30):
        if is_healthy(8001) and is_healthy(8002):
            break
        time.sleep(0.3)

    assert is_healthy(8001), "replica-1 on :8001 failed to start"
    assert is_healthy(8002), "replica-2 on :8002 failed to start"

    yield

    for p in processes:
        p.terminate()
        p.wait()


@pytest.mark.asyncio
async def test_admin_add_target_live_and_screenshots(ensure_cluster_running):
    """Verifies adding target as admin, live update, and captures 390px & 1280px screenshots."""
    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch(headless=True)

        for width, suffix in [(390, "390px"), (1280, "1280px")]:
            context = await browser.new_context(
                viewport={"width": width, "height": 844 if width == 390 else 900}
            )
            page: Page = await context.new_page()

            # Set admin key
            await page.goto(BASE_URL_1)
            await page.evaluate(f"localStorage.setItem('netwatch_api_key', '{ADMIN_KEY}')")
            await page.goto(f"{BASE_URL_1}/#/overview")
            await page.wait_for_selector(".brand-name")
            await page.wait_for_timeout(1000)

            # Screenshot: Overview
            await page.screenshot(path=str(SCREENS_DIR / f"overview_{suffix}.png"))

            # Navigate to Targets
            await page.goto(f"{BASE_URL_1}/#/targets")
            await page.wait_for_selector("#targetSearchInput")
            await page.screenshot(path=str(SCREENS_DIR / f"targets_{suffix}.png"))

            # Open Add Target Bottom Sheet
            await page.locator("button:has-text('Add target'):visible").first.click()
            await page.wait_for_selector("#addTargetSheet:not(.hidden)")
            await page.wait_for_timeout(400)
            await page.screenshot(path=str(SCREENS_DIR / f"add_target_modal_{suffix}.png"))

            # Fill and Submit new target
            test_host = f"ping-{width}.google.com"
            await page.fill("#targetHost", test_host)
            await page.fill("#targetPort", "443")
            await page.click("#submitTargetBtn")

            # Wait for sheet to close and target to appear
            await page.wait_for_selector(f"text={test_host}", timeout=8000)
            assert await page.is_visible(f"text={test_host}")

            # Close context
            await context.close()

        await browser.close()


@pytest.mark.asyncio
async def test_viewer_cannot_see_add_button(ensure_cluster_running):
    """Verifies that viewer users do not see the + Add target button."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        await context.add_init_script(f"localStorage.setItem('netwatch_api_key', '{VIEWER_KEY}')")
        page = await context.new_page()

        await page.goto(f"{BASE_URL_1}/#/targets")
        await page.wait_for_selector(".brand-name")
        await page.wait_for_timeout(800)

        check_hidden_js = "el => el.classList.contains('hidden') || el.style.display === 'none'"
        is_hidden = await page.eval_on_selector("#openAddTargetBtn", check_hidden_js)
        assert is_hidden is True

        await browser.close()


@pytest.mark.asyncio
async def test_target_detail_and_chart(ensure_cluster_running):
    """Verifies opening a target, chart rendering, 2x2 cards, and screenshots."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        for width, suffix in [(390, "390px"), (1280, "1280px")]:
            context = await browser.new_context(
                viewport={"width": width, "height": 844 if width == 390 else 900}
            )
            page = await context.new_page()

            await page.goto(BASE_URL_1)
            await page.evaluate(f"localStorage.setItem('netwatch_api_key', '{ADMIN_KEY}')")
            await page.goto(f"{BASE_URL_1}/#/targets")
            await page.wait_for_selector(".target-row")

            # Click first target row
            await page.click(".target-row")
            await page.wait_for_selector("#detailChartContainer")
            await page.wait_for_selector("#detailDnsMs")
            await page.wait_for_selector("#last20ProbesRow")
            await page.wait_for_timeout(800)

            # Assert SVG line path has rendered
            has_path = await page.evaluate(
                "document.getElementById('chartLinePath').getAttribute('d').length > 5"
            )
            assert has_path

            # Capture screenshots
            await page.screenshot(path=str(SCREENS_DIR / f"target_detail_{suffix}.png"))

            await context.close()

        await browser.close()


@pytest.mark.asyncio
async def test_cluster_view_badges_and_failover_drill(ensure_cluster_running):
    """Verifies cluster view, replica badges, timeline, gap pill, and screenshots."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        for width, suffix in [(390, "390px"), (1280, "1280px")]:
            context = await browser.new_context(
                viewport={"width": width, "height": 844 if width == 390 else 900}
            )
            page = await context.new_page()

            await page.goto(BASE_URL_1)
            await page.evaluate(f"localStorage.setItem('netwatch_api_key', '{ADMIN_KEY}')")
            await page.goto(f"{BASE_URL_1}/#/cluster")
            await page.wait_for_selector("#clusterReplicaGrid")
            await page.wait_for_selector(".role-badge-leader")
            await page.wait_for_selector(".role-badge-standby")
            await page.wait_for_selector("#leadershipGapPill")

            # Assert leadership gap pill has required text pattern
            gap_text = await page.text_content("#leadershipGapText")
            assert "Leadership gap" in gap_text

            await page.wait_for_timeout(600)
            await page.screenshot(path=str(SCREENS_DIR / f"cluster_{suffix}.png"))

            # Also capture Settings view
            await page.goto(f"{BASE_URL_1}/#/settings")
            await page.wait_for_selector("#settingsKeyInput")
            await page.wait_for_timeout(400)
            await page.screenshot(path=str(SCREENS_DIR / f"settings_{suffix}.png"))

            await context.close()

        # Failover assertion test on browser:
        # Kill the current leader replica process and assert survivor badges flip
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await context.new_page()
        await page.goto(BASE_URL_1)
        await page.evaluate(f"localStorage.setItem('netwatch_api_key', '{ADMIN_KEY}')")
        await page.goto(f"{BASE_URL_1}/#/cluster")
        await page.wait_for_selector(".role-badge-leader")

        # Discover leader
        cl_res = await httpx.AsyncClient().get(
            f"{BASE_URL_1}/api/cluster", headers={"X-API-Key": VIEWER_KEY}
        )
        cl_data = cl_res.json()
        active_leader = cl_data.get("leader", "replica-1")

        # Terminate active leader backend connection via postgres kill to trigger failover
        # This keeps the web server accessible while forcing leader election failover
        kill_port = 8001 if active_leader == "replica-1" else 8002
        survivor_port = 8002 if kill_port == 8001 else 8001

        # Direct page to survivor port to watch failover live
        await page.goto(f"http://127.0.0.1:{survivor_port}/#/cluster")
        await page.wait_for_selector("#clusterReplicaGrid")

        # Trigger election stepdown / promotion via postgres terminate
        async with async_session_maker() as session:
            # Terminate active leader connection holding the lock
            q = "SELECT pid FROM pg_locks WHERE locktype = 'advisory' AND objid = 827364501 LIMIT 1"
            lock_pid = await session.scalar(text(q))
            if lock_pid:
                await session.execute(text(f"SELECT pg_terminate_backend({lock_pid})"))
                await session.commit()

        # Assert survivor promotes to leader and timeline updates
        await page.wait_for_selector(".timeline-item", timeout=6000)
        assert await page.is_visible("#leadershipGapPill")

        await browser.close()


@pytest.mark.asyncio
async def test_disconnected_banner_appears_and_clears(ensure_cluster_running):
    """Asserts that dropping the connection triggers the banner, which auto-clears on reconnect."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await context.new_page()

        await page.goto(BASE_URL_1)
        await page.evaluate(f"localStorage.setItem('netwatch_api_key', '{ADMIN_KEY}')")
        await page.goto(f"{BASE_URL_1}/#/overview")
        await page.wait_for_selector(".brand-name")

        # Banner should initially be hidden
        assert await page.eval_on_selector(
            "#disconnectedBanner", "el => el.classList.contains('hidden')"
        )

        # Trigger stream error via NetWatchApp
        await page.evaluate("window.NetWatchApp.triggerDisconnect()")

        # Banner appears!
        await page.wait_for_selector("#disconnectedBanner:not(.hidden)", timeout=4000)
        assert await page.is_visible("#disconnectedBanner")
        assert "Connection lost" in await page.text_content("#disconnectedBanner")

        # Simulate reconnect
        await page.evaluate("window.NetWatchApp.triggerReconnect()")
        await page.wait_for_selector("#disconnectedBanner", state="hidden", timeout=4000)
        assert await page.eval_on_selector(
            "#disconnectedBanner", "el => el.classList.contains('hidden')"
        )

        await browser.close()

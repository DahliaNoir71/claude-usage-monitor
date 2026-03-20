"""
Claude Usage Monitor - Playwright Scraper
Scrapes claude.ai/settings/usage using a headless browser
that reuses the user's Chrome login session.
"""
import logging
import os
import platform
from pathlib import Path

logger = logging.getLogger("monitor.scraper")

# Last scrape status, accessible from server
last_scrape_info: dict = {
    "status": None,       # "success", "cloudflare_blocked", "extraction_failed", "timeout", "login_required", "error"
    "error": None,
    "timestamp": None,
}

# JavaScript extraction logic shared by both scraper modes
_EXTRACT_JS = """
() => {
    const data = {
        allModels: null, sonnet: null,
        allModelsResetIn: null, sonnetResetIn: null,
    };
    const sections = document.querySelectorAll('div, section, article');
    for (const section of sections) {
        const text = section.innerText.toLowerCase();
        if ((text.includes('all models') || text.includes('tous les modèles') ||
             text.includes('hebdomadaires') || text.includes('weekly'))
            && !text.includes('sonnet seulement') && !text.includes('sonnet only')) {
            const match = section.innerText.match(/(\\d+)\\s*%/);
            if (match && data.allModels === null) {
                data.allModels = parseInt(match[1]);
                const rm = section.innerText.match(
                    /(?:réinitialisation|reset)\\s*(?:dans?\\s+)?([^%\\n]+?)(?:\\n|$)/i
                );
                if (rm) data.allModelsResetIn = rm[1].trim();
            }
        }
        if (text.includes('sonnet only') || text.includes('sonnet seulement')) {
            const match = section.innerText.match(/(\\d+)\\s*%/);
            if (match && data.sonnet === null) {
                data.sonnet = parseInt(match[1]);
                const rm = section.innerText.match(
                    /(?:réinitialisation|reset)\\s*(?:dans?\\s+)?([^%\\n]+?)(?:\\n|$)/i
                );
                if (rm) data.sonnetResetIn = rm[1].trim();
            }
        }
    }
    if (data.allModels === null) {
        const bars = document.querySelectorAll('[role="progressbar"], progress, [aria-valuenow]');
        bars.forEach((bar, i) => {
            const val = bar.getAttribute('aria-valuenow') || bar.value;
            if (val != null) {
                if (i === 0 && data.allModels === null) data.allModels = parseInt(val);
                else if (i === 1 && data.sonnet === null) data.sonnet = parseInt(val);
            }
        });
    }
    return data;
}
"""


def _find_chrome_user_data_dir() -> str | None:
    system = platform.system()
    home = Path.home()

    candidates = []
    if system == "Windows":
        local_app = os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local"))
        candidates = [
            Path(local_app) / "Google" / "Chrome" / "User Data",
            Path(local_app) / "Google" / "Chrome SxS" / "User Data",
        ]
    elif system == "Darwin":
        candidates = [home / "Library" / "Application Support" / "Google" / "Chrome"]
    else:
        candidates = [home / ".config" / "google-chrome", home / ".config" / "chromium"]

    for c in candidates:
        if c.exists():
            logger.info(f"Found Chrome user data: {c}")
            return str(c)
    return None


async def scrape_usage(
    chrome_user_data_dir: str | None = None,
    chrome_profile: str = "Default",
    headless: bool = True,
    timeout: int = 60,
) -> dict | None:
    """Scrape using Chrome's existing session (Chrome must not be running)."""
    from playwright.async_api import async_playwright

    if chrome_user_data_dir is None:
        chrome_user_data_dir = _find_chrome_user_data_dir()
    if chrome_user_data_dir is None:
        logger.error("Cannot find Chrome user data directory.")
        return None

    profile_path = Path(chrome_user_data_dir)
    if not profile_path.exists():
        logger.error(f"Chrome user data dir not found: {chrome_user_data_dir}")
        return None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch_persistent_context(
                user_data_dir=str(profile_path),
                channel="chrome",
                headless=headless,
                args=[
                    f"--profile-directory={chrome_profile}",
                    *_STEALTH_ARGS,
                ],
                user_agent=_USER_AGENT,
                viewport={"width": 1920, "height": 1080},
                timeout=timeout * 1000,
            )
            page = await browser.new_page()
            await page.add_init_script(_STEALTH_JS)
            logger.info("Navigating to claude.ai/settings/usage...")
            await page.goto("https://claude.ai/settings/usage", wait_until="domcontentloaded", timeout=timeout * 1000)

            await _wait_for_cloudflare(page, max_wait=20)
            await page.wait_for_timeout(2000)
            result = await page.evaluate(_EXTRACT_JS)
            await browser.close()
    except Exception as e:
        logger.error(f"Scraping error: {e}")
        return None

    if result and result.get("allModels") is not None:
        logger.info(f"Scrape OK: All Models={result['allModels']}%, Sonnet={result.get('sonnet', 0)}%")
        return result

    logger.warning(f"Scrape incomplete: {result}")
    return None


_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

_STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--disable-component-extensions-with-background-pages",
]

_STEALTH_JS = """
() => {
    // Hide webdriver flag
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    // Realistic plugins
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5],
    });
    // Realistic languages
    Object.defineProperty(navigator, 'languages', {
        get: () => ['fr-FR', 'fr', 'en-US', 'en'],
    });
    // Chrome runtime
    window.chrome = { runtime: {} };
}
"""


async def _wait_for_cloudflare(page, max_wait: int = 30) -> bool:
    """Wait for Cloudflare challenge to resolve. Returns True if cleared."""
    for i in range(max_wait // 2):
        await page.wait_for_timeout(2000)
        body_text = await page.evaluate("() => document.body?.innerText || ''")
        lower = body_text.lower()
        if "security verification" not in lower and "cloudflare" not in lower and "checking" not in lower:
            logger.info(f"Cloudflare cleared after {(i+1)*2}s")
            return True
    logger.warning(f"Cloudflare challenge did not resolve in {max_wait}s")
    return False


def _update_scrape_status(status: str, error: str | None = None):
    from datetime import datetime
    last_scrape_info["status"] = status
    last_scrape_info["error"] = error
    last_scrape_info["timestamp"] = datetime.now().isoformat()


async def scrape_usage_simple(headless: bool = True, timeout: int = 60, max_retries: int = 2) -> dict | None:
    """Scrape using a dedicated Playwright profile.
    Retries headless attempts with backoff before falling back to visible browser."""
    from playwright.async_api import async_playwright

    from .config import DATA_DIR

    profile_dir = DATA_DIR / "browser_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    target_url = "https://claude.ai/settings/usage"
    backoff_delays = [5, 15]  # seconds between retries
    last_failure_reason = None

    try:
        async with async_playwright() as p:
            # --- Headless attempts with retry ---
            for attempt in range(1, max_retries + 1):
                logger.info(f"Headless attempt {attempt}/{max_retries}...")
                try:
                    browser = await p.chromium.launch_persistent_context(
                        user_data_dir=str(profile_dir),
                        headless=headless,
                        args=_STEALTH_ARGS,
                        user_agent=_USER_AGENT,
                        viewport={"width": 1920, "height": 1080},
                        timeout=timeout * 1000,
                    )
                    page = browser.pages[0] if browser.pages else await browser.new_page()
                    await page.add_init_script(_STEALTH_JS)
                    await page.goto(target_url, wait_until="domcontentloaded", timeout=timeout * 1000)

                    cf_cleared = await _wait_for_cloudflare(page, max_wait=30)

                    current_url = page.url
                    logger.info(f"Headless landed on: {current_url}")

                    if not cf_cleared:
                        last_failure_reason = "cloudflare_blocked"
                        logger.warning(f"Attempt {attempt}: Cloudflare not cleared")
                        await browser.close()
                    elif "/settings" not in current_url:
                        last_failure_reason = "login_required"
                        logger.warning(f"Attempt {attempt}: redirected away from settings (login required?)")
                        await browser.close()
                    else:
                        # Try extraction
                        result = await page.evaluate(_EXTRACT_JS)
                        logger.info(f"Extract result: {result}")
                        if result and result.get("allModels") is not None:
                            await browser.close()
                            _update_scrape_status("success")
                            return result
                        last_failure_reason = "extraction_failed"
                        logger.warning(f"Attempt {attempt}: extraction returned no data")
                        await browser.close()

                except Exception as e:
                    last_failure_reason = "timeout" if "Timeout" in str(e) else "error"
                    logger.warning(f"Attempt {attempt} error: {e}")
                    try:
                        await browser.close()
                    except Exception:
                        pass

                # Backoff before next retry (skip after last attempt)
                if attempt < max_retries:
                    delay = backoff_delays[attempt - 1] if attempt - 1 < len(backoff_delays) else 15
                    logger.info(f"Waiting {delay}s before retry...")
                    import asyncio
                    await asyncio.sleep(delay)

            # --- Fallback: visible browser to pass Cloudflare / login ---
            logger.info("All headless attempts failed. Opening visible browser...")
            browser = await p.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=False,
                args=_STEALTH_ARGS,
                user_agent=_USER_AGENT,
                viewport={"width": 1920, "height": 1080},
                timeout=timeout * 1000,
            )
            page = browser.pages[0] if browser.pages else await browser.new_page()
            await page.add_init_script(_STEALTH_JS)
            await page.goto(target_url, wait_until="domcontentloaded", timeout=timeout * 1000)

            # Wait for Cloudflare in visible mode (should auto-resolve)
            await _wait_for_cloudflare(page, max_wait=30)

            # If redirected to login, wait for user to authenticate
            current_url = page.url
            if "/settings" not in current_url:
                logger.info("Waiting for login (max 120s)...")
                await page.wait_for_url("**/settings/**", timeout=120000)
                await page.wait_for_timeout(4000)

            result = await page.evaluate(_EXTRACT_JS)
            logger.info(f"Extract result (visible): {result}")
            if not result or result.get("allModels") is None:
                page_text = await page.evaluate("() => document.body?.innerText?.substring(0, 500) || ''")
                logger.warning(f"Extraction failed. Page content preview: {page_text[:300]}")
            await browser.close()

            if result and result.get("allModels") is not None:
                _update_scrape_status("success")
                return result

            _update_scrape_status(last_failure_reason or "extraction_failed", "All attempts failed")
            return None

    except Exception as e:
        _update_scrape_status("error", str(e))
        logger.error(f"Simple scraper error: {e}")
        return None

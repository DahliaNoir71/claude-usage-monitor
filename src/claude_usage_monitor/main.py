"""
Claude Usage Monitor - Main Entry Point
System tray app + scraper scheduler + dashboard server.
"""
import asyncio
import logging
import os
import shutil
import sys
import threading
import webbrowser
from pathlib import Path

from .config import APP_NAME, APP_VERSION, DATA_DIR, LOG_PATH, SERVER_HOST, SERVER_PORT, load_config
from . import database as db

# ── Fix stdout/stderr for pythonw.exe (Windows startup) ────────────────────
# pythonw.exe sets sys.stdout and sys.stderr to None, which crashes uvicorn's
# logging formatter when it calls sys.stdout.isatty().
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# ── Logging ─────────────────────────────────────────────────────────────────

LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("monitor")


# ── Scheduler ───────────────────────────────────────────────────────────────

class ScrapeScheduler:
    def __init__(self):
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("Scrape scheduler started")

    def stop(self):
        self._running = False
        logger.info("Scrape scheduler stopped")

    def _loop(self):
        import time

        # Initial delay: wait 60s before first scrape to avoid blocking startup
        for _ in range(60):
            if not self._running:
                return
            time.sleep(1)

        while self._running:
            config = load_config()
            interval = config.get("scrape_interval_minutes", 30) * 60

            if config.get("auto_scrape", True):
                try:
                    asyncio.run(self._do_scrape())
                except Exception as e:
                    logger.error(f"Scheduled scrape failed: {e}")

                if config.get("auto_export_csv", False):
                    try:
                        filepath = db.export_csv()
                        if filepath:
                            logger.info(f"Auto-exported CSV: {filepath}")
                    except Exception as e:
                        logger.error(f"Auto-export failed: {e}")

            for _ in range(int(interval)):
                if not self._running:
                    return
                time.sleep(1)

    async def _do_scrape(self):
        from .scraper import scrape_usage_simple

        logger.info("Running scheduled scrape...")
        result = await scrape_usage_simple(headless=True, timeout=30)
        if result and result.get("allModels") is not None:
            db.add_entry(
                all_models_pct=result["allModels"],
                sonnet_pct=result.get("sonnet", 0) or 0,
                reset_all_models=result.get("allModelsResetIn"),
                reset_sonnet=result.get("sonnetResetIn"),
                source="auto_scrape",
            )
            logger.info(f"Scrape OK: All Models={result['allModels']}%")
            _check_alerts(result)
        else:
            logger.warning("Scrape returned no data")


# ── Notifications ──────────────────────────────────────────────────────────

_last_alert_times: dict[str, float] = {}


def _send_notification(title: str, message: str):
    """Send a desktop notification (Windows toast)."""
    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=message,
            app_name=APP_NAME,
            timeout=10,
        )
        logger.info(f"Notification sent: {title}")
    except ImportError:
        logger.debug("plyer not installed — notifications disabled")
    except Exception as e:
        logger.warning(f"Notification failed: {e}")


def _check_alerts(result: dict):
    """Check thresholds after a scrape and send notifications if needed."""
    import time

    config = load_config()
    if not config.get("notifications_enabled", True):
        return

    cooldown = config.get("alert_cooldown_minutes", 60) * 60
    now = time.time()

    all_models = result.get("allModels", 0) or 0
    sonnet = result.get("sonnet", 0) or 0

    threshold_am = config.get("alert_all_models_threshold", 80)
    threshold_sn = config.get("alert_sonnet_threshold", 80)

    if all_models >= threshold_am:
        if now - _last_alert_times.get("all_models", 0) > cooldown:
            _send_notification(
                "Usage All Models élevé",
                f"All Models à {all_models}% (seuil : {threshold_am}%)",
            )
            _last_alert_times["all_models"] = now

    if sonnet >= threshold_sn:
        if now - _last_alert_times.get("sonnet", 0) > cooldown:
            _send_notification(
                "Usage Sonnet élevé",
                f"Sonnet à {sonnet}% (seuil : {threshold_sn}%)",
            )
            _last_alert_times["sonnet"] = now

    # Alert on reset detected
    if config.get("alert_on_reset", True):
        prev = db.get_latest_entry()
        if prev:
            prev_am = prev.get("all_models_pct", 0) or 0
            if all_models < prev_am - 5:
                if now - _last_alert_times.get("reset", 0) > cooldown:
                    _send_notification(
                        "Reset détecté",
                        f"All Models : {prev_am}% → {all_models}%",
                    )
                    _last_alert_times["reset"] = now


# ── System Tray ─────────────────────────────────────────────────────────────

def _create_tray_icon(scheduler: ScrapeScheduler):
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        logger.warning(
            "pystray or Pillow not installed — running without system tray. "
            "Install with: uv add pystray Pillow"
        )
        return None

    def _make_image():
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([2, 2, size - 2, size - 2], fill="#6366f1")
        bw, gap = 8, 4
        x0 = 16
        for x, h in [(x0, 14), (x0 + bw + gap, 24), (x0 + 2 * (bw + gap), 32)]:
            draw.rectangle([x, 50 - h, x + bw, 50], fill="white")
        return img

    def open_dashboard(*_):
        webbrowser.open(f"http://{SERVER_HOST}:{SERVER_PORT}")

    def scrape_now(*_):
        threading.Thread(target=lambda: asyncio.run(scheduler._do_scrape()), daemon=True).start()

    def export_csv(*_):
        fp = db.export_csv()
        if fp:
            logger.info(f"Exported: {fp}")

    def quit_app(icon, *_):
        scheduler.stop()
        icon.stop()
        logger.info("Application exiting")
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("Ouvrir le dashboard", open_dashboard, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Scraper maintenant", scrape_now),
        pystray.MenuItem("Exporter CSV", export_csv),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quitter", quit_app),
    )
    return pystray.Icon("claude_monitor", _make_image(), APP_NAME, menu)


# ── Windows Startup & Shortcuts ────────────────────────────────────────────


def _get_launcher_paths() -> dict:
    """Resolve absolute paths for launcher executables and scripts."""
    exe_dir = Path(sys.executable).parent
    pythonw = exe_dir / "pythonw.exe"
    return {
        "pythonw": str(pythonw) if pythonw.exists() else sys.executable,
        "python": sys.executable,
        "vbs": DATA_DIR / "launch_monitor.vbs",
        "bat": DATA_DIR / "launch_monitor.bat",
    }


def _create_launcher_scripts():
    """Create .bat and .vbs launcher scripts in DATA_DIR."""
    if sys.platform != "win32":
        return
    paths = _get_launcher_paths()

    # .bat — manual launch with console visible
    bat_content = f'@echo off\r\n"{paths["python"]}" -m claude_usage_monitor\r\n'
    paths["bat"].write_text(bat_content, encoding="utf-8")
    logger.info(f"Created launcher: {paths['bat']}")

    # .vbs — silent startup (hidden window)
    vbs_content = (
        'Set WshShell = CreateObject("WScript.Shell")\r\n'
        f'WshShell.Run """{paths["pythonw"]}"" -m claude_usage_monitor", 0, False\r\n'
    )
    paths["vbs"].write_text(vbs_content, encoding="utf-8")
    logger.info(f"Created launcher: {paths['vbs']}")


def _register_startup(enable: bool = True):
    if sys.platform != "win32":
        logger.info("Startup registration only supported on Windows")
        return
    try:
        import winreg

        if enable:
            _create_launcher_scripts()
            paths = _get_launcher_paths()
            cmd = f'wscript.exe "{paths["vbs"]}"'

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_ALL_ACCESS,
        )
        if enable:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
            logger.info(f"Registered startup: {cmd}")
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception as e:
        logger.error(f"Startup registration error: {e}")


def _create_desktop_shortcut():
    """Create a desktop shortcut (.lnk) pointing to the .bat launcher."""
    if sys.platform != "win32":
        print("Desktop shortcuts only supported on Windows")
        return
    import subprocess

    paths = _get_launcher_paths()
    _create_launcher_scripts()
    desktop = Path.home() / "Desktop"
    shortcut = desktop / f"{APP_NAME}.lnk"
    ps_script = (
        '$ws = New-Object -ComObject WScript.Shell; '
        f'$sc = $ws.CreateShortcut("{shortcut}"); '
        f'$sc.TargetPath = "{paths["bat"]}"; '
        f'$sc.WorkingDirectory = "{DATA_DIR}"; '
        f'$sc.Description = "{APP_NAME}"; '
        '$sc.Save()'
    )
    try:
        subprocess.run(["powershell", "-Command", ps_script], check=True)
        print(f"Desktop shortcut created: {shortcut}")
    except Exception as e:
        print(f"Failed to create shortcut: {e}")


def _create_startup_task():
    """Create a scheduled task to launch at user logon (alternative to registry)."""
    if sys.platform != "win32":
        print("Scheduled tasks only supported on Windows")
        return
    import subprocess

    paths = _get_launcher_paths()
    _create_launcher_scripts()
    task_name = "ClaudeUsageMonitor"
    cmd = f'wscript.exe "{paths["vbs"]}"'
    try:
        subprocess.run(
            [
                "schtasks", "/Create",
                "/TN", task_name,
                "/TR", cmd,
                "/SC", "ONLOGON",
                "/DELAY", "0000:30",
                "/F",
            ],
            check=True,
        )
        print(f"Scheduled task '{task_name}' created (runs at logon with 30s delay)")
    except Exception as e:
        print(f"Failed to create scheduled task: {e}")


def _remove_startup_task():
    """Remove the scheduled task."""
    if sys.platform != "win32":
        print("Scheduled tasks only supported on Windows")
        return
    import subprocess

    task_name = "ClaudeUsageMonitor"
    try:
        subprocess.run(
            ["schtasks", "/Delete", "/TN", task_name, "/F"],
            check=True,
        )
        print(f"Scheduled task '{task_name}' removed")
    except Exception as e:
        print(f"Failed to remove scheduled task: {e}")


# ── Data Migration ─────────────────────────────────────────────────────────

def _migrate_old_data():
    """Migrate data from old CWD-based location to the new stable DATA_DIR."""
    old_candidates = [
        Path.cwd() / "data",
        Path(__file__).parent.parent / "data",
    ]
    new_db = DATA_DIR / "usage.db"
    if new_db.exists():
        return

    for old_dir in old_candidates:
        old_db = old_dir / "usage.db"
        if not old_db.exists():
            continue
        logger.info(f"Migrating data from {old_dir} -> {DATA_DIR}")
        for fname in ["usage.db", "config.json", "monitor.log"]:
            src = old_dir / fname
            dst = DATA_DIR / fname
            if src.exists() and not dst.exists():
                shutil.copy2(str(src), str(dst))
        old_exports = old_dir / "exports"
        if old_exports.exists():
            new_exports = DATA_DIR / "exports"
            new_exports.mkdir(exist_ok=True)
            for csv_file in old_exports.glob("*.csv"):
                dst = new_exports / csv_file.name
                if not dst.exists():
                    shutil.copy2(str(csv_file), str(dst))
        logger.info(f"Migration complete. Old data in {old_dir} can be removed.")
        break


# ── Server thread ───────────────────────────────────────────────────────────

def _start_server(ready_event: threading.Event, error_event: threading.Event):
    try:
        import uvicorn
        from contextlib import asynccontextmanager

        from .server import app

        @asynccontextmanager
        async def lifespan(app):
            ready_event.set()
            yield

        app.router.lifespan_context = lifespan
        uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT, log_level="warning", log_config=None)
    except Exception as e:
        logger.error(f"Server failed to start: {e}", exc_info=True)
        error_event.set()


# ── Static files ──────────────────────────────────────────────────────────

def _ensure_static():
    """Create STATIC_DIR and a placeholder dashboard.html if missing."""
    from .config import STATIC_DIR

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    dashboard = STATIC_DIR / "dashboard.html"
    if not dashboard.exists():
        logger.warning(f"dashboard.html missing, creating placeholder at {dashboard}")
        dashboard.write_text(
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<title>Claude Usage Monitor</title></head><body>"
            "<h1>Claude Usage Monitor</h1>"
            "<p>Dashboard placeholder. Replace static/dashboard.html with the full dashboard.</p>"
            "<h2>API</h2><ul>"
            "<li><a href='/api/status'>/api/status</a></li>"
            "<li><a href='/api/analysis'>/api/analysis</a></li>"
            "<li><a href='/api/entries'>/api/entries</a></li>"
            "</ul></body></html>",
            encoding="utf-8",
        )


# ── Diagnostics ────────────────────────────────────────────────────────────

def _run_diagnose():
    """Check environment health without starting the app."""
    import socket

    from .config import DB_PATH, STATIC_DIR

    print("Claude Usage Monitor - Diagnostics")
    print("=" * 40)

    # Python version
    ok = sys.version_info >= (3, 11)
    print(f"{'[OK]' if ok else '[FAIL]'} Python: {sys.version.split()[0]}")

    # Required dependencies
    for name, module in [
        ("uvicorn", "uvicorn"),
        ("fastapi", "fastapi"),
        ("playwright", "playwright"),
        ("pystray", "pystray"),
        ("Pillow", "PIL"),
    ]:
        try:
            __import__(module)
            print(f"[OK]   {name}")
        except ImportError:
            print(f"[FAIL] {name} -- not installed")

    # Playwright browsers
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            path = p.chromium.executable_path
            if path and Path(path).exists():
                print(f"[OK]   Playwright Chromium")
            else:
                print("[WARN] Playwright Chromium not found. Run: playwright install chromium")
    except Exception:
        print("[WARN] Playwright browser check failed")

    # Port availability
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            result = s.connect_ex(("127.0.0.1", SERVER_PORT))
            if result == 0:
                print(f"[WARN] Port {SERVER_PORT} is already in use")
            else:
                print(f"[OK]   Port {SERVER_PORT} is available")
    except Exception:
        print(f"[WARN] Could not check port {SERVER_PORT}")

    # Static dashboard
    dashboard = STATIC_DIR / "dashboard.html"
    if dashboard.exists():
        print(f"[OK]   dashboard.html ({dashboard.stat().st_size:,} bytes)")
    else:
        print(f"[FAIL] dashboard.html not found at {dashboard}")

    # Data directory
    if DATA_DIR.exists():
        test_file = DATA_DIR / ".diag_test"
        try:
            test_file.write_text("test")
            test_file.unlink()
            print(f"[OK]   Data dir writable: {DATA_DIR}")
        except Exception:
            print(f"[FAIL] Data dir not writable: {DATA_DIR}")
    else:
        print(f"[WARN] Data dir does not exist: {DATA_DIR}")

    # Database
    if DB_PATH.exists():
        print(f"[OK]   Database: {DB_PATH} ({DB_PATH.stat().st_size:,} bytes)")
    else:
        print(f"[INFO] Database does not exist yet: {DB_PATH}")

    # pythonw.exe
    pythonw = Path(sys.executable).parent / "pythonw.exe"
    if pythonw.exists():
        print(f"[OK]   pythonw.exe: {pythonw}")
    else:
        print(f"[WARN] pythonw.exe not found in {pythonw.parent}")

    # Launcher scripts
    paths = _get_launcher_paths()
    for label, key in [("launch_monitor.vbs", "vbs"), ("launch_monitor.bat", "bat")]:
        p = paths[key]
        if p.exists():
            print(f"[OK]   {label}: {p}")
        else:
            print(f"[WARN] {label} not found (run --register-startup to create)")

    # Windows registry entry
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_READ,
            )
            try:
                value, _ = winreg.QueryValueEx(key, APP_NAME)
                print(f"[OK]   Registry startup: {value}")
            except FileNotFoundError:
                print("[INFO] Registry startup: not registered")
            winreg.CloseKey(key)
        except Exception as e:
            print(f"[WARN] Registry check failed: {e}")

    # Task Scheduler
    if sys.platform == "win32":
        import subprocess
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", "ClaudeUsageMonitor"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print("[OK]   Scheduled task: ClaudeUsageMonitor found")
        else:
            print("[INFO] Scheduled task: ClaudeUsageMonitor not found")

    print("=" * 40)


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    # CLI sub-commands
    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == "--help":
            print(f"{APP_NAME} v{APP_VERSION}")
            print("Usage: python -m claude_usage_monitor [command]\n")
            print("Commands:")
            print("  (no args)            Start the app (tray + server + scraper)")
            print("  --data-dir           Show the data directory path")
            print("  --migrate-data       Migrate data from old CWD-based location")
            print("  --import-csv [file]  Import CSV (default: claudeusagehistorymerged.csv)")
            print("  --export-csv         Export data to CSV")
            print("  --register-startup   Register Windows startup entry")
            print("  --unregister-startup Remove Windows startup entry")
            print("  --create-task        Create scheduled task (alternative to registry)")
            print("  --remove-task        Remove scheduled task")
            print("  --create-shortcut    Create desktop shortcut")
            print("  --diagnose           Run environment diagnostics")
            print("  --help               Show this help message")
            return

        if cmd == "--data-dir":
            print(str(DATA_DIR))
            return

        if cmd == "--migrate-data":
            _migrate_old_data()
            return

        if cmd == "--import-csv":
            db.init_db()
            csv_path = sys.argv[2] if len(sys.argv) > 2 else "claudeusagehistorymerged.csv"
            count = db.import_csv(csv_path)
            print(f"Imported {count} entries from {csv_path}")
            return

        if cmd == "--export-csv":
            db.init_db()
            fp = db.export_csv()
            print(f"Exported to {fp}" if fp else "No data to export")
            return

        if cmd == "--register-startup":
            _register_startup(True)
            return

        if cmd == "--unregister-startup":
            _register_startup(False)
            return

        if cmd == "--create-task":
            _create_startup_task()
            return

        if cmd == "--remove-task":
            _remove_startup_task()
            return

        if cmd == "--create-shortcut":
            _create_desktop_shortcut()
            return

        if cmd == "--diagnose":
            _run_diagnose()
            return

    # Normal startup
    logger.info(f"=== {APP_NAME} starting ===")
    _migrate_old_data()
    db.init_db()
    _ensure_static()
    logger.info(f"Database: {db.DB_PATH} ({db.entry_count()} entries)")

    config = load_config()
    logger.info(f"Plan: {config['plan']}, Auto-scrape: {config['auto_scrape']}")

    if config.get("launch_at_startup"):
        _register_startup(True)

    _create_launcher_scripts()

    scheduler = ScrapeScheduler()
    scheduler.start()

    server_ready = threading.Event()
    server_error = threading.Event()
    threading.Thread(target=_start_server, args=(server_ready, server_error), daemon=True).start()

    if not server_ready.wait(timeout=15):
        if server_error.is_set():
            logger.error("Server failed to start. Check logs for details.")
        else:
            logger.warning("Server did not signal ready within 15 seconds.")

    logger.info(f"Dashboard: http://{SERVER_HOST}:{SERVER_PORT}")

    tray = _create_tray_icon(scheduler)
    if tray:
        if server_ready.is_set():
            threading.Timer(1.0, lambda: webbrowser.open(f"http://{SERVER_HOST}:{SERVER_PORT}")).start()
        logger.info("System tray active. Double-click to open dashboard.")
        tray.run()
    else:
        logger.info("Running without tray. Ctrl+C to quit.")
        try:
            if server_ready.is_set():
                webbrowser.open(f"http://{SERVER_HOST}:{SERVER_PORT}")
            else:
                logger.warning("Skipping browser open -- server not ready.")
            threading.Event().wait()
        except KeyboardInterrupt:
            scheduler.stop()
            logger.info("Shutting down...")

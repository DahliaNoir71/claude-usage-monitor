# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Claude Usage Monitor."""

import os
import sys
from pathlib import Path

block_cipher = None

src_dir = os.path.join("src", "claude_usage_monitor")
static_dir = os.path.join(src_dir, "static")

a = Analysis(
    [os.path.join(src_dir, "__main__.py")],
    pathex=["src"],
    binaries=[],
    datas=[
        (static_dir, os.path.join("claude_usage_monitor", "static")),
    ],
    hiddenimports=[
        "claude_usage_monitor",
        "claude_usage_monitor.main",
        "claude_usage_monitor.server",
        "claude_usage_monitor.scraper",
        "claude_usage_monitor.database",
        "claude_usage_monitor.analyzer",
        "claude_usage_monitor.config",
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "fastapi",
        "pystray",
        "PIL",
        "plyer",
        "plyer.platforms.win.notification",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "playwright",  # Playwright must be installed separately
        "tkinter",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ClaudeUsageMonitor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # No console window (windowed app with tray)
    icon=None,  # Add .ico path here if available
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ClaudeUsageMonitor",
)

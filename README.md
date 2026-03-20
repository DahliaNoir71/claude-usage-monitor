# Claude Usage Monitor

Application Windows qui surveille ta consommation Claude et recommande le plan optimal.

Tourne en arrière-plan (system tray), scrape automatiquement `claude.ai/settings/usage` via Playwright headless, et sert un dashboard local avec graphiques et recommandations.

## Pourquoi ?

La page `claude.ai/settings/usage` affiche la consommation **totale tous clients confondus** : navigateur web, application Desktop, Claude Code (VS Code), API. Cette app capture ce total automatiquement toutes les 30 min, ce qu'une simple extension Chrome ne peut pas faire.

## Stack

- **Python 3.11+** avec **uv** pour la gestion de projet
- **FastAPI** + **uvicorn** pour le serveur local
- **Playwright** pour le scraping headless
- **SQLite** pour le stockage
- **pystray** pour le system tray Windows
- **Chart.js** pour les graphiques du dashboard

## Installation

### Prérequis

- [uv](https://docs.astral.sh/uv/getting-started/installation/) installé
- Google Chrome connecté à claude.ai

### Setup

```bash
# Cloner ou décompresser le projet
cd claude-usage-monitor

# Installer les dépendances + créer le venv
uv sync

# Installer le navigateur Playwright
uv run playwright install chromium
```

## Utilisation

### Lancer l'application

```bash
uv run claude-monitor
```

Le dashboard s'ouvre sur http://127.0.0.1:8420 et l'icône apparaît dans le system tray.

### Importer ton historique CSV existant

```bash
uv run claude-monitor --import-csv chemin\vers\claudeusagehistorymerged.csv
```

### Exporter en CSV

```bash
uv run claude-monitor --export-csv
```

### Lancement au démarrage de Windows

```bash
uv run claude-monitor --register-startup
# Pour retirer :
uv run claude-monitor --unregister-startup
```

### Alternative : lancer comme module

```bash
uv run python -m claude_usage_monitor
```

## Fonctionnement

```
🚀 Au lancement :
   └─→ Initialise SQLite (data/usage.db)
   └─→ Démarre le serveur FastAPI (port 8420)
   └─→ Démarre le scheduler de scraping
   └─→ Icône dans le system tray

🔄 Toutes les 30 min (configurable) :
   └─→ Playwright ouvre claude.ai/settings/usage en headless
   └─→ Extrait les % All Models et Sonnet
   └─→ Stocke en base + export CSV si activé

📊 Dashboard (http://127.0.0.1:8420) :
   ├─ Vue d'ensemble : métriques, recommandation, graphiques
   ├─ Historique : timeline, resets, entrées brutes
   ├─ Plans : comparaison, simulateur d'économies
   └─ Paramètres : plan, intervalle, import/export
```

### System tray (Windows)

- **Double-clic** : ouvre le dashboard
- **Clic droit** → Scraper maintenant / Exporter CSV / Quitter

### Première connexion

Au premier scraping, si aucune session n'existe, un navigateur visible s'ouvre pour te connecter à claude.ai. La session est ensuite mémorisée dans `data/browser_profile/`.

## API REST

| Endpoint | Méthode | Description |
|----------|---------|-------------|
| `/api/status` | GET | État de l'app |
| `/api/analysis` | GET | Analyse + recommandation |
| `/api/entries` | GET | Entrées (`?days=7&limit=100`) |
| `/api/daily` | GET | Résumés quotidiens |
| `/api/weekly` | GET | Peaks hebdomadaires |
| `/api/config` | GET/PUT | Configuration |
| `/api/scrape` | POST | Forcer un scraping |
| `/api/export/csv` | GET | Télécharger CSV |
| `/api/import/csv` | POST | Importer CSV |

## Structure

```
claude-usage-monitor/
├── pyproject.toml
├── README.md
├── src/
│   └── claude_usage_monitor/
│       ├── __init__.py
│       ├── __main__.py        # python -m support
│       ├── main.py            # Entry point (tray + scheduler)
│       ├── server.py          # FastAPI
│       ├── scraper.py         # Playwright headless
│       ├── database.py        # SQLite
│       ├── analyzer.py        # Analyse + recommandation
│       ├── config.py          # Configuration
│       └── static/
│           └── dashboard.html # Dashboard Chart.js
└── data/                      # Créé au runtime
    ├── usage.db
    ├── config.json
    ├── monitor.log
    ├── browser_profile/
    └── exports/
```

## Dépannage

### Le scraping échoue

- **Chrome ouvert** : le scraper utilise son propre profil dans `data/browser_profile/`, pas celui de Chrome.
- **Session expirée** : relance l'app, un navigateur visible s'ouvre pour la reconnexion.
- **Page modifiée par Anthropic** : vérifie `data/monitor.log`.

### Le dashboard ne charge pas

Vérifie que le port 8420 est libre : `netstat -an | findstr 8420`

### Installer uv

```powershell
# Windows PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## Licence

MIT

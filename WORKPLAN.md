# Claude Monitor v2.1 — Workplan

## Contexte

**Claude Usage Monitor** (v2.0.1) est une application desktop Python qui surveille la consommation sur claude.ai.

### Architecture actuelle
- **Backend** : FastAPI serveur local sur `127.0.0.1:8420`
- **Scraping** : Playwright (headless Chromium) qui scrape `claude.ai/settings/usage` en réutilisant la session Chrome de l'utilisateur
- **Stockage** : SQLite (`usage.db`) avec tables `usage_entries` et `daily_summaries`
- **Dashboard** : page HTML statique servie par FastAPI (`static/dashboard.html`)
- **System tray** : icône Windows avec double-clic pour ouvrir le dashboard
- **Démarrage auto** : enregistrement au démarrage Windows via registre
- **Plateforme** : Windows principalement (support macOS/Linux dans la config des paths)

### Fichiers principaux
```
claude_usage_monitor/
├── __init__.py          # Version 2.0.1
├── __main__.py          # Entrypoint: python -m claude_usage_monitor
├── main.py              # Orchestration: tray, scheduler, serveur
├── server.py            # FastAPI (API REST + dashboard HTML)
├── scraper.py           # Playwright scraper avec gestion Cloudflare
├── database.py          # SQLite (CRUD, export/import CSV, cycles, resets)
├── analyzer.py          # Analyse, recommandation de plan
├── config.py            # Config, plans, paths OS-aware
└── static/
    └── dashboard.html   # Frontend (HTML/JS/CSS monolithique)
```

### Problèmes connus (logs)
- Le scraper headless échoue fréquemment sur Cloudflare (`Page.goto: Timeout 30000ms`)
- Fallback vers navigateur visible fonctionne mais nécessite interaction manuelle
- Erreur de syntaxe transitoire dans `scraper.py` ligne 121 (résolue depuis)
- Le scrape retourne parfois `null` même après passage Cloudflare

### Problème conceptuel majeur
L'analyse actuelle raisonne en **pics hebdomadaires** et en **cycles de ~5h** pour recommander un plan. Or les abonnements Claude sont **mensuels**. La recommandation doit être recentrée sur la consommation mensuelle agrégée : c'est le mois complet qui détermine si un utilisateur a besoin ou non de changer de plan.

---

## Phase 1 — Bugfixes critiques

### 1.1 Fix graphique "Peaks hebdomadaires" vide (Dashboard)

**Problème** : Le bar chart "Peaks hebdomadaires" dans l'onglet Cycles ne rend aucune donnée.

**Investigation** :
- L'endpoint `/api/weekly` utilise `strftime('%Y-W%W', timestamp)` en SQLite. **Attention** : `%W` commence le comptage à 00 (lundi = premier jour), ce qui peut diverger du format ISO `%V`. Vérifier que le frontend parse le même format.
- Le dashboard HTML (`static/dashboard.html`) fait un `fetch('/api/weekly')` — vérifier que la réponse contient bien des données (tester avec `curl http://127.0.0.1:8420/api/weekly`).
- Vérifier le mapping entre les clés de la réponse (`max_all_models`, `max_sonnet`, `week`) et les propriétés attendues par le chart JS dans `dashboard.html`.
- Les semaines affichées (W04, W05, W06, W11) ont un trou entre W06 et W11 — si le chart s'attend à des semaines contiguës, les semaines sans données peuvent casser le rendu.

**Fix probable** :
- Dans `database.py`, fonction `get_weekly_peaks()` : remplacer `%W` par un calcul ISO week correct, ou aligner le frontend sur le format retourné.
- Dans `dashboard.html` : s'assurer que le chart gère les semaines non-contiguës (pas d'interpolation forcée).

**Résultat attendu** : Le graphique affiche des barres pour chaque semaine ayant des données.

### 1.2 Fix typo "Donnees" → "Données" (Historique)

**Problème** : Le titre de la section dans l'onglet Historique affiche "Donnees" au lieu de "Données".

**Fix dans `dashboard.html`** : Rechercher toutes les occurrences de "Donnees" et remplacer par "Données". Vérifier aussi les autres labels pour d'éventuels accents manquants (ex: "Parametres" → "Paramètres", "Velocite" → "Vélocité", "Resets detectes" → "Resets détectés", "Historique complet" ok).

**Résultat attendu** : Tous les labels du dashboard affichent correctement les accents français.

### 1.3 Fiabiliser le scraper Cloudflare

**Problème** : Le log montre que le scraper headless est bloqué par Cloudflare dans la majorité des cas. Les timeouts à 30s sont insuffisants et le fallback visible n'est pas toujours déclenché.

**Investigation et fix** :
- Dans `scraper.py`, fonction `scrape_usage_simple()` : le `wait_until` utilise `"networkidle"` dans certains chemins de code (visible dans les logs de timeout). Remplacer systématiquement par `"domcontentloaded"` qui est plus rapide et suffisant puisque les données sont déjà dans le DOM initial.
- Augmenter le timeout Cloudflare de 20s à 30s dans `_wait_for_cloudflare()` pour le mode headless.
- Ajouter un retry automatique (max 2 retries avec backoff) avant de basculer en mode visible.
- Logger plus clairement la distinction entre "Cloudflare bloqué" et "données non trouvées dans le DOM".

**Résultat attendu** : Taux de succès du scrape headless amélioré. Moins de fallbacks vers le navigateur visible.

---

## Phase 2 — Recentrer l'analyse sur la consommation mensuelle

> C'est le changement le plus structurant de la v2.1. Les abonnements Claude étant mensuels, toute la logique de recommandation et les vues principales doivent raisonner en mois.

### 2.1 Agrégation mensuelle en base de données

**Implémentation dans `database.py`** :

- Ajouter une nouvelle table `monthly_summaries` :
  ```sql
  CREATE TABLE IF NOT EXISTS monthly_summaries (
      month TEXT PRIMARY KEY,           -- Format YYYY-MM
      max_all_models INTEGER,           -- Pic All Models du mois
      avg_all_models REAL,              -- Moyenne All Models du mois
      max_sonnet INTEGER,               -- Pic Sonnet du mois
      avg_sonnet REAL,                  -- Moyenne Sonnet du mois
      rate_limit_days INTEGER,          -- Nb de jours où un pic > 80% a été atteint
      total_entries INTEGER,            -- Nb de mesures dans le mois
      active_days INTEGER,              -- Nb de jours distincts avec au moins 1 mesure
      first_entry TEXT,                 -- Timestamp première mesure
      last_entry TEXT                   -- Timestamp dernière mesure
  )
  ```
- Mettre à jour `monthly_summaries` à chaque `add_entry()` (comme `_update_daily_summary()` existant).
- Nouvelle fonction `get_monthly_summaries(months: int = 6) -> list[dict]`.
- Nouveau endpoint dans `server.py` : `GET /api/monthly` → retourne les résumés mensuels.
- Nouvelle fonction `get_monthly_peaks(months: int = 6) -> list[dict]` — requête SQL :
  ```sql
  SELECT
      strftime('%Y-%m', timestamp) as month,
      MAX(all_models_pct) as max_all_models,
      AVG(all_models_pct) as avg_all_models,
      MAX(sonnet_pct) as max_sonnet,
      AVG(sonnet_pct) as avg_sonnet,
      COUNT(DISTINCT date(timestamp)) as active_days,
      COUNT(*) as entries_count
  FROM usage_entries
  WHERE timestamp >= ?
  GROUP BY month
  ORDER BY month ASC
  ```

### 2.2 Refonte de la logique de recommandation

**Implémentation dans `analyzer.py`** :

La fonction `_recommend_plan()` doit être refondue pour raisonner en **consommation mensuelle** plutôt qu'en pics hebdomadaires.

**Nouvelles métriques clés pour la décision** :
- `monthly_avg_peak` : moyenne des pics mensuels All Models.
- `monthly_max_peak` : pic absolu sur l'ensemble des mois.
- `monthly_avg_usage` : moyenne d'utilisation mensuelle All Models.
- `rate_limit_frequency` : nombre de jours/mois où l'usage dépasse 80%.
- `monthly_trend` : tendance (hausse/baisse/stable) calculée sur les 3 derniers mois.

**Nouvelle signature** :
```python
def _recommend_plan(
    monthly_stats: list[dict],    # Résumés mensuels
    sonnet_cycles: list[dict],    # Conservé pour info Sonnet
    current_plan: str,
    days_covered: int,
) -> dict:
```

**Règles de décision révisées** :

| Situation | Action | Confiance |
|-----------|--------|-----------|
| Plan Max et pic mensuel max ≤ 30% sur les 2+ derniers mois complets | Recommander **Pro** (downgrade) | high si 3+ mois, medium si 2 mois |
| Plan Max et pic mensuel max ≤ 50% | Suggérer d'**envisager Pro** | medium |
| Plan Max et pic mensuel max 50-75% | **Maintenir** le plan | high |
| Plan Max et pic mensuel max > 75% | **Bon usage** du plan | high |
| Plan Pro et pic mensuel max > 80% fréquemment (2+ mois) | Recommander **Max** (upgrade) | high |
| Plan Pro et pic mensuel max ≤ 80% | **Maintenir** le plan | high |
| Plan Free et jours rate-limités > 5/mois | Recommander **Pro** (upgrade) | high |
| Données < 1 mois complet | **Maintenir** avec caveat "données insuffisantes" | low |

**Trend mensuel** : Si la consommation est en hausse constante sur 3 mois (chaque mois > mois précédent de +10% relatif), ajouter un caveat "Tendance à la hausse — réévalue dans 1 mois".

**Champs retournés** (inchangés en structure, enrichis) :
```python
{
    "plan": "pro",
    "plan_name": "Pro",
    "action": "downgrade",
    "confidence": "high",
    "reason": "Sur les 3 derniers mois, ton pic max All Models est de 27% (moyenne 15%). Le Pro couvrirait largement cet usage.",
    "caveats": [...],
    "savings_monthly": 80,
    "savings_yearly": 960,
    "stats": {
        "months_analyzed": 3,
        "monthly_peaks": [22, 27, 19],
        "monthly_avgs": [12, 15, 11],
        "rate_limit_days_per_month": [0, 1, 0],
        "trend": "stable",
        "days_covered": 52,
    },
}
```

### 2.3 Vue d'ensemble : ajouter le résumé mensuel

**Implémentation dans `dashboard.html`** (Vue d'ensemble) :

- **Nouvelles KPI cards** remplaçant ou complétant les actuelles :
  - "Usage ce mois" : pic All Models du mois en cours + barre de progression vers 100%.
  - "Mois précédent" : pic All Models du mois dernier (pour comparaison).
  - "Jours actifs" : nombre de jours avec au moins 1 mesure ce mois.
  - "Tendance" : flèche ↗️↘️→ selon le trend (hausse/baisse/stable).
- Conserver les KPI actuelles (All Models courant, Sonnet courant, Pic max, Jours couverts) mais les déplacer dans une section secondaire "Détails temps réel".
- Le bloc recommandation utilise maintenant les données mensuelles et la raison mentionne explicitement les mois ("Sur les 3 derniers mois...").

### 2.4 Dashboard Cycles : ajouter les peaks mensuels

**Implémentation dans `dashboard.html`** (onglet Cycles) :

- **Nouveau graphique** : "Peaks mensuels" (bar chart, en haut de l'onglet, au-dessus des peaks hebdomadaires).
  - Axe X : mois (Jan, Fév, Mar…).
  - Barres : pic All Models (bleu) et pic Sonnet (orange) par mois.
  - Ligne horizontale pointillée à 80% = zone de risque rate-limit.
  - Source : `GET /api/monthly`.
- Conserver le graphique "Peaks hebdomadaires" (une fois fixé) et "Cycles Sonnet" en dessous comme vues détaillées.

---

## Phase 3 — Améliorations UX / Dashboard

> Toutes les modifications frontend sont dans `static/dashboard.html`.

### 3.1 Pagination du tableau Historique

**Problème** : 174+ entrées affichées d'un bloc.

**Changements dans `dashboard.html`** :
- Pagination côté client JS : 50 entrées par page par défaut.
- Sélecteur de lignes par page (30 / 50 / 100 / Tout).
- **Filtre par mois** (sélecteur dropdown avec les mois disponibles, en plus d'un filtre plage de dates).
- Boutons Précédent / Suivant + numéros de page cliquables.
- Footer du tableau : "Page 1/4 — 174 entrées".
- L'export CSV (bouton existant "Exporter CSV") continue d'exporter **toutes** les données via `/api/export/csv`.

### 3.2 Lisibilité axe X du graphique "Cycles Sonnet"

**Problème** : Les labels C1…C18 sont tassés sur l'axe X.

**Changements dans `dashboard.html`** :
- Appliquer une rotation de 45° sur les labels de l'axe X du chart Cycles Sonnet.
- OU afficher un label sur deux pour réduire la densité.
- S'assurer que le tooltip au hover affiche le numéro de cycle complet + dates du cycle.

### 3.3 Restructurer le bloc recommandation (Vue d'ensemble)

**État actuel** : La recommandation Pro et la note sur le plan Max sont dans le même bloc vert.

**Changements dans `dashboard.html`** :
- Séparer en deux blocs visuels distincts :
  - **Bloc principal** (bordure verte) : recommandation de plan, badge action, confiance, économies. La raison mentionne les mois analysés.
  - **Bloc secondaire** (bordure gris-bleu, plus discret) : caveats (`recommendation.caveats[]`). Ne s'affiche que si le tableau caveats est non-vide.

### 3.4 Indicateur de fraîcheur des données

**Ajout dans `dashboard.html`** (Vue d'ensemble) :
- Afficher sous les KPI cards : "Dernière mesure : il y a X min" en utilisant `latest.timestamp` de `/api/analysis`.
- Calcul relatif côté JS (`Date.now() - new Date(timestamp)`).
- Si > 24h, afficher en orange avec icône ⚠️.
- Tooltip au hover avec le timestamp exact.

---

## Phase 4 — Nouvelles fonctionnalités

### 4.1 Prédiction de reset & compte à rebours

**Contexte** : Le scraper récupère déjà `reset_all_models` et `reset_sonnet` (ex: "18 h 36 min"). Les cycles Sonnet montrent des patterns de ~5h.

**Implémentation backend** (`analyzer.py` + `database.py`) :
- Nouvelle fonction `compute_cycle_stats()` dans `analyzer.py` :
  - Calculer la durée médiane des cycles All Models et Sonnet à partir des resets détectés.
  - Retourner : `median_cycle_duration`, `stddev`, `last_reset_timestamp`, `next_reset_estimate`.
- Ajouter le champ `cycle_stats` dans la réponse de `analyze()`.

**Implémentation frontend** (`dashboard.html`) :
- Nouvelle KPI card dans la Vue d'ensemble (section "Détails temps réel") : "Prochain reset estimé".
  - Compte à rebours dynamique (mise à jour chaque seconde côté JS).
  - Barre de progression circulaire (SVG ou CSS) montrant l'avancement dans le cycle.
  - Si la dernière donnée de reset vient du scraper (`reset_all_models`), l'utiliser directement. Sinon, estimer à partir de la médiane des cycles.
  - Note : "Basé sur une moyenne de Xh Ymin par cycle" si estimé.

**Nouvel endpoint** :
- `GET /api/cycle-stats` → retourne les stats de cycle calculées.

### 4.2 Système de notifications desktop

**Fonctionnalité** : Alerter l'utilisateur via notification Windows (toast) quand un seuil est atteint.

**Implémentation** (`main.py` + `config.py`) :
- Utiliser la lib `plyer` ou `win10toast-click` pour les notifications Windows.
- Alertes configurables dans `config.json` (nouveaux champs) :
  ```json
  {
    "alert_all_models_threshold": 80,
    "alert_sonnet_threshold": 80,
    "alert_on_reset": true,
    "alert_cooldown_minutes": 60
  }
  ```
- Après chaque scrape réussi dans `main.py`, vérifier les seuils et envoyer une notification si dépassé.
- Respecter le cooldown entre notifications (stocker le dernier timestamp d'alerte en mémoire).
- Ajouter les champs dans `DEFAULT_CONFIG` et dans le formulaire Paramètres du dashboard.

### 4.3 Comparateur de plans interactif

**Implémentation frontend** (`dashboard.html`) :
- Nouvel onglet "Plans" dans la sidebar.
- Tableau comparatif généré dynamiquement depuis `GET /api/plans` :
  - Colonnes : Nom, Prix/mois, Modèles, Extended thinking, Priorité.
  - Ligne "Ton usage" : superposer les métriques réelles **mensuelles** (pic max, moyenne du dernier mois complet).
  - Highlight en vert le plan recommandé.
- Simulateur : slider JS "Si mon usage augmentait de X%…" qui recalcule la recommandation.

**Implémentation backend** (`config.py`) :
- Enrichir le dict `PLANS` :
  ```python
  PLANS = {
      "free": {"name": "Free", "price": 0, "models": ["sonnet", "haiku"], "extended_thinking": False, "priority": "low"},
      "pro": {"name": "Pro", "price": 20, "models": ["opus", "sonnet", "haiku"], "extended_thinking": "10 min", "priority": "normal"},
      "max_100": {"name": "Max $100", "price": 100, "models": ["opus", "sonnet", "haiku"], "extended_thinking": "45 min", "priority": "high"},
      "max_200": {"name": "Max $200", "price": 200, "models": ["opus", "sonnet", "haiku"], "extended_thinking": "45 min", "priority": "highest"},
  }
  ```

### 4.4 Export des graphiques en PNG

**Implémentation dans `dashboard.html`** :
- Ajouter un bouton icône 📷 dans le coin supérieur droit de chaque conteneur de graphique.
- Utiliser `chart.toBase64Image()` (Chart.js) pour capturer le rendu.
- Déclencher un téléchargement via `URL.createObjectURL()`.
- Nom du fichier : `claude-monitor_{nom-du-graphique}_{YYYYMMDD}.png`.

### 4.5 Page Paramètres enrichie

**Implémentation dans `dashboard.html`** (onglet Paramètres existant) :
- Ajouter les nouveaux champs de config (seuils de notification, toggle alerte sur reset, cooldown).
- Sauvegarder via `PUT /api/config`.
- Étendre le modèle Pydantic `ConfigUpdate` dans `server.py` avec les nouveaux champs.

---

## Phase 5 — Robustesse & Distribution

### 5.1 Migration de données entre versions

**Problème** : Pas de mécanisme de migration si le schéma SQLite change.

**Implémentation** (`database.py`) :
- Ajouter une table `schema_info` avec un champ `version`.
- Au démarrage (`init_db()`), vérifier la version :
  - Si absente ou < 2.1 → exécuter les migrations séquentiellement.
  - Migration `2.0 → 2.1` : créer la table `monthly_summaries`, la peupler à partir des données existantes dans `usage_entries`.
- Chaque migration est une fonction dans un dict `MIGRATIONS = {"2.0→2.1": migrate_2_0_to_2_1}`.
- Logger les migrations exécutées.

### 5.2 README.md avec screenshots

- Description du projet (3-4 lignes).
- Screenshots des onglets.
- Prérequis : Python 3.11+, Playwright, Chrome installé.
- Installation : `pip install -e .` ou `pip install -r requirements.txt`.
- Lancement : `python -m claude_usage_monitor`.
- Configuration : explication du `config.json`.
- Section "Comment ça marche" : scraping Playwright, stockage SQLite local, aucune donnée envoyée.
- Section "Troubleshooting" : Cloudflare, Chrome doit être fermé pour le scraping, etc.

### 5.3 Améliorer la résilience du scraper

**Changements dans `scraper.py`** :
- Retry configurable (`max_retries` dans config, défaut: 2) avec backoff exponentiel (5s, 15s).
- Catégoriser les échecs dans les logs et la réponse API :
  - `cloudflare_blocked`, `extraction_failed`, `timeout`, `login_required`.
- Exposer dans `/api/status` : `last_scrape_status`, `last_scrape_error`, `last_scrape_timestamp`.

### 5.4 Packaging avec PyInstaller (optionnel)

- `pyinstaller.spec` pour générer un `.exe` Windows standalone.
- Inclure `static/` dans le bundle.
- Tester system tray + Playwright depuis le bundle.

---

## Ordre d'exécution recommandé

| Priorité | Tâche | Fichiers impactés | Effort estimé |
|----------|-------|--------------------|---------------|
| 🔴 P0 | 1.1 Fix graphique Peaks hebdomadaires | `database.py`, `dashboard.html` | ~1h |
| 🔴 P0 | 1.2 Fix typo "Donnees" → "Données" + accents | `dashboard.html` | ~15min |
| 🔴 P0 | 1.3 Fiabiliser scraper Cloudflare | `scraper.py` | ~2h |
| 🟠 P1 | 2.1 Agrégation mensuelle en BDD | `database.py`, `server.py` | ~2h |
| 🟠 P1 | 2.2 Refonte recommandation (logique mensuelle) | `analyzer.py` | ~3h |
| 🟠 P1 | 2.3 Vue d'ensemble : résumé mensuel | `dashboard.html` | ~2h |
| 🟠 P1 | 2.4 Onglet Cycles : peaks mensuels | `dashboard.html` | ~1h30 |
| 🟡 P2 | 3.1 Pagination tableau Historique | `dashboard.html` | ~2h |
| 🟡 P2 | 3.2 Lisibilité axe X Cycles Sonnet | `dashboard.html` | ~30min |
| 🟡 P2 | 3.3 Restructurer bloc recommandation | `dashboard.html` | ~1h |
| 🟡 P2 | 3.4 Indicateur de fraîcheur | `dashboard.html` | ~30min |
| 🟢 P3 | 4.1 Prédiction reset & compte à rebours | `analyzer.py`, `server.py`, `dashboard.html` | ~3h |
| 🟢 P3 | 4.2 Notifications desktop | `main.py`, `config.py`, `server.py` | ~2h |
| 🟢 P3 | 4.3 Comparateur de plans | `config.py`, `dashboard.html` | ~3h |
| 🟢 P3 | 4.4 Export graphiques PNG | `dashboard.html` | ~1h |
| 🟢 P3 | 4.5 Paramètres enrichis | `server.py`, `config.py`, `dashboard.html` | ~1h |
| 🔵 P4 | 5.1 Migration de données | `database.py` | ~2h |
| 🔵 P4 | 5.2 README avec screenshots | `README.md` | ~1h |
| 🔵 P4 | 5.3 Résilience scraper | `scraper.py`, `server.py` | ~2h |
| 🔵 P4 | 5.4 Packaging PyInstaller | `build.py` / `.spec` | ~3h |

**Total estimé : ~33h de développement**

---

## Notes pour l'implémentation

- **Architecture** : C'est une app desktop Python (FastAPI + Playwright + system tray), PAS une extension Chrome. Le frontend est un fichier HTML monolithique servi par FastAPI.
- **Philosophie mensuelle** : Les abonnements Claude sont mensuels. Toute recommandation de plan doit s'appuyer sur au moins 1 mois complet de données. Les vues hebdomadaires et les cycles restent utiles comme détail, mais le mois est l'unité de décision.
- **Ne pas modifier** le mécanisme de scraping fondamental (Playwright + profil Chrome) — améliorer sa résilience uniquement.
- **Dashboard** : toutes les modifications frontend sont dans `static/dashboard.html`. Le dashboard communique avec le backend via `fetch('/api/...')`.
- **Config** : les nouvelles options doivent être ajoutées dans `DEFAULT_CONFIG` (config.py), dans `ConfigUpdate` (server.py), et dans le formulaire Paramètres du dashboard.
- **Base de données** : SQLite via `database.py`. Toute nouvelle table ou colonne doit passer par `init_db()` avec migration. La migration 2.0→2.1 doit peupler `monthly_summaries` à partir des données existantes.
- **Accents** : Tous les labels visibles du dashboard doivent être en français correct avec accents (Données, Paramètres, Vélocité, Détectés, etc.).
- **OS** : l'app tourne principalement sur Windows. Les notifications doivent utiliser une lib compatible Windows.
- **Commiter** après chaque tâche avec un message conventionnel (`fix:`, `feat:`, `style:`, `docs:`).

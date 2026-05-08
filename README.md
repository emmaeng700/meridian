# 🔭 Meridian — Data Observability Platform

> **Monitor your data pipelines for anomalies, schema drift, null-rate spikes, and volume drops — before your users notice.**

Meridian is an open-source, production-grade data observability platform that continuously profiles your databases and files, learns statistical baselines, and alerts you to data quality issues using ML-powered anomaly detection.

---

## ✨ Features

- 📊 **Automatic Profiling** — Profiles PostgreSQL tables and CSV/Parquet files: row counts, null rates, distinct counts, percentiles, and string statistics
- 🤖 **ML Anomaly Detection** — Z-score, IQR, and Isolation Forest detectors flag anomalies automatically
- 🔁 **Schema Drift Detection** — Detects added/removed columns and type changes between profile runs
- 📈 **Historical Baselines** — Learns what "normal" looks like over time and flags deviations
- 🚨 **Severity Scoring** — Every anomaly is rated critical / high / medium / low with a full explanation
- 💯 **Health Scores** — Each table gets a 0–100 health score updated after every profile run
- 🖥️ **Live Dashboard** — Streamlit multi-page dashboard with Plotly dark-themed charts
- 🔌 **REST API** — Full FastAPI backend with OpenAPI docs at `/docs`
- 🐳 **Docker-first** — One command to run the entire stack

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Meridian Stack                           │
│                                                             │
│   ┌──────────────┐     REST API      ┌──────────────────┐  │
│   │  Streamlit   │ ───────────────►  │    FastAPI       │  │
│   │  Dashboard   │ ◄───────────────  │    Backend       │  │
│   │  :8501       │                   │    :8000         │  │
│   └──────────────┘                   └────────┬─────────┘  │
│                                               │             │
│                                    ┌──────────▼──────────┐ │
│                                    │    PostgreSQL 16     │ │
│                                    │    :5432             │ │
│                                    └─────────────────────-┘ │
│                                                             │
│   ┌───────────────────────────────────────────────────┐    │
│   │  Profilers                  Detectors             │    │
│   │  ├── PostgresProfiler       ├── ZScoreDetector    │    │
│   │  └── CSVProfiler            ├── IQRDetector       │    │
│   │                             ├── IsolationForest   │    │
│   │                             └── SchemaDrift       │    │
│   └───────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites
- Docker and Docker Compose

### 1. Clone the repo

```bash
git clone https://github.com/your-org/meridian.git
cd meridian
```

### 2. Start the full stack

```bash
docker-compose up --build
```

This starts:
- **PostgreSQL** on port `5432`
- **Meridian Backend** (FastAPI) on port `8000`
- **Meridian Dashboard** (Streamlit) on `http://localhost:8501`

### 3. Open the dashboard

```
http://localhost:8501
```

API docs available at:
```
http://localhost:8000/docs
```

### 4. Seed demo data (optional)

Load NYC Yellow Taxi data with intentional anomalies pre-injected:

```bash
docker-compose --profile seed up seeder
```

Or locally (after the stack is running):

```bash
cd backend
pip install -r requirements.txt
python seed_demo.py --api-url http://localhost:8000/api/v1
```

---

## 🔧 Local Development

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Set up environment
cp ../.env.example .env
# Edit .env with your local DB URL

uvicorn app.main:app --reload --port 8000
```

### Dashboard

```bash
cd dashboard
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

API_URL=http://localhost:8000/api/v1 streamlit run app.py
```

---

## 📡 API Reference

### Sources

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/sources` | List all data sources |
| `POST` | `/api/v1/sources` | Add a new data source |
| `GET` | `/api/v1/sources/{id}` | Get source details |
| `DELETE` | `/api/v1/sources/{id}` | Soft-delete a source |
| `POST` | `/api/v1/sources/{id}/profile` | Trigger a profile run |
| `GET` | `/api/v1/sources/{id}/tables` | List tables in a DB source |

### Profiles

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/profiles` | List profiles (filterable by source, table) |
| `GET` | `/api/v1/profiles/{id}` | Get a single profile with all column stats |

### Anomalies

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/anomalies` | List anomalies (filterable by source, severity, type, ack) |
| `GET` | `/api/v1/anomalies/summary` | Aggregated counts by severity, type, source |
| `PATCH` | `/api/v1/anomalies/{id}/acknowledge` | Acknowledge or un-acknowledge an anomaly |

### Reports

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/reports/{source_id}` | Full quality report for a source |

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Service health check |

---

## 🧠 How It Works

### 1. Profiling
When you trigger a profile run, Meridian:
- Connects to your data source (PostgreSQL via `psycopg2`, CSV/Parquet via `pandas`)
- For each table/file: counts rows, computes per-column null rates, distinct counts, and numeric statistics (min, max, mean, std, percentiles)
- Saves the result as a `TableProfile` + `ColumnProfile` records in PostgreSQL

### 2. Anomaly Detection
After profiling, three detectors run against the new profile vs. historical profiles:

**Z-Score Detector**: Computes mean + standard deviation of each metric across recent history. Flags anything more than 3σ from the mean.

**IQR Detector**: Uses the interquartile range (Q1–Q3) to flag outliers beyond `Q1 - 1.5·IQR` or `Q3 + 1.5·IQR`.

**Isolation Forest**: Trains a scikit-learn `IsolationForest` on a feature vector `[row_count, avg_null_rate, avg_distinct_rate, avg_mean, avg_std]`. Requires ≥5 historical profiles.

**Schema Drift Detector**: Compares the column list and types between the current and previous profile. Added columns → `low`. Removed columns → `critical`. Type changes → `high`.

### 3. Health Score
After each profile run, a health score is computed:

```
health_score = max(0, 100 - critical×25 - high×10 - medium×5)
```

---

## 📸 Screenshots

> *Run `docker-compose up --build && docker-compose --profile seed up seeder` to populate demo data, then visit http://localhost:8501*

- **Sources** — Health badges, profile triggers, add new sources
- **Profiles** — Row count trends, null rate per column over time, column quality grid
- **Anomalies** — Live feed with severity badges, expected vs actual values, one-click acknowledge
- **Reports** — Health gauge, anomaly donut chart, column quality heatmap

---

## 🤝 Contributing

Contributions are very welcome!

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes with tests where possible
4. Run the linter: `ruff check backend/`
5. Submit a pull request

### Adding a new detector

1. Create `backend/app/detectors/my_detector.py`
2. Implement a class with a `detect(current_profile, historical_profiles, source_id, table_profile_id) -> list[dict]` method
3. Add it to `backend/app/detectors/__init__.py`
4. Call it inside `_run_detectors()` in `backend/app/api/sources.py`

### Adding a new profiler

1. Create `backend/app/profiler/my_profiler.py`
2. Subclass `BaseProfiler` and implement `list_tables()` and `profile_table()`
3. Add a new `SourceType` value and wire it into `_run_profiler_sync()` in `sources.py`

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

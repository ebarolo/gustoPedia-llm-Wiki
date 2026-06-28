# GustoPedia Service

GustoPedia is a high-performance Python FastAPI service designed to orchestrate social media recipe ingestion and semantically organize recipe information into a dynamic, self-healing wiki. It leverages Google Gemini for structured extraction and markdown generation, Cloudflare R2 for media hosting, and Supabase for persistent storage and hybrid semantic search.

---

## 🌟 Key Features

### 1. Social Ingestion (`social_ingestion`)
- **Multi-Platform Scraper**: Sanitizes and scrapes Instagram (reels, posts, stories) and YouTube (shorts, videos) URLs using specialized RapidAPI endpoints.
- **Media Processor**: Downloads target media and uploads it directly to a Cloudflare R2 (S3-compatible) bucket, preparing it for AI analysis.
- **Gemini-Powered Extraction**: Uses the Google Gemini API to analyze raw media (videos, images) along with text captions to extract fully structured recipe details (ingredients, step-by-step instructions, prep time, difficulty, etc.) into type-safe models.
- **AI Thumbnail Generation**: Automatically generates illustrative preview images for recipes using the Gemini Imagen API and hosts them on R2.
- **Database Synchronization**: Automatically saves the extracted recipe data, links, ingredients, and tags to Supabase.

### 2. Wiki Ingestion System (`wiki`)
- **Queue-Based Execution**: A job manager handles background tasks to process new recipes into the wiki database.
- **Two-Step AI Wiki Pipeline**:
  1. **Analysis**: Uses Gemini to compare a incoming recipe with the current index of wiki pages to determine which pages should be updated or created (e.g., adding cooking techniques, ingredient guides, or regional articles).
  2. **Generation**: Generates or updates markdown files for the target wiki pages based on predefined structured layouts.
- **Self-Healing Wiki Links**: Parses wiki syntax (e.g. `[[wikilink]]`) and automatically repairs dangling links by creating placeholder stubs to maintain internal referential integrity.
- **Vector Re-indexing**: Automatically generates and stores vector embeddings for updated wiki pages to enable semantic discovery.
- **Backfill API**: Bulk-queues existing recipes to rebuild or refresh the wiki index.

### 3. Hybrid Semantic Search
- Implements a hybrid search engine combining Postgres full-text keyword matching and pgvector similarity embeddings.
- Combines search results using **Reciprocal Rank Fusion (RRF)** to provide accurate, contextual retrieval for the user-facing app and admin dashboard.

### 4. Serverless-Optimized Queue Worker
- Includes a synchronous, time-budgeted worker drain process (`/wiki/process-queue`) designed specifically for serverless CPU models (like **Google Cloud Run**). It ensures that tasks are executed during active HTTP handler requests so that serverless CPU throttling does not freeze background processes.

---

## 📂 Project Structure

```text
├── Dockerfile              # Production Docker configuration
├── main.py                 # FastAPI application entrypoint and middleware
├── requirements.txt        # Package dependencies
├── pytest.ini              # Pytest configuration
├── social_ingestion/       # Social media scraping and recipe extraction
│   ├── scraper.py          # RapidAPI scrapers for Instagram & YouTube
│   ├── media_processor.py  # R2 file uploader (boto3 client)
│   ├── recipe_extractor.py # Gemini multimodal analyzer & Imagen client
│   ├── recipe_writer.py    # Database writer and text embedding generator
│   └── service.py          # Orchestrates the ingestion pipeline
├── wiki/                   # Wiki structure and page generation
│   ├── analyzer.py         # Determines which wiki pages to edit/create
│   ├── generator.py        # Generates markdown page content via Gemini
│   ├── parser.py           # Validates generated block layouts
│   ├── repair.py           # Self-healing link resolver (stub generator)
│   ├── search.py           # Hybrid search with Reciprocal Rank Fusion (RRF)
│   ├── worker.py           # Time-budgeted queue worker
│   └── service.py          # Orchestrates the wiki generation pipeline
├── shared/                 # Common helpers
│   ├── auth.py             # Simple shared-secret API authentication guard
│   ├── embeddings.py       # Interface for Gemini text-embedding-004
│   ├── retry.py            # Async retry decorator with exponential backoff
│   └── supabase.py         # Supabase client initializer
└── tests/                  # Test suite
    └── unit/               # Unit tests covering scraper, retry, and models
```

---

## ⚙️ Configuration & Environment

The service reads configuration parameters from environment variables. Copy `.env.example` to `.env` and fill in the secrets:

```bash
cp .env.example .env
```

### Required Environment Variables

| Variable | Description |
|---|---|
| `SUPABASE_URL` | Your Supabase project URL. |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role key for admin access (required to write to restricted tables). |
| `GEMINI_API_KEY` | Google Gemini API key (supports multimodal models and embeddings). |
| `GUSTOPEDIA_API_SHARED_SECRET` | Header secret token to authorize requests (leave empty to disable auth). |
| `RAPID_API_KEY` | RapidAPI key used to authenticate Instagram and YouTube downloaders. |
| `R2_ACCOUNT_ID` | Cloudflare Account ID for R2 storage. |
| `R2_ACCESS_KEY_ID` | Cloudflare R2 Access Key ID. |
| `R2_SECRET_ACCESS_KEY` | Cloudflare R2 Secret Access Key. |
| `R2_BUCKET_NAME` | Cloudflare R2 Bucket Name for media. |
| `R2_PUBLIC_DOMAIN` | The public CDN URL serving files uploaded to your R2 bucket. |
| `LOG_LEVEL` | Logging verbosity (e.g. `INFO`, `DEBUG`, `WARN`). |

---

## 🚀 Local Development

### 1. Prerequisites
Ensure you have **Python 3.12+** installed on your system.

### 2. Set Up Virtual Environment & Dependencies
```bash
# Create virtual environment
python3 -m venv .venv

# Activate virtual environment
source .venv/bin/activate

# Install required packages
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Run Unit Tests
To verify your installation and mocks:
```bash
pytest
```

### 4. Run the Dev Server
Start the local FastAPI development server:
```bash
uvicorn main:app --reload --port 8080
```
Open [http://localhost:8080/docs](http://localhost:8080/docs) in your browser to explore the Swagger UI documentation.

---

## 🐳 Deployment

### Build Docker Image
You can package the application into a Docker container. The service listens on port `8080` by default:

```bash
# Build the image
docker build -t gustopedia-service .

# Run the container locally
docker run --env-file .env -p 8080:8080 gustopedia-service
```

### Deploy to Google Cloud Run
This service is designed to work seamlessly on **Google Cloud Run** using a serverless container workflow:

1. **Build and push** the image to Google Artifact Registry:
   ```bash
   gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/gustopedia
   ```

2. **Deploy** to Cloud Run:
   ```bash
   gcloud run deploy gustopedia \
     --image gcr.io/YOUR_PROJECT_ID/gustopedia \
     --platform managed \
     --region europe-west1 \
     --allow-unauthenticated
   ```

3. **Important architectural note on Cloud Run CPU allocation:**
   By default, Cloud Run instances throttle CPU when no HTTP requests are actively processing. Therefore, standard background task pools (like Celery or raw asyncio tasks) might freeze mid-execution. To solve this, the `/wiki/process-queue` endpoint executes the worker queue synchronously and exits within a specified time budget (usually 55 seconds), returning the execution results directly in the response. A scheduler (like Google Cloud Scheduler or Supabase Edge Functions webhook triggers) should trigger this endpoint periodically to drain the queue.

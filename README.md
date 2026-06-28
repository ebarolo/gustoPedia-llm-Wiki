# GustoPedia Wiki LLM

GustoPedia Wiki è un servizio Python FastAPI ad alte prestazioni progettato per orchestrare l'acquisizione di ricette dai social media e organizzare semanticamente le informazioni sulle ricette in una wiki dinamica e auto-riparante. Sfrutta Google Gemini per l'estrazione strutturata e la generazione di markdown, Cloudflare R2 per l'hosting dei file multimediali, e Supabase per l'archiviazione persistente e la ricerca semantica ibrida.

---

## 🌟 Funzionalità Principali

### 1. Ingestione Social (`social_ingestion`)
- **Scraper Multi-Piattaforma**: Pulisce ed estrae dati da URL di Instagram (reel, post, storie) e YouTube (shorts, video) utilizzando endpoint RapidAPI specializzati.
- **Processore Multimediale**: Scarica i contenuti multimediali estratti e li carica direttamente in un bucket Cloudflare R2 (compatibile con S3), preparandoli per l'analisi AI.
- **Estrazione basata su Gemini**: Utilizza l'API Google Gemini per analizzare i media grezzi (video, immagini) insieme alle didascalie di testo per estrarre dettagli di ricette completamente strutturati (ingredienti, istruzioni passo-passo, tempo di preparazione, difficoltà, ecc.) in modelli type-safe.
- **Generazione AI delle Miniature (Thumbnail)**: Genera automaticamente immagini di anteprima illustrative per le ricette utilizzando l'API Gemini Imagen e le ospita su R2.
- **Sincronizzazione del Database**: Salva automaticamente i dati delle ricette estratte, i link, gli ingredienti e i tag su Supabase.

### 2. Wiki Ingestion System (`Karpathy LLM Wiki style`)
- **Esecuzione basata su coda**: Un gestore di processi (job manager) gestisce le attività in background per elaborare le nuove ricette nel database della wiki.
- **Pipeline Wiki AI in due passaggi**:
  1. **Analisi**: Utilizza Gemini per confrontare una ricetta in arrivo con l'indice corrente delle pagine della wiki per determinare quali pagine debbano essere aggiornate o create (ad esempio, aggiungendo tecniche di cottura, guide agli ingredienti o articoli regionali).
  2. **Generazione**: Genera o aggiorna i file markdown per le pagine wiki di destinazione in base a layout strutturati predefiniti.
- **Collegamenti Wiki Auto-Riparanti**: Analizza la sintassi della wiki (ad es. `[[wikilink]]`) e ripara automaticamente i collegamenti interrotti creando stub segnaposto per mantenere l'integrità referenziale interna.
- **Reindicizzazione Vettoriale**: Genera e memorizza automaticamente gli embedding vettoriali per le pagine wiki aggiornate per abilitare la scoperta semantica.
- **API di Backfill**: Mette in coda in blocco le ricette esistenti per ricostruire o aggiornare l'indice della wiki.

### 3. Ricerca Semantica Ibrida
- Implementa un motore di ricerca ibrido che combina la corrispondenza delle parole chiave full-text di Postgres e gli embedding di similarità di pgvector.
- Combina i risultati di ricerca utilizzando la **Reciprocal Rank Fusion (RRF)** per fornire un recupero accurato e contestuale per l'app rivolta agli utenti e la dashboard di amministrazione.

### 4. Coda di Lavoro Ottimizzata per Serverless
- Include un processo sincrono di svuotamento dei nodi di lavoro con budget di tempo (`/wiki/process-queue`) progettato specificamente per modelli CPU serverless (come **Google Cloud Run**). Garantisce che le attività vengano eseguite durante le richieste attive degli handler HTTP, in modo che la limitazione della CPU serverless non congeli i processi in background.

---

## 📂 Struttura del Progetto

```text
├── Dockerfile              # Configurazione Docker di produzione
├── main.py                 # Punto di ingresso dell'applicazione FastAPI e middleware
├── requirements.txt        # Dipendenze del pacchetto
├── pytest.ini              # Configurazione Pytest
├── social_ingestion/       # Scraping dei social media ed estrazione delle ricette
│   ├── scraper.py          # Scraper RapidAPI per Instagram e YouTube
│   ├── media_processor.py  # Caricatore di file R2 (client boto3)
│   ├── recipe_extractor.py # Analizzatore multimodale Gemini e client Imagen
│   ├── recipe_writer.py    # Scrittore del database e generatore di embedding di testo
│   └── service.py          # Orchestra la pipeline di ingestione
├── wiki/                   # Struttura della wiki e generazione delle pagine
│   ├── analyzer.py         # Determina quali pagine della wiki modificare/creare
│   ├── generator.py        # Genera il contenuto delle pagine markdown tramite Gemini
│   ├── parser.py           # Valida i layout dei blocchi generati
│   ├── repair.py           # Risolutore di collegamenti auto-riparante (generatore di stub)
│   ├── search.py           # Ricerca ibrida con Reciprocal Rank Fusion (RRF)
│   ├── worker.py           # Lavoratore di coda (worker) con budget di tempo
│   └── service.py          # Orchestra la pipeline di generazione della wiki
├── shared/                 # Helper comuni
│   ├── auth.py             # Semplice protezione dell'autenticazione API con segreto condiviso
│   ├── embeddings.py       # Interfaccia per Gemini text-embedding-004
│   ├── retry.py            # Decoratore di riprovo asincrono con backoff esponenziale
│   └── supabase.py         # Inizializzatore del client Supabase
└── tests/                  # Suite di test
    └── unit/               # Test unitari che coprono scraper, retry e modelli
```

---

## ⚙️ Configurazione e Ambiente

Il servizio legge i parametri di configurazione dalle variabili d'ambiente. Copia `.env.example` in `.env` e inserisci i segreti:

```bash
cp .env.example .env
```

### Variabili d'Ambiente Richieste

| Variabile | Descrizione |
|---|---|
| `SUPABASE_URL` | L'URL del tuo progetto Supabase. |
| `SUPABASE_SERVICE_ROLE_KEY` | Chiave del ruolo di servizio per l'accesso amministratore (richiesta per scrivere su tabelle con restrizioni). |
| `GEMINI_API_KEY` | Chiave API di Google Gemini (supporta modelli multimodali ed embedding). |
| `GUSTOPEDIA_API_SHARED_SECRET` | Token segreto nell'header per autorizzare le richieste (lasciare vuoto per disabilitare l'autenticazione). |
| `RAPID_API_KEY` | Chiave RapidAPI utilizzata per autenticare i downloader di Instagram e YouTube. |
| `R2_ACCOUNT_ID` | ID account Cloudflare per l'archiviazione R2. |
| `R2_ACCESS_KEY_ID` | ID chiave di accesso Cloudflare R2. |
| `R2_SECRET_ACCESS_KEY` | Chiave di accesso segreta Cloudflare R2. |
| `R2_BUCKET_NAME` | Nome del bucket Cloudflare R2 per i media. |
| `R2_PUBLIC_DOMAIN` | L'URL CDN pubblico che serve i file caricati sul tuo bucket R2. |
| `LOG_LEVEL` | Livello di dettaglio dei log (es. `INFO`, `DEBUG`, `WARN`). |

---

## 🚀 Sviluppo Locale

### 1. Prerequisiti
Assicurati di avere **Python 3.12+** installato sul tuo sistema.

### 2. Configurare l'Ambiente Virtuale e le Dipendenze
```bash
# Crea l'ambiente virtuale
python3 -m venv .venv

# Attiva l'ambiente virtuale
source .venv/bin/activate

# Installa i pacchetti richiesti
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Eseguire i Test Unitari
Per verificar l'installazione e i mock:
```bash
pytest
```

### 4. Avviare il Server di Sviluppo
Avvia il server di sviluppo FastAPI locale:
```bash
uvicorn main:app --reload --port 8080
```
Apri [http://localhost:8080/docs](http://localhost:8080/docs) nel tuo browser per esplorare la documentazione dell'interfaccia utente Swagger.

---

## 🐳 Distribuzione (Deployment)

### Creare l'Immagine Docker
È possibile pacchettizzare l'applicazione in un contenitore Docker. Il servizio ascolta sulla porta `8080` per impostazione predefinita:

```bash
# Crea l'immagine
docker build -t gustopedia-service .

# Esegui il contenitore localmente
docker run --env-file .env -p 8080:8080 gustopedia-service
```

### Distribuire su Google Cloud Run
Questo servizio è progettato per funzionare perfettamente su **Google Cloud Run** utilizzando un flusso di lavoro con contenitori serverless:

1. **Compila e invia** l'immagine a Google Artifact Registry:
   ```bash
   gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/gustopedia
   ```

2. **Esegui la distribuzione** su Cloud Run:
   ```bash
   gcloud run deploy gustopedia \
     --image gcr.io/YOUR_PROJECT_ID/gustopedia \
     --platform managed \
     --region europe-west1 \
     --allow-unauthenticated
   ```

3. **Nota architetturale importante sull'allocazione della CPU in Cloud Run:**
   Per impostazione predefinita, le istanze di Cloud Run limitano (throttle) la CPU quando non ci sono richieste HTTP in fase di elaborazione attiva. Pertanto, i pool di attività in background standard (come Celery o attività asyncio grezze) potrebbero congelarsi a metà esecuzione. Per risolvere questo problema, l'endpoint `/wiki/process-queue` esegue la coda del worker in modo sincrono e termina entro un budget temporale specificato (solitamente 55 secondi), restituendo i risultati dell'esecuzione direttamente nella risposta. Un pianificatore (come Google Cloud Scheduler o trigger webhook di Supabase Edge Functions) dovrebbe attivare periodicamente questo endpoint per svuotare la coda.

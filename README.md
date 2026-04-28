# NGO Adapter — Zero Cost Setup
## No GCP billing. No credit card. Nothing.

### Services Used
| Service | Cost | Card needed? |
|---------|------|-------------|
| Gemini API | Free | No |
| Supabase (DB + pgvector) | Free | No |
| OpenStreetMap | Free forever | No |

### Setup (15 mins total)

**1. Gemini API — 2 mins**
- aistudio.google.com → Sign in → Get API Key → Copy

**2. Supabase — 10 mins**
- supabase.com → Sign up with GitHub → New Project
- Region: Southeast Asia → set any DB password
- Wait 2 mins → Settings → Database → copy Host + Password
- SQL Editor → paste this and run:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS submissions (
    id TEXT PRIMARY KEY, raw_input TEXT, location TEXT,
    worker_name TEXT, translated JSONB, resources JSONB,
    similar JSONB DEFAULT '[]', resolved BOOLEAN DEFAULT FALSE,
    resolution_notes TEXT, created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS crisis_embeddings (
    id TEXT PRIMARY KEY, summary TEXT NOT NULL,
    crisis_tags JSONB, resolution_notes TEXT,
    embedding VECTOR(768), created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);
```

**3. Run**
```bash
pip install -r requirements.txt
cp .env.example .env
# fill GEMINI_API_KEY + SUPABASE_* values
python app.py
# open http://localhost:5000
```

### That's it. No GCP. No billing. No card.

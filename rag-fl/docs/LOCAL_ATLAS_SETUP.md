# MongoDB Local Atlas Setup Guide

This guide explains how to set up RAG-FL with **MongoDB Local Atlas** for native `$vectorSearch` support.

## Overview

| Feature | Docker MongoDB (Old) | Local Atlas (New) |
|---------|---------------------|-------------------|
| `$vectorSearch` | ❌ Not supported | ✅ **Native support** |
| Vector Index | None | HNSW ANN index |
| Search Algorithm | Python cosine similarity | MongoDB Atlas `$vectorSearch` |
| Search Speed | 200-500ms | <100ms |
| Production Parity | Low | **High** |

## Prerequisites

1. **Atlas CLI** - Install:
   ```bash
   # macOS
   brew install mongodb-atlas-cli
   
   # Windows
   winget install MongoDB.AtlasCLI
   
   # Linux
   # See: https://www.mongodb.com/docs/atlas/cli/install-atlas-cli/
   ```

2. **Docker** - Must be running

3. **mongosh** (optional) - For connecting to MongoDB:
   ```bash
   brew install mongosh
   ```

## Quick Start

### Option 1: Automated Setup (Recommended)

Run the setup script:

```bash
cd /Users/rahmad/work/freelance/raif-project/vector-embedding-mongodb/rag-fl
./scripts/setup-local-atlas.sh
```

This will:
1. Check prerequisites
2. Create Local Atlas deployment (`localRS`)
3. Create vector search index (`embedding_index`)
4. Verify the connection

### Option 2: Manual Setup

#### Step 1: Create Local Atlas Deployment

```bash
# Interactive setup
atlas deployments setup

# Or non-interactive
atlas deployments setup localRS --type local --version 7.0.12 --port 27017
```

#### Step 2: Create Vector Search Index

```bash
atlas deployments search indexes create \
  --file infra/atlas/vector-index.json \
  --deploymentName localRS
```

#### Step 3: Verify

```bash
# Check deployment status
atlas deployments list

# Connect to MongoDB
atlas deployments connect localRS
```

## Configuration

### Update .env File

Copy the example and update:

```bash
cp .env.example .env
```

Edit `.env`:

```bash
# MongoDB Connection (Local Atlas)
MONGODB_URI=mongodb://localhost:27017/ragfl?replicaSet=localRS
MONGODB_DB=ragfl

# Enable Atlas Vector Search
VECTOR_SEARCH_BACKEND=atlas

# Other settings...
GOOGLE_API_KEY=your_key_here
INPUT_DIR=/path/to/your/input
OUTPUT_DIR=/path/to/your/output
```

### Start Services

```bash
# Start Docker services (without MongoDB)
docker compose up -d

# Check status
docker compose ps
```

## Verification

### Test Vector Search

1. Upload a document via UI: http://localhost:3001

2. Wait for processing (check logs: `docker compose logs -f rag-fl`)

3. Test search:
   ```bash
   curl -X POST http://localhost:8004/search \
     -H "Content-Type: application/json" \
     -d '{"query":"customer churn rate","top_k":5}'
   ```

### Verify Vector Index

```bash
# Connect to MongoDB
atlas deployments connect localRS

# In mongosh, check index
use ragfl
db.doc_embeddings.getIndexes()
```

You should see `embedding_index` of type `vectorSearch`.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        RAG-FL System                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌────────────┐    ┌────────────┐    ┌────────────┐            │
│  │ Ingestion  │───▶│  RAG-FL    │───▶│  Next.js   │            │
│  │  Service   │    │  Pipeline  │    │     UI     │            │
│  │  :8001     │    │   :8004    │    │   :3001    │            │
│  └────────────┘    └────────────┘    └────────────┘            │
│         │                  │                                     │
│         │                  │                                     │
│         ▼                  ▼                                     │
│  ┌──────────────────────────────────┐    ┌────────────┐        │
│  │   MongoDB Local Atlas            │    │  Fake GCS  │        │
│  │   localhost:27017                │    │   :4443    │        │
│  │                                  │    └────────────┘        │
│  │   ✓ $vectorSearch enabled       │    ┌────────────┐        │
│  │   ✓ HNSW vector index           │    │   Redis    │        │
│  │   ✓ 768-dim cosine similarity   │    │   :6379    │        │
│  └──────────────────────────────────┘    └────────────┘        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Migration from Docker MongoDB

If you have existing data in Docker MongoDB:

```bash
# 1. Export data from Docker MongoDB (if running)
docker exec ragfl-mongo mongodump --out=/data/backup --db=ragfl

# 2. Stop Docker MongoDB
docker compose stop mongo mongo-init mongo-express

# 3. Setup Local Atlas
./scripts/setup-local-atlas.sh

# 4. Import data to Local Atlas
mongorestore --host localhost --port 27017 --db=ragfl dump/ragfl

# 5. Start remaining services
docker compose up -d
```

## Troubleshooting

### Issue: "connection refused" to MongoDB

**Cause:** Local Atlas not running

**Fix:**
```bash
# Check deployment status
atlas deployments list

# Start if paused
atlas deployments start localRS
```

### Issue: "vector search index not found"

**Cause:** Index not created

**Fix:**
```bash
# Create index manually
atlas deployments search indexes create \
  --file infra/atlas/vector-index.json \
  --deploymentName localRS
```

### Issue: Port 27017 already in use

**Cause:** Another MongoDB instance running

**Fix:**
```bash
# Find and kill process
lsof -ti:27017 | xargs kill -9

# Or use different port
atlas deployments setup localRS --port 27018
# Update MONGODB_URI in .env accordingly
```

### Issue: "atlas deployments command not found"

**Cause:** Atlas CLI not installed or not in PATH

**Fix:**
```bash
# macOS
brew install mongodb-atlas-cli

# Verify
atlas --version
```

## Useful Commands

```bash
# Deployment management
atlas deployments list                    # List deployments
atlas deployments connect localRS         # Connect with mongosh
atlas deployments pause localRS           # Pause to save resources
atlas deployments start localRS           # Start paused deployment
atlas deployments delete localRS          # Delete deployment

# Vector search indexes
atlas deployments search indexes list --deploymentName localRS
atlas deployments search indexes describe embedding_index --deploymentName localRS

# Logs
atlas deployments logs localRS
```

## Production Migration

When ready for production:

1. Create MongoDB Atlas cluster (M10+ for vector search)
2. Create vector search index via Atlas UI
3. Update `.env`:
   ```bash
   MONGODB_URI=mongodb+srv://user:pass@cluster.mongodb.net/ragfl
   VECTOR_SEARCH_BACKEND=atlas
   ENVIRONMENT=production
   ```
4. No code changes needed!

## References

- [MongoDB Atlas Local Documentation](https://www.mongodb.com/docs/atlas/cli/atlas-cli-deploy-local/)
- [Atlas Vector Search](https://www.mongodb.com/docs/atlas/atlas-vector-search/)
- [Vector Search Index Type](https://www.mongodb.com/docs/atlas/atlas-vector-search/vector-search-type/)

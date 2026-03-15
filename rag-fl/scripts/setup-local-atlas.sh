#!/bin/bash
# ================================================================================
# Setup MongoDB Local Atlas for RAG-FL
# ================================================================================
# This script sets up MongoDB Local Atlas with vector search support.
# Run this BEFORE starting Docker Compose services.
# ================================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}══════════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  RAG-FL: MongoDB Local Atlas Setup${NC}"
echo -e "${BLUE}══════════════════════════════════════════════════════════════════${NC}"
echo ""

# ── Check prerequisites ───────────────────────────────────────────────────────

echo -e "${YELLOW}▶ Checking prerequisites...${NC}"

if ! command -v atlas &> /dev/null; then
    echo -e "${RED}✗ Atlas CLI not found.${NC}"
    echo ""
    echo "Please install Atlas CLI:"
    echo "  macOS:    brew install mongodb-atlas-cli"
    echo "  Windows:  winget install MongoDB.AtlasCLI"
    echo "  Linux:    See https://www.mongodb.com/docs/atlas/cli/install-atlas-cli/"
    exit 1
fi

echo -e "${GREEN}✓ Atlas CLI found${NC}"

if ! command -v docker &> /dev/null; then
    echo -e "${RED}✗ Docker not found.${NC}"
    echo "Please install Docker Desktop or Docker Engine"
    exit 1
fi

echo -e "${GREEN}✓ Docker found${NC}"

# ── Configuration ────────────────────────────────────────────────────────────

DEPLOYMENT_NAME="localRS"
MONGODB_VERSION="7.0.12"
MONGODB_PORT="27017"
DB_NAME="ragfl"
VECTOR_INDEX_FILE="infra/atlas/vector-index.json"

echo ""
echo -e "${YELLOW}▶ Configuration:${NC}"
echo "  Deployment name: $DEPLOYMENT_NAME"
echo "  MongoDB version: $MONGODB_VERSION"
echo "  Port: $MONGODB_PORT"
echo "  Database: $DB_NAME"
echo ""

# ── Check if deployment already exists ───────────────────────────────────────

echo -e "${YELLOW}▶ Checking existing deployments...${NC}"

# Check using new 'atlas local' command
EXISTING_DEPLOYMENT=$(atlas local list 2>/dev/null | grep "$DEPLOYMENT_NAME" || true)

if [ -n "$EXISTING_DEPLOYMENT" ]; then
    echo -e "${GREEN}✓ Deployment '$DEPLOYMENT_NAME' already exists${NC}"
    echo ""
    echo -e "${YELLOW}  To recreate it, run first:${NC}"
    echo "    atlas local stop $DEPLOYMENT_NAME"
    echo "    atlas local delete $DEPLOYMENT_NAME"
    echo ""
else
    echo -e "${YELLOW}▶ Creating Local Atlas deployment...${NC}"
    echo "  This may take 2-3 minutes..."
    echo ""
    
    # Use new 'atlas local setup' command
    atlas local setup "$DEPLOYMENT_NAME" \
        --mongodbVersion "$MONGODB_VERSION" \
        --port "$MONGODB_PORT" \
        --force || {
            echo -e "${RED}✗ Failed to create deployment${NC}"
            echo "Trying alternative setup method..."
            atlas local start "$DEPLOYMENT_NAME" \
                --mongodbVersion "$MONGODB_VERSION" \
                --port "$MONGODB_PORT"
        }
    
    echo ""
    echo -e "${GREEN}✓ Deployment '$DEPLOYMENT_NAME' created${NC}"
fi

# ── Wait for deployment to be ready ──────────────────────────────────────────

echo ""
echo -e "${YELLOW}▶ Waiting for deployment to be ready...${NC}"

for i in {1..30}; do
    STATUS=$(atlas local list 2>/dev/null | grep "$DEPLOYMENT_NAME" | awk '{print $2}' || true)
    if [ "$STATUS" = "RUNNING" ] || [ "$STATUS" = "IDLE" ]; then
        echo -e "${GREEN}✓ Deployment is ready${NC}"
        break
    fi
    echo "  Waiting... ($i/30)"
    sleep 5
done

# ── Create collections and indexes ───────────────────────────────────────────

echo ""
echo -e "${YELLOW}▶ Setting up database collections and indexes...${NC}"

MONGODB_URI="mongodb://localhost:$MONGODB_PORT/$DB_NAME?replicaSet=$DEPLOYMENT_NAME"

# Create collections first (required before creating vector search indexes)
echo "  Creating required collections..."

if command -v mongosh &> /dev/null; then
    mongosh "$MONGODB_URI" --eval "
        // Create collections if they don't exist
        db.createCollection('documents');
        db.createCollection('doc_embeddings');
        db.createCollection('page_profiles');
        db.createCollection('citation_cache');
        
        // Create regular indexes
        db.documents.createIndex({ doc_id: 1 }, { unique: true });
        db.documents.createIndex({ content_hash: 1 });
        db.doc_embeddings.createIndex({ doc_id: 1 });
        db.doc_embeddings.createIndex({ chunk_id: 1 }, { unique: true });
        db.page_profiles.createIndex({ doc_id: 1, page_number: 1 });
        db.citation_cache.createIndex({ cache_key: 1 }, { unique: true });
        db.citation_cache.createIndex({ expires_at: 1 }, { expireAfterSeconds: 0 });
        
        print('Collections and indexes created successfully');
    " --quiet 2>/dev/null && echo -e "${GREEN}✓ Collections created${NC}" || {
        echo -e "${YELLOW}⚠ Could not create collections automatically${NC}"
    }
else
    echo -e "${YELLOW}⚠ mongosh not installed, skipping collection creation${NC}"
    echo "  Install with: brew install mongosh"
fi

# ── Create vector search index ───────────────────────────────────────────────

echo ""
echo -e "${YELLOW}▶ Setting up vector search index...${NC}"

if [ ! -f "$VECTOR_INDEX_FILE" ]; then
    echo -e "${RED}✗ Vector index file not found: $VECTOR_INDEX_FILE${NC}"
    exit 1
fi

echo "  Index definition: $VECTOR_INDEX_FILE"

# Try to create the vector search index
INDEX_CREATED=false

# Method 1: Try 'atlas local search indexes create'
echo "  Trying: atlas local search indexes create..."
if atlas local search indexes create \
    --deploymentName "$DEPLOYMENT_NAME" \
    --file "$VECTOR_INDEX_FILE" 2>/dev/null; then
    echo -e "${GREEN}✓ Vector index created via 'atlas local search indexes create'${NC}"
    INDEX_CREATED=true
else
    echo "    (atlas local search command failed, trying fallback)"
fi

# Method 2: Use mongosh with createSearchIndexes command
if [ "$INDEX_CREATED" = false ] && command -v mongosh &> /dev/null; then
    echo "  Trying: mongosh with createSearchIndexes..."
    
    if mongosh "$MONGODB_URI" --eval "
        try {
            const result = db.runCommand({
                createSearchIndexes: 'doc_embeddings',
                indexes: [{
                    name: 'embedding_index',
                    type: 'vectorSearch',
                    definition: {
                        fields: [
                            { type: 'vector', path: 'embedding', numDimensions: 768, similarity: 'cosine' },
                            { type: 'filter', path: 'doc_id' },
                            { type: 'filter', path: 'chunk_type' }
                        ]
                    }
                }]
            });
            print('Index creation result:', JSON.stringify(result));
            quit(result.ok === 1 ? 0 : 1);
        } catch(e) {
            print('Error:', e.message);
            quit(1);
        }
    " --quiet 2>/dev/null; then
        echo -e "${GREEN}✓ Vector index created via mongosh${NC}"
        INDEX_CREATED=true
    else
        echo "    (mongosh method also failed)"
    fi
fi

# Summary of index creation
if [ "$INDEX_CREATED" = false ]; then
    echo ""
    echo -e "${YELLOW}⚠ Could not create vector search index automatically${NC}"
    echo ""
    echo -e "${BLUE}Please create it manually after starting the app:${NC}"
    echo ""
    echo "Step 1: Upload a document via UI (http://localhost:3001)"
    echo "Step 2: Run this command to create the index:"
    echo ""
    echo "  atlas local search indexes create \\"
    echo "    --deploymentName $DEPLOYMENT_NAME \\"
    echo "    --file $VECTOR_INDEX_FILE"
    echo ""
    echo "Or use MongoDB Compass:"
    echo "  1. Connect to: $MONGODB_URI"
    echo "  2. Select 'doc_embeddings' collection"
    echo "  3. Go to 'Indexes' → 'Create Vector Search Index'"
    echo "  4. Use this definition:"
    cat "$VECTOR_INDEX_FILE" | sed 's/^/     /'
    echo ""
fi

# ── Verify connection ────────────────────────────────────────────────────────

echo ""
echo -e "${YELLOW}▶ Verifying MongoDB connection...${NC}"

if command -v mongosh &> /dev/null; then
    if mongosh "$MONGODB_URI" --eval "db.runCommand({ping: 1})" --quiet > /dev/null 2>&1; then
        echo -e "${GREEN}✓ MongoDB connection successful${NC}"
    else
        echo -e "${YELLOW}⚠ MongoDB connection failed - deployment may still be starting${NC}"
    fi
else
    echo -e "${YELLOW}⚠ mongosh not installed, skipping connection test${NC}"
fi

# ── Summary ──────────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}══════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Setup Complete!${NC}"
echo -e "${GREEN}══════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${BLUE}MongoDB Local Atlas is running:${NC}"
echo "  Connection URI: $MONGODB_URI"
echo "  Deployment:     $DEPLOYMENT_NAME"
if [ "$INDEX_CREATED" = true ]; then
    echo "  Collections:    ✓ Created"
    echo "  Vector Search:  ✓ Enabled (embedding_index)"
else
    echo "  Collections:    ✓ Created"
    echo "  Vector Search:  ⚠ Manual setup required (see above)"
fi
echo ""
echo -e "${BLUE}Next steps:${NC}"
echo "  1. Update your .env file:"
echo "     MONGODB_URI=$MONGODB_URI"
echo "     VECTOR_SEARCH_BACKEND=atlas"
echo ""
echo "  2. Start Docker services:"
echo "     docker compose up -d"
echo ""
echo "  3. Access MongoDB:"
echo "     atlas local connect $DEPLOYMENT_NAME"
echo ""
echo -e "${BLUE}Useful commands:${NC}"
echo "  Check status:        atlas local list"
echo "  List search indexes: atlas local search indexes list --deploymentName $DEPLOYMENT_NAME"
echo "  Connect:             atlas local connect $DEPLOYMENT_NAME"
echo "  Stop:                atlas local stop $DEPLOYMENT_NAME"
echo "  Delete:              atlas local delete $DEPLOYMENT_NAME"
echo ""

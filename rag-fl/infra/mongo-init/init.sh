#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# infra/mongo-init/init.sh
# Runs inside the mongo-init container.
# 1. Waits until mongod accepts connections
# 2. Initiates replica set rs0 (idempotent)
# 3. Waits until this node becomes PRIMARY
# 4. Creates all 5 collections + indexes
# 5. Creates GCS bucket on fake-gcs-server
# ─────────────────────────────────────────────────────────────────────────────
set -e

MONGO_HOST="${MONGO_HOST:-mongo:27017}"
GCS_ENDPOINT="${GCS_ENDPOINT:-http://fake-gcs:4443}"
GCS_BUCKET="${GCS_BUCKET:-rag-fl-documents}"
DB="${MONGODB_DB:-ragfl}"

echo "=== [1/4] Waiting for mongod to accept connections on ${MONGO_HOST} ..."
until mongosh --host "${MONGO_HOST}" --quiet \
      --eval "db.adminCommand('ping').ok" 2>/dev/null | grep -q 1; do
  echo "  mongod not ready yet — retrying in 2s"
  sleep 2
done
echo "  mongod is up."

echo "=== [2/4] Initiating replica set rs0 ..."
mongosh --host "${MONGO_HOST}" --quiet --eval "
  try {
    var result = rs.initiate({
      _id: 'rs0',
      members: [{ _id: 0, host: '${MONGO_HOST}' }]
    });
    print('rs.initiate result: ' + JSON.stringify(result));
  } catch(e) {
    if (e.code === 23) {
      print('Replica set already initiated — skipping.');
    } else {
      print('rs.initiate error: ' + e);
      throw e;
    }
  }
"

echo "=== [3/4] Waiting for PRIMARY ..."
until mongosh --host "${MONGO_HOST}" --quiet \
      --eval "db.isMaster().ismaster" 2>/dev/null | grep -q true; do
  echo "  not primary yet — retrying in 2s"
  sleep 2
done
echo "  PRIMARY is ready."

echo "=== [4/4] Creating collections and indexes in '${DB}' ..."
mongosh "mongodb://${MONGO_HOST}/${DB}?replicaSet=rs0" --quiet /scripts/collections.js

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  rag-fl MongoDB initialisation DONE         ║"
echo "║  GCS bucket: run 'make init-gcs' from host  ║"
echo "╚══════════════════════════════════════════════╝"

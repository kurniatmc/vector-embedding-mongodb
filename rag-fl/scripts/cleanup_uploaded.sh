#!/bin/bash
# Delete all documents with status=UPLOADED from MongoDB
# Also delete their page_profiles and any orphan chunks

docker compose exec -T mongo mongosh ragfl --eval "
  const uploadedDocs = db.documents.find({status: 'UPLOADED'}, {doc_id: 1}).toArray();
  const docIds = uploadedDocs.map(d => d.doc_id);

  print('Found ' + docIds.length + ' UPLOADED documents to delete');

  const docsDeleted = db.documents.deleteMany({status: 'UPLOADED'});
  const profilesDeleted = db.page_profiles.deleteMany({doc_id: {\$in: docIds}});
  const chunksDeleted = db.doc_embeddings.deleteMany({doc_id: {\$in: docIds}});

  print('Deleted:');
  print('  - ' + docsDeleted.deletedCount + ' documents');
  print('  - ' + profilesDeleted.deletedCount + ' page_profiles');
  print('  - ' + chunksDeleted.deletedCount + ' chunks (if any)');
"

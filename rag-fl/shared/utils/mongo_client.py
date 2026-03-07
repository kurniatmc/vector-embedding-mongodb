"""
shared/utils/mongo_client.py
Synchronous MongoDB client. Each service imports this module.
Connection is lazy — the client is created once per process.
"""
import os
from functools import lru_cache
from pymongo import MongoClient
from pymongo.database import Database
from pymongo.collection import Collection


@lru_cache(maxsize=1)
def get_mongo_client() -> MongoClient:
    uri = os.getenv("MONGODB_URI", "mongodb://mongo:27017/ragfl?replicaSet=rs0")
    return MongoClient(uri)


def get_db() -> Database:
    db_name = os.getenv("MONGODB_DB", "ragfl")
    return get_mongo_client()[db_name]


def get_collection(name: str) -> Collection:
    return get_db()[name]


# Convenience accessors
def documents() -> Collection:
    return get_collection("documents")

def page_profiles() -> Collection:
    return get_collection("page_profiles")

def doc_embeddings() -> Collection:
    return get_collection("doc_embeddings")

def file_ledger() -> Collection:
    return get_collection("file_ledger")

def citation_cache() -> Collection:
    return get_collection("citation_cache")

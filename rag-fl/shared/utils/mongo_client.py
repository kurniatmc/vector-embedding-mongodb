"""
shared/utils/mongo_client.py
Synchronous MongoDB client. Each service imports this module.
Connection is lazy — the client is created once per process.

MongoDB Atlas compatible with SRV connection strings.
"""
import os
from functools import lru_cache
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from pymongo.database import Database
from pymongo.collection import Collection


@lru_cache(maxsize=1)
def get_mongo_client() -> MongoClient:
    """
    Return a MongoDB client configured for Atlas or local.
    For Atlas: uses mongodb+srv:// URI with ServerApi
    """
    uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/ragfl")
    
    # Common client options
    client_options = {
        "server_api": ServerApi('1'),
    }
    
    # For Atlas SRV connections, enable TLS
    if "mongodb+srv://" in uri:
        client_options["tls"] = True
        # Allow retry on different TLS versions
        client_options["retryWrites"] = True
        client_options["tlsAllowInvalidCertificates"] = False
    
    # Create a new client and connect to the server
    client = MongoClient(uri, **client_options)
    
    return client


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

# Test connection function
def test_connection():
    """Send a ping to confirm a successful connection"""
    try:
        client = get_mongo_client()
        client.admin.command('ping')
        print("Pinged your deployment. You successfully connected to MongoDB!")
        return True
    except Exception as e:
        print(f"MongoDB connection failed: {e}")
        return False

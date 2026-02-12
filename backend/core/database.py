"""
Database connection - MongoDB with Motor (async)
"""
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from .config import get_settings

settings = get_settings()

# Async client for FastAPI
_async_client: AsyncIOMotorClient = None

# Sync client for background tasks
_sync_client: MongoClient = None


async def get_database():
    """Get async database connection"""
    global _async_client
    if _async_client is None:
        _async_client = AsyncIOMotorClient(settings.MONGODB_URI)
    return _async_client[settings.MONGODB_DATABASE]


def get_sync_database():
    """Get sync database for background tasks"""
    global _sync_client
    if _sync_client is None:
        _sync_client = MongoClient(settings.MONGODB_URI)
    return _sync_client[settings.MONGODB_DATABASE]


async def close_database():
    """Close database connections"""
    global _async_client, _sync_client
    if _async_client:
        _async_client.close()
    if _sync_client:
        _sync_client.close()

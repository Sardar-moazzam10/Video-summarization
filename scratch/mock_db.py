class MockCollection:
    def __init__(self, name):
        self.name = name
        self.data = {}
    async def insert_one(self, doc):
        _id = doc.get("_id") or doc.get("job_id")
        self.data[_id] = doc
        return None
    async def find_one(self, query):
        _id = query.get("job_id") or query.get("_id")
        return self.data.get(_id)
    async def update_one(self, query, update, **kwargs):
        _id = query.get("job_id") or query.get("_id")
        if _id in self.data:
            if "$set" in update:
                self.data[_id].update(update["$set"])
        return None
    def find(self, *args, **kwargs):
        class Cursor:
            async def to_list(self, length): return []
        return Cursor()

class MockDB:
    def __init__(self):
        self.collections = {}
    def __getitem__(self, name):
        if name not in self.collections:
            self.collections[name] = MockCollection(name)
        return self.collections[name]

_mock_db = MockDB()

async def get_database(): return _mock_db
def get_sync_database(): return _mock_db

import backend.core.database as db
db.get_database = get_database
db.get_sync_database = get_sync_database

# We also need to patch get_jobs_collection in backend.api.merge if it caches the collection
import backend.api.merge as merge
async def get_jobs_collection(): return _mock_db["jobs"]
merge.get_jobs_collection = get_jobs_collection

import backend.services.transcript_service as ts
class MockTranscripts:
    def __init__(self):
        self.data = {}
    async def find_one(self, query): return self.data.get(query.get("video_id"))
    async def update_one(self, query, update, **kwargs):
        _id = query.get("video_id")
        if _id not in self.data:
            self.data[_id] = {}
        if "$set" in update:
            self.data[_id].update(update["$set"])
ts.get_database = get_database

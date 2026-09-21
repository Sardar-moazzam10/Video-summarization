

from pymongo.mongo_client import MongoClient
import os

# Never commit database credentials. This legacy module now follows the same
# environment contract as the unified FastAPI backend.
MONGO_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")

# ✅ Connect to MongoDB
client = MongoClient(MONGO_URI)

# ✅ Define database and collection
db = client[os.getenv("MONGODB_DATABASE", "video-summarizer")]
user_collection = db["users"]

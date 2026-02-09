

from pymongo.mongo_client import MongoClient

# ✅ Replace with your actual MongoDB Atlas connection string
MONGO_URI = "mongodb+srv://admin:adminhamza@podcastlycluster.hyrqok6.mongodb.net/?retryWrites=true&w=majority&appName=podcastlycluster"

# ✅ Connect to MongoDB
client = MongoClient(MONGO_URI)

# ✅ Define database and collection
db = client["podcastly_db"]
user_collection = db["users"]

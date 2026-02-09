from pymongo import MongoClient

# Connect to MongoDB
client = MongoClient("mongodb+srv://hamzaarif725725:hamzapodcastly@podcastlycluster.hyrqok6.mongodb.net/")
db = client['user-auth']

# List all collections
collections = db.list_collection_names()
print("✅ Collections in user-auth DB:")
print(collections)

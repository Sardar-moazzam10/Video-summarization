from pymongo import MongoClient
from datetime import datetime

client = MongoClient("mongodb+srv://hamzaarif725725:hamzapodcastly@podcastlycluster.hyrqok6.mongodb.net/")
db = client['user-auth']
history = db['history']

# Insert a sample record
test_data = {
    "username": "testuser",
    "type": "watch",
    "videoId": "dQw4w9WgXcQ",
    "title": "Test Video Title",
    "timestamp": datetime.utcnow().isoformat()
}

result = history.insert_one(test_data)
print(f"✅ Inserted record with ID: {result.inserted_id}")

import os
from dotenv import load_dotenv

import pymongo

load_dotenv()


client = pymongo.MongoClient(os.getenv("ATLAS_URI"))
db = client.myDatabase


# action-functionality collection
action_func_db = db["action-functionality"]
func_db = db["functionality"]


def ensure_deduplication_indexes() -> None:
    func_db.create_index(
        [("app", 1), ("text_key", 1)],
        unique=True,
        partialFilterExpression={"text_key": {"$type": "string"}},
        name="unique_functionality_text_per_app",
    )
    action_func_db.create_index(
        [("app", 1), ("dedupe_key", 1)],
        unique=True,
        partialFilterExpression={"dedupe_key": {"$type": "string"}},
        name="unique_action_functionality_relation",
    )

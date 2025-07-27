import os
import logging
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_client import BaseClient

# --- Configuration ---
# Configure logging to see the script's progress
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# Use the same credentials as your application.
# Ensure the GOOGLE_APPLICATION_CREDENTIALS environment variable is set.
# Example: export GOOGLE_APPLICATION_CREDENTIALS="/path/to/your/serviceAccountKey.json"
try:
    cred = credentials.Certificate("service-account.json")
    firebase_admin.initialize_app(
        cred,
        {
            "projectId": "nutrilytics-1b7b5",
        },
    )
    logging.info("Firebase Admin SDK initialized successfully.")
except Exception as e:
    logging.error(f"Failed to initialize Firebase Admin SDK: {e}")
    exit(1)

# Get a client for the Firestore database
db: BaseClient = firestore.client()


# --- Migration Logic ---
def migrate_meals():
    """
    Finds and migrates meal documents from the old flat structure
    to the new nested 'data' structure.
    """
    meals_ref = db.collection("meals")
    docs_stream = meals_ref.stream()
    batch = db.batch()

    migrated_count = 0
    processed_count = 0
    batch_size = 250  # Commit writes in batches of 250

    logging.info("Starting meal data migration...")

    for doc in docs_stream:
        processed_count += 1
        meal_data = doc.to_dict()

        # Check if the document needs migration.
        # It needs migration if 'data' field does NOT exist AND old fields DO exist.
        if (
            True
        ):
            logging.info(f"Migrating document: {doc.id}")

            # These are the fields that will be moved into the 'data' sub-object.
            # Names must match the camelCase format in Firestore.
            fields_to_nest = [
                "name",
                "description",
                "type",
                "nutrientProfile",
                "components",
            ]

            new_data_payload = {}
            fields_to_delete = {}

            for field in fields_to_nest:
                if field in meal_data:
                    new_data_payload[field] = meal_data[field]
                    fields_to_delete[field] = firestore.DELETE_FIELD

            # Prepare the final update payload
            update_payload = {
                "data": new_data_payload,
                "status": "complete",
                "originalInput": "",
                "submittedAt": firestore.DELETE_FIELD,
            }

            # Add the update operation to the batch
            batch.delete(doc.reference)
            migrated_count += 1

            # Commit the batch when it's full to avoid memory issues
            if migrated_count % batch_size == 0:
                logging.info(f"Committing batch of {batch_size} documents...")
                batch.commit()
                # Start a new batch
                batch = db.batch()

    # Commit any remaining documents in the last batch
    if migrated_count % batch_size != 0:
        logging.info("Committing the final batch of documents...")
        batch.commit()

    logging.info("--- Migration Summary ---")
    logging.info(f"Total documents processed: {processed_count}")
    logging.info(f"Total documents migrated: {migrated_count}")
    logging.info("Migration complete.")


if __name__ == "__main__":
    migrate_meals()

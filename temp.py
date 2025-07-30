import firebase_admin
from firebase_admin import credentials, firestore

# --- IMPORTANT: BEFORE RUNNING ---
# 1. Install the Firebase Admin SDK: pip install firebase-admin
# 2. Download your service account key JSON file from the Firebase console
#    (Project settings -> Service accounts -> Generate new private key).
# 3. Replace 'path/to/your/serviceAccountKey.json' with the actual path to your file.
# 4. Replace 'your_collection_name' with the name of your Firestore collection.
# 5. Understand the potential impact: This script will modify your Firestore data.
#    It's highly recommended to test on a development database or a backup first.

# Initialize Firebase Admin SDK
try:
    cred = credentials.Certificate('service-account.json')
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("Firebase initialized successfully.")
except Exception as e:
    print(f"Error initializing Firebase: {e}")
    print("Please ensure your service account key path is correct and the file is accessible.")
    exit()

def update_component_type_in_docs(collection_name):
    """
    Iterates through every document in a specified Firestore collection,
    and for each document's 'data.components' array, adds a 'type': 'food'
    field to every component if it doesn't already exist.
    """
    try:
        docs_ref = db.collection(collection_name).stream()
        
        print(f"\nProcessing documents in collection: '{collection_name}'...")
        
        updated_count = 0
        for doc in docs_ref:
            doc_id = doc.id
            doc_data = doc.to_dict()
            
            # Check if 'data' and 'data.components' exist
            if 'data' in doc_data and 'components' in doc_data['data'] and isinstance(doc_data['data']['components'], list):
                components = doc_data['data']['components']
                
                changes_made = False
                for component in components:
                    if isinstance(component, dict) and 'type' not in component:
                        component['type'] = 'food'
                        changes_made = True
                
                if changes_made:
                    # Update the document in Firestore
                    try:
                        db.collection(collection_name).document(doc_id).update({'data.components': components})
                        print(f"  Updated document: {doc_id}")
                        updated_count += 1
                    except Exception as e:
                        print(f"  Error updating document {doc_id}: {e}")
                else:
                    print(f"  No changes needed for document: {doc_id}")
            else:
                print(f"  Document {doc_id} does not have 'data.components' array or it's not a list. Skipping.")
        
        print(f"\nScript finished. Total documents updated: {updated_count}")

    except Exception as e:
        print(f"An error occurred during document processing: {e}")

# --- Configuration ---
YOUR_COLLECTION_NAME = 'meals' # <<< RENAME THIS TO YOUR ACTUAL COLLECTION NAME

# Run the update function
if __name__ == '__main__':
    update_component_type_in_docs(YOUR_COLLECTION_NAME)
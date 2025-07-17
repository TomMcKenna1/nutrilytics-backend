import firebase_admin
from firebase_admin import credentials, firestore_async, auth
from app.core.config import settings


def initialize_firebase():
    """
    Initialize the Firebase Admin SDK.
    """
    try:
        firebase_admin.get_app()
    except ValueError:
        cred = credentials.Certificate("service-account.json")
        firebase_admin.initialize_app(
            cred,
            {
                "projectId": settings.FIREBASE_PROJECT_ID,
            },
        )


def get_firestore_client():
    """
    Returns a Firestore client.
    """
    return firestore_async.client()


def get_firebase_auth():
    """
    Returns a Firebase Auth client.
    """
    return auth

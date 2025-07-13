# Nutrilytics Backend API

This repository contains the backend server for **Nutrilytics**, a mobile application for logging meals and tracking nutrition. This API handles user authentication, meal data storage, and meal generation using **FastAPI** and **Google Firestore**.

The API also integrates with **Redis** for caching Firebase ID tokens and generated meal drafts, significantly improving performance and reducing redundant computation.

It uses another one of my projects: the [meal-generator](https://github.com/TomMcKenna1/meal-generator) Python library. Check it out!

---

## Features

- **User Authentication**: Secure user management via Firebase Authentication.  
- **Meal Logging**: Full CRUD (Create, Read, Update, Delete) operations for user meals.  
- **AI-Powered Meal Generation**: Asynchronously generate detailed meal nutritional profiles from simple text descriptions.  
- **Secure Data Storage**: All user data is securely stored and tied to individual user accounts in Firestore.  
- **Redis Caching**: Speeds up authentication checks and meal draft polling by caching Firebase tokens and in-progress meal generations.

---

## Tech Stack

- **Framework**: FastAPI  
- **Database**: Google Firestore  
- **Authentication**: Firebase Authentication  
- **Caching**: Redis (for token validation and meal draft caching)  
- **Server**: Uvicorn  
- **Data Validation**: Pydantic  
- **AI**: Google Gemini  

---

## Local Setup

To get the project running locally, follow these steps:

### 1. Prerequisites

- Python 3.8+  
- Redis server running locally or remotely  
- A Google Firebase project with Firestore and Authentication enabled  
- A Google AI Studio API Key for Gemini  

### 2. Clone & Setup

```bash
# Clone the repository
git clone https://github.com/TomMcKenna1/nutrilytics-backend
cd nutrilytics-backend

# Install dependencies
pip install -r requirements.txt
```

### 3. Environment Setup

- Download your service account key from the Firebase console, rename it to `service-account.json`, and place it in the project's root directory.
- Create a `.env` file in the root directory and add your project credentials:

#### Sample `.env` file:

```ini
GOOGLE_APPLICATION_CREDENTIALS="service-account.json"
FIREBASE_PROJECT_ID="your-firebase-project-id"
GEMINI_API_KEY="your-google-ai-studio-api-key"
REDIS_URL="redis://localhost:6379"  # or your hosted Redis URL
```

### 4. Run the Server

```bash
uvicorn app.main:app --reload
```

The API will be available at: [http://127.0.0.1:8000](http://127.0.0.1:8000)

---

## API Endpoints

All v1 endpoints are prefixed with `/api/v1`.  
Authentication is handled via Firebase ID tokens passed as a Bearer token in the `Authorization` header.  
Redis is used internally to cache validated tokens and reduce the number of external verification requests.

---

### Root

**GET /**  
_Description_: A welcome message to verify that the API is running.

**Response 200 OK**

```json
{
  "message": "Welcome to the Meal Tracker API"
}
```

---

### Authentication

**Base path**: `/api/v1/auth`

#### GET /api/v1/auth/me

_Description_: Retrieves the profile of the currently authenticated user. Validated Firebase tokens are cached in Redis to speed up future authentication.

**Response 200 OK**

```json
{
  "uid": "user_firebase_uid",
  "email": "user@example.com",
  "name": "example"
}
```

---

### Meal Drafts

**Base path**: `/api/v1/meal_drafts`

#### POST /api/v1/meal_drafts/

_Description_: Starts a background task to generate a meal from a user's description. Results are cached in Redis and can be polled.

**Status Code**: 202 ACCEPTED  
**Request Body**

```json
{
  "description": "A bowl of spaghetti bolognese"
}
```

**Response 202 ACCEPTED**

```json
{
  "draftId": "a_unique_draft_id"
}
```

---

#### GET /api/v1/meal_drafts/{draft_id}

_Description_: Poll to check the status of a meal generation task. Cached in Redis until complete.

**Pending State Response**

```json
{
  "status": "pending",
  "uid": "user_firebase_uid",
  "meal": null
}
```

**Complete State Response**

```json
{
  "status": "complete",
  "uid": "user_firebase_uid",
  "meal": {
    "name": "Spaghetti Bolognese",
    "calories": 600,
    "protein": 30,
    "carbohydrates": 70,
    "fat": 20,
    ...
  }
}
```

**Errors**:  
- 403 Forbidden  
- 404 Not Found  

---

#### DELETE /api/v1/meal_drafts/{draft_id}

_Description_: Deletes a meal draft from the Redis cache.

**Status Code**: 204 NO CONTENT  
**Errors**:  
- 403 Forbidden  
- 404 Not Found  

---

### Meals

**Base path**: `/api/v1/meals`

#### POST /api/v1/meals/

_Description_: Promotes a completed meal draft to be saved in the Firestore database.

**Status Code**: 201 CREATED  
**Request Body**

```json
{
  "draft_id": "the_completed_draft_id"
}
```

**Response 201 CREATED**

Returns the completed Meal, timestamp and Firestore ID.

**Errors**:  
- 403 Forbidden  
- 404 Not Found  
- 409 Conflict  

---

#### GET /api/v1/meals/{meal_id}

_Description_: Retrieves a specific meal by its Firestore document ID.

**Response 200 OK**

Returns the requested Meal, timestamp and Firestore ID.

**Errors**:  
- 403 Forbidden  
- 404 Not Found  

---

## Contact

For any questions or contributions, please reach out via [GitHub Issues](https://github.com/TomMcKenna1/nutrilytics-backend/issues).

---

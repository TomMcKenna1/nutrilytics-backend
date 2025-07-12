# Nutrilytics Backend API

This repository contains the backend server for **Nutrilytics**, a mobile application for logging meals and tracking nutrition.

This API handles user authentication, meal data storage, and meal generation using FastAPI and Google Firestore.

The API uses my meal-generator python library. See [meal-generator](https://github.com/TomMcKenna1/meal-generator) for more info!

---

## **Features** ✨

* **User Authentication**: Secure user management via Firebase Authentication.
* **Meal Logging**: Full CRUD (Create, Read, Update, Delete) operations for user meals.
* **AI-Powered Meal Generation**: Asynchronously generate detailed meal nutritional profiles from simple text descriptions.
* **Secure Data Storage**: All user data is securely stored and tied to individual user accounts in Firestore.

---

## **Tech Stack** 🚀

* **Framework**: FastAPI
* **Database**: Google Firestore
* **Authentication**: Firebase Authentication
* **Server**: Uvicorn
* **Data Validation**: Pydantic
* **AI**: Google Gemini

---

## **Local Setup** ⚙️

To get the project running locally, follow these steps.

### **1. Prerequisites**

* Python 3.8+
* A Google Firebase project with Firestore and Authentication enabled.
* A Google AI Studio API Key for Gemini.

### **2. Clone & Setup**

```bash
# Clone the repository
git clone https://github.com/TomMcKenna1/nutrilytics-backend
cd nutrilytics-backend

# Install dependencies
pip install -r requirements.txt
```
### **3. Environment Setup**
Download your service account key from the Firebase console, rename it to service-account.json, and place it in the project's root directory.

Create a .env file in the root directory and add your project credentials:

Sample .env file:
```ini
GOOGLE_APPLICATION_CREDENTIALS="service-account.json"
FIREBASE_PROJECT_ID="your-firebase-project-id"
GEMINI_API_KEY="your-google-ai-studio-api-key"
```
### **4. Run the Server**
```bash
uvicorn app.main:app --reload
```
The API will be available at http://127.0.0.1:8000.

### **5 (Optional). Get a firebase token for testing**
I have provided a get token tool in the dev_tools directory. This can be used to get a token for testing purposes.
N.B. You must edit the code with your own firebase configuration and test login details!
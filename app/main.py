from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.api.v1 import auth as auth_v1, meal_drafts, meals
from app.db.firebase import initialize_firebase


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_firebase()
    yield
    # Clean up resources if needed on shutdown
    pass


app = FastAPI(lifespan=lifespan)

app.include_router(auth_v1.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(
    meal_drafts.router, prefix="/api/v1/meal_drafts", tags=["meal_drafts"]
)
app.include_router(meals.router, prefix="/api/v1/meals", tags=["meals"])


@app.get("/")
def read_root():
    return {"message": "Welcome to the Meal Tracker API"}

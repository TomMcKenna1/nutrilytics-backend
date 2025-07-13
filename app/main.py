import logging
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.api.v1 import auth as auth_v1, meal_drafts, meals
from app.core.config import settings
from app.db.firebase import initialize_firebase

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages application startup and shutdown events.

    This context manager handles the initialization of database connections
    and other resources at startup, and ensures they are gracefully closed
    on shutdown.
    """
    logging.info("Application startup...")
    try:
        initialize_firebase()
        app.state.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
        await app.state.redis.ping()
        logging.info("Successfully connected to Redis.")
    except Exception as e:
        logging.critical(f"Failed to initialize resources: {e}")
        raise

    yield

    logging.info("Application shutdown...")
    if hasattr(app.state, "redis") and app.state.redis:
        await app.state.redis.close()
        logging.info("Redis connection closed.")


app = FastAPI(
    lifespan=lifespan,
    title="Nutrilytics API",
    version="1.0.0",
    description="API for tracking meals and their nutritional information.",
)


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """
    Catches all unhandled exceptions and returns a generic 500 error.
    """
    logging.error(
        f"Unhandled exception for request {request.url}: {exc}", exc_info=True
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal server error occurred."},
    )


app.include_router(auth_v1.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(
    meal_drafts.router, prefix="/api/v1/meal_drafts", tags=["meal_drafts"]
)
app.include_router(meals.router, prefix="/api/v1/meals", tags=["meals"])


@app.get("/", tags=["Root"])
def read_root():
    """
    Root endpoint that provides a welcome message.

    Useful for simple health checks to confirm the API is running.
    """
    return {"message": "Welcome to the Nutrilytics API"}

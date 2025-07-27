import logging
from functools import lru_cache

from app.core.config import settings
from meal_generator import Meal, MealGenerationError, MealGenerator

logger = logging.getLogger(__name__)


@lru_cache(maxsize=None)
def get_meal_generator() -> MealGenerator:
    """
    Initializes and returns a cached singleton instance of the MealGenerator.

    This function uses a cache to ensure the MealGenerator class is instantiated
    only once during the application's lifecycle, on its first request.

    Raises:
        ValueError: If the GEMINI_API_KEY is not configured.

    Returns:
        An initialized MealGenerator instance.
    """
    logger.info("Initializing MealGenerator for the first time...")
    if not settings.GEMINI_API_KEY:
        logger.critical("GEMINI_API_KEY is not set. Meal generator cannot be created.")
        raise ValueError("Cannot initialize MealGenerator: API key is missing.")

    return MealGenerator(api_key=settings.GEMINI_API_KEY)


async def generate_meal_async(description: str, country_code: str = "GB") -> Meal:
    """
    Generates a meal by calling the MealGenerator library.

    This function retrieves the cached generator instance and uses it to generate
    the meal from the provided text description.

    Args:
        description: The text description of the meal.

    Raises:
        MealGenerationError: Propagates errors from the generator service,
                             such as configuration issues or upstream API failures.

    Returns:
        A Meal object with the generated nutritional information.
    """
    try:
        generator = get_meal_generator()
        return await generator.generate_meal_async(description, country_code)
    except (ValueError, MealGenerationError) as e:
        logger.error(f"Could not complete meal generation: {e}", exc_info=True)
        # Re-raise a consistent error type to be handled by the caller.
        raise MealGenerationError(f"Meal generation failed: {e}") from e

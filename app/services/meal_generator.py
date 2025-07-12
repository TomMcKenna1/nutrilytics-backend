from meal_generator import MealGenerationError, MealGenerator, Meal
from app.core.config import settings

try:
    generator = MealGenerator(api_key=settings.GEMINI_API_KEY)
except ValueError as e:
    print(f"ERROR: Could not initialize MealGenerator: {e}")
    generator = None


def generate_meal(description: str) -> Meal:
    """
    Generates a meal by calling the MealGenerator library.
    This function acts as a service layer between the API endpoint and the generation logic.
    """
    if not generator:
        raise MealGenerationError("MealGenerator is not available due to a configuration error.")
        
    # The actual generation logic is now handled by the generator instance.
    return generator.generate_meal(description)

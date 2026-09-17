"""
Looks up average nutrition data for a food by name from USDA FoodData
Central (a free, authoritative US government nutrition database), so
users don't have to look up or manually enter calories/macros themselves.

The network call and the response-parsing logic are kept separate: the
parsing can be tested against a realistic fixture response, independent
of whether the live API is reachable from wherever this runs.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

USDA_API_KEY = os.environ.get("USDA_API_KEY", "DEMO_KEY")
USDA_SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"

NUTRIENT_NUMBERS = {
    "calories": "208",
    "protein": "203",
    "carbs": "205",
    "fat": "204",
    "calcium": "301",
    "vitamin_c": "401",
}

# USDA reports omega-3 as separate fatty acids rather than one combined
# figure - ALA (plant sources), EPA/DPA/DHA (mainly fish). Not every food
# has all of these measured; we sum whichever are present and the result
# is genuinely 0 for foods where USDA's entry doesn't break out fatty
# acid detail (common for many legacy/branded entries) - that's a real
# data limitation, not a bug.
OMEGA3_NUTRIENT_NUMBERS = ["851", "621", "628", "631"]  # ALA, EPA, DPA, DHA

PREFERRED_DATA_TYPES = ["Foundation", "SR Legacy"]


class FoodLookupError(Exception):
    pass


def _extract_nutrient(food_nutrients: list, nutrient_number: str):
    for nutrient in food_nutrients:
        if str(nutrient.get("nutrientNumber")) == nutrient_number:
            return nutrient.get("value")
    return None


def _sum_omega3(food_nutrients: list) -> float:
    total = 0.0
    for number in OMEGA3_NUTRIENT_NUMBERS:
        value = _extract_nutrient(food_nutrients, number)
        if value is not None:
            total += value
    return total


def parse_search_response(response_json: dict, food_name: str) -> dict:
    foods = response_json.get("foods", [])
    if not foods:
        raise FoodLookupError(f"No nutrition data found for '{food_name}'")

    foods_sorted = sorted(
        foods,
        key=lambda f: PREFERRED_DATA_TYPES.index(f["dataType"])
        if f.get("dataType") in PREFERRED_DATA_TYPES
        else len(PREFERRED_DATA_TYPES),
    )
    best_match = foods_sorted[0]

    nutrients = best_match.get("foodNutrients", [])
    calories = _extract_nutrient(nutrients, NUTRIENT_NUMBERS["calories"])
    protein = _extract_nutrient(nutrients, NUTRIENT_NUMBERS["protein"])
    carbs = _extract_nutrient(nutrients, NUTRIENT_NUMBERS["carbs"])
    fat = _extract_nutrient(nutrients, NUTRIENT_NUMBERS["fat"])
    calcium = _extract_nutrient(nutrients, NUTRIENT_NUMBERS["calcium"])
    vitamin_c = _extract_nutrient(nutrients, NUTRIENT_NUMBERS["vitamin_c"])
    omega3 = _sum_omega3(nutrients)

    if calories is None:
        raise FoodLookupError(f"Found '{best_match.get('description')}' but it has no calorie data")

    return {
        "name": food_name,
        "matched_description": best_match.get("description", food_name),
        "calories_per_100g": round(calories, 1),
        "protein_per_100g": round(protein or 0, 1),
        "carbs_per_100g": round(carbs or 0, 1),
        "fat_per_100g": round(fat or 0, 1),
        "calcium_mg_per_100g": round(calcium or 0, 1),
        "vitamin_c_mg_per_100g": round(vitamin_c or 0, 1),
        "omega3_g_per_100g": round(omega3, 2),
    }


def search_food_nutrition(food_name: str) -> dict:
    params = urllib.parse.urlencode({
        "query": food_name,
        "api_key": USDA_API_KEY,
        "pageSize": 5,
        "dataType": ",".join(PREFERRED_DATA_TYPES + ["Branded"]),
    })
    url = f"{USDA_SEARCH_URL}?{params}"

    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            response_json = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        reason = getattr(e, "reason", None)
        print(f"[nutrition_lookup] USDA request failed: {type(e).__name__}: {repr(e)} | reason={repr(reason)}")
        raise FoodLookupError(f"Could not reach nutrition database: {type(e).__name__}: {repr(e)}")

    return parse_search_response(response_json, food_name)

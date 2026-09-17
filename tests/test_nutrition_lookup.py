import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nutrition_lookup import parse_search_response, FoodLookupError

FIXTURE_RESPONSE = {
    "totalHits": 2,
    "foods": [
        {
            "fdcId": 171077,
            "description": "Chicken, broilers or fryers, breast, meat only, raw",
            "dataType": "SR Legacy",
            "foodNutrients": [
                {"nutrientId": 1008, "nutrientNumber": "208", "nutrientName": "Energy", "value": 120.0, "unitName": "KCAL"},
                {"nutrientId": 1003, "nutrientNumber": "203", "nutrientName": "Protein", "value": 22.5, "unitName": "G"},
                {"nutrientId": 1005, "nutrientNumber": "205", "nutrientName": "Carbohydrate, by difference", "value": 0.0, "unitName": "G"},
                {"nutrientId": 1004, "nutrientNumber": "204", "nutrientName": "Total lipid (fat)", "value": 2.6, "unitName": "G"},
                {"nutrientId": 1087, "nutrientNumber": "301", "nutrientName": "Calcium, Ca", "value": 5.0, "unitName": "MG"},
                {"nutrientId": 1162, "nutrientNumber": "401", "nutrientName": "Vitamin C", "value": 0.0, "unitName": "MG"},
                {"nutrientId": 1404, "nutrientNumber": "851", "nutrientName": "PUFA 18:3 n-3 c,c,c (ALA)", "value": 0.01, "unitName": "G"},
            ],
        },
        {
            "fdcId": 999999,
            "description": "Chicken Breast, Some Brand",
            "dataType": "Branded",
            "foodNutrients": [
                {"nutrientId": 1008, "nutrientNumber": "208", "nutrientName": "Energy", "value": 110.0, "unitName": "KCAL"},
            ],
        },
    ],
}

EMPTY_RESPONSE = {"totalHits": 0, "foods": []}

RESPONSE_MISSING_CALORIES = {
    "foods": [
        {
            "description": "Mystery food",
            "dataType": "SR Legacy",
            "foodNutrients": [
                {"nutrientNumber": "203", "value": 10.0},
            ],
        }
    ]
}


def test_parses_calories_and_macros_correctly():
    result = parse_search_response(FIXTURE_RESPONSE, "chicken breast")
    assert result["calories_per_100g"] == 120.0
    assert result["protein_per_100g"] == 22.5
    assert result["carbs_per_100g"] == 0.0
    assert result["fat_per_100g"] == 2.6


def test_parses_micronutrients_correctly():
    result = parse_search_response(FIXTURE_RESPONSE, "chicken breast")
    assert result["calcium_mg_per_100g"] == 5.0
    assert result["vitamin_c_mg_per_100g"] == 0.0
    assert result["omega3_g_per_100g"] == 0.01


def test_omega3_sums_multiple_fatty_acid_entries():
    response = {
        "foods": [
            {
                "description": "Salmon",
                "dataType": "SR Legacy",
                "foodNutrients": [
                    {"nutrientNumber": "208", "value": 200.0},
                    {"nutrientNumber": "621", "value": 0.5},   # EPA
                    {"nutrientNumber": "631", "value": 1.0},   # DHA
                ],
            }
        ]
    }
    result = parse_search_response(response, "salmon")
    assert result["omega3_g_per_100g"] == 1.5


def test_omega3_defaults_to_zero_when_not_reported():
    response = {
        "foods": [
            {
                "description": "Plain white bread",
                "dataType": "SR Legacy",
                "foodNutrients": [{"nutrientNumber": "208", "value": 265.0}],
            }
        ]
    }
    result = parse_search_response(response, "bread")
    assert result["omega3_g_per_100g"] == 0.0


def test_prefers_sr_legacy_over_branded():
    result = parse_search_response(FIXTURE_RESPONSE, "chicken breast")
    assert result["calories_per_100g"] == 120.0
    assert "roilers" in result["matched_description"]


def test_includes_matched_description_for_transparency():
    result = parse_search_response(FIXTURE_RESPONSE, "chicken breast")
    assert "description" not in result
    assert result["matched_description"]


def test_raises_when_no_foods_found():
    with pytest.raises(FoodLookupError):
        parse_search_response(EMPTY_RESPONSE, "nonexistent food xyz")


def test_raises_when_best_match_has_no_calorie_data():
    with pytest.raises(FoodLookupError):
        parse_search_response(RESPONSE_MISSING_CALORIES, "mystery food")


def test_missing_macros_default_to_zero_not_crash():
    response = {
        "foods": [
            {
                "description": "Water",
                "dataType": "SR Legacy",
                "foodNutrients": [
                    {"nutrientNumber": "208", "value": 0.0},
                ],
            }
        ]
    }
    result = parse_search_response(response, "water")
    assert result["calories_per_100g"] == 0.0
    assert result["protein_per_100g"] == 0.0
    assert result["carbs_per_100g"] == 0.0
    assert result["fat_per_100g"] == 0.0

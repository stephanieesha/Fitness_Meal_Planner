import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nutrition import (
    calculate_bmr, calculate_tdee, calculate_calorie_target,
    calculate_macros, build_profile_targets, SAFE_MINIMUM_CALORIES,
)


def test_bmr_male_known_value():
    assert round(calculate_bmr(70, 175, 30, "male"), 2) == 1648.75


def test_bmr_female_known_value():
    assert round(calculate_bmr(60, 165, 28, "female"), 2) == 1330.25


def test_bmr_rejects_invalid_sex():
    try:
        calculate_bmr(70, 175, 30, "unknown")
        assert False, "should have raised"
    except ValueError:
        pass


def test_bmr_male_higher_than_female_at_same_stats():
    male = calculate_bmr(70, 175, 30, "male")
    female = calculate_bmr(70, 175, 30, "female")
    assert male > female


def test_tdee_sedentary_equals_bmr_times_1_2():
    assert calculate_tdee(1500, "sedentary") == 1800


def test_tdee_very_active_is_highest_multiplier():
    sedentary = calculate_tdee(1500, "sedentary")
    very_active = calculate_tdee(1500, "very_active")
    assert very_active > sedentary


def test_tdee_rejects_unknown_activity_level():
    try:
        calculate_tdee(1500, "extremely_active")
        assert False, "should have raised"
    except ValueError:
        pass


def test_calorie_target_maintain_equals_tdee():
    result = calculate_calorie_target(2000, "maintain")
    assert result["calorie_target"] == 2000
    assert result["floor_applied"] is False


def test_calorie_target_lose_subtracts_500():
    result = calculate_calorie_target(2000, "lose")
    assert result["calorie_target"] == 1500


def test_calorie_target_gain_adds_500():
    result = calculate_calorie_target(2000, "gain")
    assert result["calorie_target"] == 2500


def test_safety_floor_prevents_dangerously_low_target():
    result = calculate_calorie_target(1400, "lose")
    assert result["calorie_target"] == SAFE_MINIMUM_CALORIES
    assert result["floor_applied"] is True


def test_floor_not_applied_when_target_is_already_safe():
    result = calculate_calorie_target(2200, "lose")
    assert result["floor_applied"] is False


def test_macros_roughly_sum_to_calorie_target():
    macros = calculate_macros(2000, "maintain")
    total_calories = macros["protein_g"] * 4 + macros["carbs_g"] * 4 + macros["fat_g"] * 9
    assert abs(total_calories - 2000) <= 10


def test_lose_goal_has_higher_protein_ratio_than_maintain():
    lose_macros = calculate_macros(2000, "lose")
    maintain_macros = calculate_macros(2000, "maintain")
    assert lose_macros["protein_g"] > maintain_macros["protein_g"]


def test_build_profile_targets_returns_all_expected_fields():
    result = build_profile_targets(70, 175, 30, "male", "moderate", "lose")
    assert "bmr" in result
    assert "tdee" in result
    assert "calorie_target" in result
    assert "macros" in result
    assert result["tdee"] > result["bmr"]

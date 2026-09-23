"""
Core nutrition math. Pure functions, no I/O, so this is fully testable
without a server or database.

Uses the Mifflin-St Jeor equation for BMR - the most widely validated
formula for this. This is general wellness math, not medical advice; a
hard safety floor prevents the calculator from ever recommending an
unsafely low intake regardless of inputs.
"""

ACTIVITY_MULTIPLIERS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}

GOAL_CALORIE_ADJUSTMENT = {
    "lose": -500,
    "maintain": 0,
    "gain": 500,
}

GOAL_MACRO_RATIOS = {
    "lose": {"protein": 0.30, "carbs": 0.40, "fat": 0.30},
    "maintain": {"protein": 0.25, "carbs": 0.45, "fat": 0.30},
    "gain": {"protein": 0.25, "carbs": 0.50, "fat": 0.25},
}

SAFE_MINIMUM_CALORIES = 1200


def calculate_bmr(weight_kg: float, height_cm: float, age: int, sex: str) -> float:
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    if sex == "male":
        return base + 5
    elif sex == "female":
        return base - 161
    else:
        raise ValueError("sex must be 'male' or 'female' (used only for the BMR formula's constant)")


def calculate_tdee(bmr: float, activity_level: str) -> float:
    if activity_level not in ACTIVITY_MULTIPLIERS:
        raise ValueError(f"Unknown activity level: {activity_level}")
    return bmr * ACTIVITY_MULTIPLIERS[activity_level]


def calculate_calorie_target(tdee: float, goal: str) -> dict:
    if goal not in GOAL_CALORIE_ADJUSTMENT:
        raise ValueError(f"Unknown goal: {goal}")

    raw_target = tdee + GOAL_CALORIE_ADJUSTMENT[goal]
    floor_applied = raw_target < SAFE_MINIMUM_CALORIES
    target = max(raw_target, SAFE_MINIMUM_CALORIES)

    return {
        "calorie_target": round(target),
        "floor_applied": floor_applied,
    }


def calculate_macros(calorie_target: int, goal: str) -> dict:
    if goal not in GOAL_MACRO_RATIOS:
        raise ValueError(f"Unknown goal: {goal}")

    ratios = GOAL_MACRO_RATIOS[goal]
    return {
        "protein_g": round(calorie_target * ratios["protein"] / 4),
        "carbs_g": round(calorie_target * ratios["carbs"] / 4),
        "fat_g": round(calorie_target * ratios["fat"] / 9),
    }


def build_profile_targets(weight_kg: float, height_cm: float, age: int, sex: str,
                            activity_level: str, goal: str, calorie_override: float = None) -> dict:
    bmr = calculate_bmr(weight_kg, height_cm, age, sex)
    tdee = calculate_tdee(bmr, activity_level)

    if calorie_override is not None:
        # A manually chosen target still respects the safety floor - the
        # floor exists to protect the person, not just to correct the formula.
        floor_applied = calorie_override < SAFE_MINIMUM_CALORIES
        calorie_target = round(max(calorie_override, SAFE_MINIMUM_CALORIES))
        overridden = True
    else:
        calorie_result = calculate_calorie_target(tdee, goal)
        calorie_target = calorie_result["calorie_target"]
        floor_applied = calorie_result["floor_applied"]
        overridden = False

    macros = calculate_macros(calorie_target, goal)

    return {
        "bmr": round(bmr),
        "tdee": round(tdee),
        "calorie_target": calorie_target,
        "floor_applied": floor_applied,
        "overridden": overridden,
        "macros": macros,
    }

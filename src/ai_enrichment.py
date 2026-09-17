"""
Optional AI layer that adds a friendly summary on top of the
deterministic meal plan. The plan itself works completely without this -
if no ANTHROPIC_API_KEY is set, or the call fails for any reason, callers
get a plain default message instead of a broken page.
"""

import os

import anthropic


def generate_plan_summary(profile_targets: dict, region: str, goal: str) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _default_summary(goal)

    try:
        client = anthropic.Anthropic()
        prompt = (
            f"Write a short (2-3 sentence), encouraging summary for someone starting "
            f"a meal plan. Their goal is to {goal} weight. Their daily target is "
            f"{profile_targets['calorie_target']} calories with "
            f"{profile_targets['macros']['protein_g']}g protein. Meals are drawn from "
            f"{region} cuisine. Keep it warm and practical, not clinical. No medical claims."
        )
        response = client.messages.create(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5"),
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return text.strip() or _default_summary(goal)
    except Exception:
        return _default_summary(goal)


def _default_summary(goal: str) -> str:
    messages = {
        "lose": "Here's your plan, built around your calorie and protein targets to support steady, sustainable progress.",
        "maintain": "Here's your plan, balanced to match your current energy needs.",
        "gain": "Here's your plan, built with a calorie surplus and extra protein to support healthy gains.",
    }
    return messages.get(goal, "Here's your personalized meal plan.")

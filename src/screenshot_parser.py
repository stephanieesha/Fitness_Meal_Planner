"""
Extracts active/move calories from a screenshot of Apple's Fitness or
Health app (the Activity rings view), using Claude's vision capability -
screenshot layouts vary too much across app versions and screens for
reliable OCR regex matching to hold up.

Unlike the deterministic Apple Health XML parser, this involves a real
AI reading step and can be wrong. The app shows the extracted value back
to the user to confirm or correct before saving, rather than trusting it
silently - the parsing logic here only extracts a candidate value, it
never writes to storage itself.
"""

import base64
import json
import os

import anthropic

SUPPORTED_MEDIA_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}


class ScreenshotParseError(Exception):
    pass


def media_type_for_filename(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in SUPPORTED_MEDIA_TYPES:
        raise ScreenshotParseError(
            "Unsupported image format. Upload a .png, .jpg, or .webp screenshot - "
            "a real iOS screenshot is always PNG. If this came from a photo of "
            "your screen instead of an actual screenshot, that won't work as well."
        )
    return SUPPORTED_MEDIA_TYPES[ext]


def extract_json_from_response(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        cleaned = parts[1] if len(parts) > 1 else cleaned
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    return json.loads(cleaned.strip())


def parse_extraction_result(result: dict) -> float:
    if "error" in result:
        raise ScreenshotParseError(result["error"])
    if "active_calories" not in result:
        raise ScreenshotParseError("Could not find an active calories value in this image.")

    try:
        return float(result["active_calories"])
    except (ValueError, TypeError):
        raise ScreenshotParseError("Could not parse the calorie value found in this image.")


def extract_active_calories(image_bytes: bytes, filename: str) -> float:
    media_type = media_type_for_filename(filename)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ScreenshotParseError(
            "Screenshot reading requires an ANTHROPIC_API_KEY to be set - "
            "unlike the full export upload, there's no way to read numbers "
            "off an image without it."
        )

    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    prompt = (
        "This is a screenshot from the Apple Fitness or Health app showing "
        "activity rings. Find the 'Move' or 'Active Energy' calorie value - "
        "the calories burned from activity, not total calories or steps. "
        "Respond with ONLY a JSON object, no other text, no markdown fences: "
        '{"active_calories": <number>} if found, or '
        '{"error": "<short reason>"} if you cannot find a clear active/move '
        "calorie number in this image."
    )

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5"),
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        result = extract_json_from_response(text)
    except json.JSONDecodeError:
        raise ScreenshotParseError("Could not read a clear result from the image - try a clearer screenshot or enter the value manually.")
    except ScreenshotParseError:
        raise
    except Exception as e:
        raise ScreenshotParseError(f"Could not process this image: {type(e).__name__}: {e}")

    return parse_extraction_result(result)

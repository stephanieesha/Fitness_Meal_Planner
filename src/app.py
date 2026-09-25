"""
Meal Planner web app, now with accounts. Every generated plan is saved
against the logged-in user's target history - the foundation Phase 3's
dashboard (weight trend, target history) will read from.

Run with: python src/app.py
Then open: http://localhost:5040
"""

import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

load_dotenv()

from flask import Flask, jsonify, render_template, request, redirect, url_for
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user,
)

from db import get_connection, init_db
from limits import (
    client_ip, int_setting, too_many_auth_attempts, too_many_writes, use_daily_allowance,
)
from auth import (
    create_user, authenticate_user, get_user_by_id,
    save_target_entry, get_target_history,
    EmailAlreadyExists, InvalidCredentials,
)
from nutrition import build_profile_targets
from meal_selector import build_week_plan
from ai_enrichment import generate_plan_summary, _default_summary
from food_library import (
    add_food, get_foods, get_food, delete_food, update_food_category, update_food, nutrition_for,
    FoodNotFound, InvalidCategory, InvalidFoodData, MEAL_CATEGORIES,
)
from day_log import add_day_entry, get_day, delete_day_entry, DayEntryNotFound, InvalidDayEntry
from nutrition_lookup import search_food_nutrition, FoodLookupError
from plan_storage import save_plan, get_latest_plan, update_plan_meal, PlanMealNotFound
from apple_health_parser import parse_upload
from activity_storage import save_activity_log, get_activity_log
from screenshot_parser import extract_active_calories, ScreenshotParseError
from weight_storage import save_weight_entry, get_weight_history, get_latest_weight, delete_weight_entry
import re

ROOT = Path(__file__).parent.parent
app = Flask(__name__, template_folder=str(ROOT / "templates"))
DEV_SECRET_KEY = "dev-only-insecure-key-change-in-env"
app.secret_key = os.environ.get("FLASK_SECRET_KEY", DEV_SECRET_KEY)
if os.environ.get("PRODUCTION", "").lower() == "true":
    if app.secret_key == DEV_SECRET_KEY:
        raise RuntimeError("Set FLASK_SECRET_KEY to a long random value before running in production")
    app.config["SESSION_COOKIE_SECURE"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
# Apple Health exports can genuinely be several hundred MB for a long-time
# user - default Flask has no cap, but an explicit generous limit avoids
# an unbounded upload taking down the server.
app.config["MAX_CONTENT_LENGTH"] = int_setting("MAX_UPLOAD_MB", 500) * 1024 * 1024  # 500MB unless MAX_UPLOAD_MB says otherwise

init_db()

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


@app.before_request
def limit_requests_per_visitor():
    ip = client_ip(request)
    if request.path in ("/login", "/signup") and request.method == "POST":
        if too_many_auth_attempts(ip):
            page = "login.html" if request.path == "/login" else "signup.html"
            return render_template(page, error="Too many attempts - please wait a few minutes and try again"), 429
    elif request.method in ("POST", "PUT", "PATCH", "DELETE") and too_many_writes(ip):
        return jsonify({"error": "Too many requests - please slow down and try again in a minute"}), 429


class User(UserMixin):
    def __init__(self, user_row):
        self.id = str(user_row["id"])
        self.email = user_row["email"]


@login_manager.user_loader
def load_user(user_id):
    conn = get_connection()
    try:
        row = get_user_by_id(conn, int(user_id))
        return User(row) if row else None
    finally:
        conn.close()


VALID_SEX = ("male", "female")
VALID_ACTIVITY = ("sedentary", "light", "moderate", "active", "very_active")
VALID_GOAL = ("lose", "maintain", "gain")
VALID_REGIONS = ("nigeria", "us")


def _safe_next_url():
    """The page a visitor was trying to reach before being sent to log in. Only same-site paths are
    followed, so a crafted link cannot bounce someone to another website."""
    target = request.args.get("next", "")
    if target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return None


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "GET":
        return render_template("signup.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not email or len(password) < 8:
        return render_template("signup.html", error="Email is required and password must be at least 8 characters"), 400

    conn = get_connection()
    try:
        if not use_daily_allowance(conn, "signup", "DAILY_SIGNUP_LIMIT"):
            return render_template("signup.html", error="Sign-ups are paused for today - please try again tomorrow"), 429
        user_row = create_user(conn, email, password)
        login_user(User(user_row))
        return redirect(url_for("index"))
    except EmailAlreadyExists:
        return render_template("signup.html", error="An account with that email already exists"), 400
    finally:
        conn.close()


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    conn = get_connection()
    try:
        user_row = authenticate_user(conn, email, password)
        login_user(User(user_row))
        return redirect(_safe_next_url() or url_for("index"))
    except InvalidCredentials:
        return render_template("login.html", error="Incorrect email or password"), 401
    finally:
        conn.close()


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/api/generate-plan", methods=["POST"])
@login_required
def generate_plan():
    data = request.get_json() or {}

    required = ["weight_kg", "height_cm", "age", "sex", "activity_level", "goal", "region"]
    missing = [f for f in required if data.get(f) in (None, "")]
    if missing:
        return jsonify({"error": f"Missing required field(s): {', '.join(missing)}"}), 400

    if data["sex"] not in VALID_SEX:
        return jsonify({"error": f"sex must be one of {VALID_SEX}"}), 400
    if data["activity_level"] not in VALID_ACTIVITY:
        return jsonify({"error": f"activity_level must be one of {VALID_ACTIVITY}"}), 400
    if data["goal"] not in VALID_GOAL:
        return jsonify({"error": f"goal must be one of {VALID_GOAL}"}), 400
    if data["region"] not in VALID_REGIONS:
        return jsonify({"error": f"region must be one of {VALID_REGIONS}"}), 400

    try:
        weight_kg = float(data["weight_kg"])
        height_cm = float(data["height_cm"])
        age = int(data["age"])
        days = int(data.get("days", 7))
    except (ValueError, TypeError):
        return jsonify({"error": "weight_kg, height_cm, age, and days must be numbers"}), 400

    calorie_override = None
    if data.get("calorie_override") not in (None, ""):
        try:
            calorie_override = float(data["calorie_override"])
        except (ValueError, TypeError):
            return jsonify({"error": "calorie_override must be a number"}), 400
        if not (500 <= calorie_override <= 10000):
            return jsonify({"error": "calorie_override must be between 500 and 10000"}), 400

    if not (1 <= days <= 14):
        return jsonify({"error": "days must be between 1 and 14"}), 400
    if not (20 <= weight_kg <= 500 and 50 <= height_cm <= 260 and 5 <= age <= 120):
        return jsonify({"error": "weight_kg (20-500), height_cm (50-260) and age (5-120) must be realistic values"}), 400

    profile_targets = build_profile_targets(
        weight_kg, height_cm, age, data["sex"], data["activity_level"], data["goal"],
        calorie_override=calorie_override,
    )

    week_plan = build_week_plan(
        data["region"], profile_targets["calorie_target"], days=days,
        meal_types=("breakfast", "lunch", "dinner", "snack"),
    )
    conn = get_connection()
    try:
        if use_daily_allowance(conn, "summary", "DAILY_SUMMARY_LIMIT"):
            summary = generate_plan_summary(profile_targets, data["region"], data["goal"])
        else:
            summary = _default_summary(data["goal"])

        profile_inputs = {
            "weight_kg": weight_kg, "height_cm": height_cm, "age": age,
            "sex": data["sex"], "activity_level": data["activity_level"],
            "goal": data["goal"], "region": data["region"],
        }
        save_target_entry(conn, int(current_user.id), profile_inputs, profile_targets)
        # Persisted so the plan survives a page reload and individual
        # meals can be edited afterward - without this, editing would
        # have nothing durable to target.
        save_plan(conn, int(current_user.id), week_plan)
        # Return the plan as saved, so every meal carries its id and can be edited straight away
        saved_plan = get_latest_plan(conn, int(current_user.id))
    finally:
        conn.close()

    return jsonify({
        "profile_targets": profile_targets,
        "summary": summary,
        "plan": saved_plan,
    })


@app.route("/api/target-history")
@login_required
def target_history():
    conn = get_connection()
    try:
        history = get_target_history(conn, int(current_user.id))
        return jsonify(history)
    finally:
        conn.close()


@app.route("/api/plan/latest")
@login_required
def latest_plan():
    conn = get_connection()
    try:
        return jsonify(get_latest_plan(conn, int(current_user.id)))
    finally:
        conn.close()


@app.route("/api/plan/meals/<int:meal_id>", methods=["PATCH"])
@login_required
def edit_plan_meal(meal_id):
    data = request.get_json() or {}
    conn = get_connection()

    try:
        if data.get("food_id"):
            # Sourced from the user's own food library, scaled by grams
            # so the calories genuinely reflect what was actually chosen,
            # not left stale from whatever meal this is replacing.
            try:
                food_id = int(data["food_id"])
            except (ValueError, TypeError):
                return jsonify({"error": "food_id must be a number"}), 400

            try:
                food = get_food(conn, int(current_user.id), food_id)
            except FoodNotFound:
                return jsonify({"error": "Food not found in your library"}), 404

            # The amount is in the food's own unit (grams, slices, eggs...),
            # defaulting to one of its servings. "grams" is still accepted
            # from older pages.
            raw_quantity = data.get("quantity", data.get("grams"))
            if raw_quantity in (None, ""):
                quantity = food["serving_size"]
            else:
                try:
                    quantity = float(raw_quantity)
                except (ValueError, TypeError):
                    return jsonify({"error": "quantity must be a number"}), 400
                if quantity < 0:
                    return jsonify({"error": "quantity must be at least 0"}), 400

            updated_values = {
                "food_name": food["name"],
                **nutrition_for(food, quantity),
                "food_id": food["id"],
                "grams": quantity,
                "unit": food["serving_unit"],
            }
        else:
            # Manual entry: just a name and a calorie count - macros
            # default to 0 since none were supplied. Grams is optional here
            # too - useful while trial-weighing portions before they're in
            # the food library yet, but it's a label only, not part of the
            # calorie math (there's no per-100g figure to scale from).
            food_name = (data.get("food_name") or "").strip()
            if not food_name:
                return jsonify({"error": "food_name is required for a manual entry"}), 400
            try:
                calories = float(data["calories"])
            except (ValueError, TypeError, KeyError):
                return jsonify({"error": "calories must be a number"}), 400

            manual_grams = None
            if data.get("grams") not in (None, ""):
                try:
                    manual_grams = float(data["grams"])
                except (ValueError, TypeError):
                    return jsonify({"error": "grams must be a number"}), 400

            updated_values = {
                "food_name": food_name,
                "calories": calories,
                "protein_g": 0,
                "carbs_g": 0,
                "fat_g": 0,
                "food_id": None,
                "grams": manual_grams,
                "unit": ((data.get("unit") or "").strip()[:20] or "g") if manual_grams is not None else None,
            }

        result = update_plan_meal(conn, int(current_user.id), meal_id, updated_values)
        return jsonify(result)
    except PlanMealNotFound:
        return jsonify({"error": "Meal not found"}), 404
    finally:
        conn.close()


@app.route("/foods")
@login_required
def foods_page():
    return render_template("foods.html")


@app.route("/api/foods", methods=["GET"])
@login_required
def list_foods():
    conn = get_connection()
    try:
        return jsonify(get_foods(conn, int(current_user.id)))
    finally:
        conn.close()


@app.route("/api/foods", methods=["POST"])
@login_required
def create_food():
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    meal_category = data.get("meal_category", "other")

    if not name:
        return jsonify({"error": "Food name is required"}), 400
    if meal_category not in MEAL_CATEGORIES:
        return jsonify({"error": f"meal_category must be one of {MEAL_CATEGORIES}"}), 400

    # Manual mode: if macros were explicitly provided (the fallback path
    # after an automatic lookup failed), use them directly and skip the
    # lookup entirely. Micronutrients (calcium/vitamin C/omega-3) are
    # optional even in manual mode - defaulting to 0 rather than forcing
    # the user to look those up too defeats the point of this feature.
    max_foods = int_setting("MAX_FOODS_PER_USER")
    if max_foods:
        cap_conn = get_connection()
        try:
            if len(get_foods(cap_conn, int(current_user.id))) >= max_foods:
                return jsonify({"error": f"Your food library is full ({max_foods} foods) - remove one first"}), 400
        finally:
            cap_conn.close()

    # Your own values: calories for a serving you choose (10 g, 1 slice,
    # 1 egg...) or a whole item split into servings, or the older
    # per-100g fields. Anything given here skips the automatic lookup.
    manual_fields = ["calories_per_100g", "protein_per_100g", "carbs_per_100g", "fat_per_100g"]
    is_manual = (
        data.get("serving_calories") not in (None, "")
        or data.get("whole_calories") not in (None, "")
        or all(data.get(f) not in (None, "") for f in manual_fields)
    )
    if is_manual:
        conn = get_connection()
        try:
            food = add_food(conn, int(current_user.id), {**data, "name": name, "meal_category": meal_category})
            return jsonify(food), 201
        except InvalidFoodData as e:
            return jsonify({"error": str(e)}), 400
        finally:
            conn.close()

    # Automatic mode: look up average nutrition data so the user doesn't
    # have to find or enter it themselves. Category still comes from the
    # user's selection - USDA has no concept of "which meal is this for".
    lookup_conn = get_connection()
    try:
        lookup_allowed = use_daily_allowance(lookup_conn, "food_lookup", "DAILY_FOOD_LOOKUP_LIMIT")
    finally:
        lookup_conn.close()
    if not lookup_allowed:
        return jsonify({
            "error": "The daily limit for automatic nutrition lookups has been reached - enter the values by hand",
            "manual_entry_required": True,
        }), 422

    try:
        looked_up = search_food_nutrition(name)
    except FoodLookupError as e:
        return jsonify({
            "error": str(e),
            "manual_entry_required": True,
        }), 422

    conn = get_connection()
    try:
        food = add_food(conn, int(current_user.id), {**looked_up, "meal_category": meal_category})
        food["matched_description"] = looked_up["matched_description"]
        return jsonify(food), 201
    finally:
        conn.close()


@app.route("/api/foods/<int:food_id>", methods=["PUT"])
@login_required
def edit_food(food_id):
    data = request.get_json() or {}
    conn = get_connection()
    try:
        return jsonify(update_food(conn, int(current_user.id), food_id, data))
    except (InvalidFoodData, InvalidCategory) as e:
        return jsonify({"error": str(e)}), 400
    except FoodNotFound:
        return jsonify({"error": "Food not found"}), 404
    finally:
        conn.close()


@app.route("/api/day-log", methods=["GET"])
@login_required
def day_log_for_date():
    conn = get_connection()
    try:
        return jsonify(get_day(conn, int(current_user.id), request.args.get("date", "")))
    except InvalidDayEntry as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@app.route("/api/day-log", methods=["POST"])
@login_required
def add_to_day_log():
    data = request.get_json() or {}
    conn = get_connection()
    try:
        entry = add_day_entry(conn, int(current_user.id), data)
        day = get_day(conn, int(current_user.id), entry["date"])
        return jsonify({"entry": entry, "total_calories": day["total_calories"]}), 201
    except InvalidDayEntry as e:
        return jsonify({"error": str(e)}), 400
    except FoodNotFound:
        return jsonify({"error": "Food not found in your library"}), 404
    finally:
        conn.close()


@app.route("/api/day-log/<int:entry_id>", methods=["DELETE"])
@login_required
def remove_from_day_log(entry_id):
    conn = get_connection()
    try:
        delete_day_entry(conn, int(current_user.id), entry_id)
        return jsonify({"deleted": entry_id})
    except DayEntryNotFound:
        return jsonify({"error": "Entry not found"}), 404
    finally:
        conn.close()


@app.route("/api/foods/<int:food_id>/category", methods=["PATCH"])
@login_required
def change_food_category(food_id):
    data = request.get_json() or {}
    category = data.get("meal_category")

    conn = get_connection()
    try:
        food = update_food_category(conn, int(current_user.id), food_id, category)
        return jsonify(food)
    except InvalidCategory as e:
        return jsonify({"error": str(e)}), 400
    except FoodNotFound:
        return jsonify({"error": "Food not found"}), 404
    finally:
        conn.close()


@app.route("/api/foods/<int:food_id>", methods=["DELETE"])
@login_required
def remove_food(food_id):
    conn = get_connection()
    try:
        delete_food(conn, int(current_user.id), food_id)
        return jsonify({"deleted": food_id})
    except FoodNotFound:
        return jsonify({"error": "Food not found"}), 404
    finally:
        conn.close()


@app.route("/weight")
@login_required
def weight_page():
    return render_template("weight.html")


@app.route("/api/weight", methods=["GET"])
@login_required
def list_weight():
    conn = get_connection()
    try:
        return jsonify(get_weight_history(conn, int(current_user.id)))
    finally:
        conn.close()


@app.route("/api/weight/latest", methods=["GET"])
@login_required
def latest_weight():
    conn = get_connection()
    try:
        entry = get_latest_weight(conn, int(current_user.id))
        return jsonify(entry)  # null if nothing logged yet
    finally:
        conn.close()


@app.route("/api/weight", methods=["POST"])
@login_required
def log_weight():
    data = request.get_json() or {}
    date_str = (data.get("logged_date") or "").strip()

    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return jsonify({"error": "logged_date must be in YYYY-MM-DD format"}), 400
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return jsonify({"error": "logged_date must be a real calendar date"}), 400

    try:
        weight_kg = float(data.get("weight_kg"))
    except (TypeError, ValueError):
        return jsonify({"error": "weight_kg must be a number"}), 400
    if not (20 <= weight_kg <= 500):
        return jsonify({"error": "weight_kg must be a realistic value (20-500)"}), 400

    conn = get_connection()
    try:
        entry = save_weight_entry(conn, int(current_user.id), weight_kg, date_str)
        return jsonify(entry), 201
    finally:
        conn.close()


@app.route("/api/weight/<int:entry_id>", methods=["DELETE"])
@login_required
def remove_weight(entry_id):
    conn = get_connection()
    try:
        delete_weight_entry(conn, int(current_user.id), entry_id)
        return jsonify({"deleted": entry_id})
    finally:
        conn.close()


@app.route("/activity")
@login_required
def activity_page():
    return render_template("activity.html")


@app.route("/api/activity/upload", methods=["POST"])
@login_required
def upload_activity():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    uploaded = request.files["file"]
    if not uploaded.filename:
        return jsonify({"error": "No file selected"}), 400

    if not (uploaded.filename.lower().endswith(".xml") or uploaded.filename.lower().endswith(".zip")):
        return jsonify({"error": "Upload your Apple Health export as a .zip or .xml file"}), 400

    try:
        file_bytes = uploaded.read()
        daily_totals = parse_upload(file_bytes, uploaded.filename)
    except Exception as e:
        print(f"[activity_upload] Failed to parse upload: {type(e).__name__}: {e}")
        return jsonify({"error": f"Could not parse this file: {type(e).__name__}: {e}"}), 400

    if not daily_totals:
        return jsonify({"error": "No Active Energy data found in this export"}), 422

    conn = get_connection()
    try:
        days_written = save_activity_log(conn, int(current_user.id), daily_totals)
        return jsonify({
            "days_processed": days_written,
            "date_range": [min(daily_totals), max(daily_totals)],
        })
    finally:
        conn.close()


@app.route("/api/activity")
@login_required
def list_activity():
    conn = get_connection()
    try:
        return jsonify(get_activity_log(conn, int(current_user.id)))
    finally:
        conn.close()


@app.route("/api/activity/screenshot/extract", methods=["POST"])
@login_required
def extract_activity_screenshot():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    uploaded = request.files["file"]
    if not uploaded.filename:
        return jsonify({"error": "No file selected"}), 400

    cap_conn = get_connection()
    try:
        allowed = use_daily_allowance(cap_conn, "screenshot", "DAILY_SCREENSHOT_LIMIT")
    finally:
        cap_conn.close()
    if not allowed:
        return jsonify({"error": "The daily limit for reading screenshots has been reached - enter the day by hand"}), 429

    try:
        calories = extract_active_calories(uploaded.read(), uploaded.filename)
        return jsonify({"active_calories": calories})
    except ScreenshotParseError as e:
        return jsonify({"error": str(e)}), 422


@app.route("/api/activity/manual", methods=["POST"])
@app.route("/api/activity/screenshot/confirm", methods=["POST"])
@login_required
def confirm_activity_screenshot():
    # Separate from extract on purpose - the extracted value is shown to
    # the user first and only written here once they confirm or correct
    # it, since AI-read numbers off an image can be wrong.
    data = request.get_json() or {}
    date_str = data.get("date", "")

    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return jsonify({"error": "date must be in YYYY-MM-DD format"}), 400
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return jsonify({"error": "date must be a real calendar date"}), 400

    try:
        calories = float(data.get("active_calories"))
    except (TypeError, ValueError):
        return jsonify({"error": "active_calories must be a number"}), 400

    conn = get_connection()
    try:
        save_activity_log(conn, int(current_user.id), {date_str: calories})
        return jsonify({"saved": True, "date": date_str, "active_calories": calories})
    finally:
        conn.close()


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "1") == "1", port=int(os.environ.get("PORT", "5040")))
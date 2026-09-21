"""
App-level tests for the parts added for a public deployment: usage limits, validation, and bug fixes.
They run on SQLite by default, or on PostgreSQL when DATABASE_URL is set.
"""

import io
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import db

# The app creates its database when it is imported, so point it at a scratch file first.
_scratch = Path(tempfile.mkdtemp()) / "import.db"
db.DB_PATH = _scratch

import app as app_module  # noqa: E402
import limits  # noqa: E402
from apple_health_parser import parse_upload  # noqa: E402

PASSWORD = "Password-123"
PROFILE = {
    "weight_kg": 70, "height_cm": 170, "age": 30, "sex": "female",
    "activity_level": "sedentary", "goal": "maintain", "region": "us", "days": 5,
}
FOOD = {"name": "Rice", "meal_category": "lunch", "calories_per_100g": 130,
        "protein_per_100g": 2.7, "carbs_per_100g": 28, "fat_per_100g": 0.3}


@pytest.fixture(autouse=True)
def fresh_database(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    limits.reset_rate_limits()
    yield
    limits.reset_rate_limits()


@pytest.fixture
def client():
    return app_module.app.test_client()


@pytest.fixture
def user(client):
    """A signed-up, logged-in visitor."""
    response = client.post("/signup", data={"email": "tester@example.com", "password": PASSWORD})
    assert response.status_code == 302
    return client


# ---------- bug fixes ----------

def test_generated_plan_meals_have_ids_so_they_can_be_edited_immediately(user):
    plan = user.post("/api/generate-plan", json=PROFILE).get_json()["plan"]
    assert len(plan) == 5
    for day in plan:
        for meal in day["meals"]:
            assert isinstance(meal["id"], int)


def test_a_meal_from_a_fresh_plan_can_be_edited(user):
    plan = user.post("/api/generate-plan", json=PROFILE).get_json()["plan"]
    meal_id = plan[0]["meals"][0]["id"]
    edited = user.patch(f"/api/plan/meals/{meal_id}", json={"food_name": "Jollof", "calories": 500})
    assert edited.status_code == 200
    assert edited.get_json()["meal"]["name"] == "Jollof"


def test_a_non_numeric_food_id_is_a_client_error(user):
    plan = user.post("/api/generate-plan", json=PROFILE).get_json()["plan"]
    meal_id = plan[0]["meals"][0]["id"]
    response = user.patch(f"/api/plan/meals/{meal_id}", json={"food_id": "No foods in your library yet", "grams": "100"})
    assert response.status_code == 400
    assert "food_id must be a number" in response.get_json()["error"]


def test_manual_activity_entry_is_saved(user):
    response = user.post("/api/activity/manual", json={"date": "2001-06-02", "active_calories": 300})
    assert response.status_code == 200
    assert response.get_json() == {"saved": True, "date": "2001-06-02", "active_calories": 300.0}
    assert {"activity_date": "2001-06-02", "active_calories": 300.0} in user.get("/api/activity").get_json()


def test_login_returns_you_to_the_page_you_asked_for(client):
    client.post("/signup", data={"email": "back@example.com", "password": PASSWORD})
    client.get("/logout")
    redirect = client.get("/foods")
    assert "/login?next=%2Ffoods" in redirect.headers["Location"]
    response = client.post("/login?next=/foods", data={"email": "back@example.com", "password": PASSWORD})
    assert response.headers["Location"].endswith("/foods")


@pytest.mark.parametrize("target", ["//evil.example", "/\\evil.example", "https://evil.example", "javascript:alert(1)"])
def test_login_never_redirects_to_another_site(client, target):
    client.post("/signup", data={"email": "safe@example.com", "password": PASSWORD})
    client.get("/logout")
    response = client.post("/login", query_string={"next": target}, data={"email": "safe@example.com", "password": PASSWORD})
    assert response.status_code == 302
    assert "evil.example" not in response.headers["Location"]
    assert "javascript" not in response.headers["Location"]


def test_empty_library_option_has_no_value_so_the_page_asks_for_a_food():
    html = (Path(__file__).parent.parent / "templates" / "index.html").read_text()
    assert '<option value="">No foods in your library yet</option>' in html


def test_pages_escape_user_text():
    templates = Path(__file__).parent.parent / "templates"
    assert "${esc(meal.name)}" in (templates / "index.html").read_text()
    assert "${esc(f.name)}" in (templates / "foods.html").read_text()


# ---------- validation ----------

@pytest.mark.parametrize("change", [{"days": 0}, {"days": 15}, {"days": 100000}, {"weight_kg": 5}, {"age": 500}, {"height_cm": 5}])
def test_unrealistic_plan_inputs_are_rejected(user, change):
    assert user.post("/api/generate-plan", json={**PROFILE, **change}).status_code == 400


# ---------- usage limits (all off unless configured) ----------

def test_daily_summary_cap_falls_back_to_the_standard_summary(user, monkeypatch):
    monkeypatch.setenv("DAILY_SUMMARY_LIMIT", "1")
    monkeypatch.setattr(app_module, "generate_plan_summary", lambda *a, **k: "WRITTEN BY CLAUDE")
    first = user.post("/api/generate-plan", json=PROFILE).get_json()["summary"]
    second = user.post("/api/generate-plan", json=PROFILE).get_json()["summary"]
    assert first == "WRITTEN BY CLAUDE"
    assert second != "WRITTEN BY CLAUDE" and second


def test_daily_food_lookup_cap_asks_for_manual_entry(user, monkeypatch):
    monkeypatch.setenv("DAILY_FOOD_LOOKUP_LIMIT", "1")
    monkeypatch.setattr(app_module, "search_food_nutrition", lambda name: {
        "name": name, "calories_per_100g": 100, "protein_per_100g": 1, "carbs_per_100g": 10, "fat_per_100g": 1,
        "calcium_mg_per_100g": 0, "vitamin_c_mg_per_100g": 0, "omega3_g_per_100g": 0, "matched_description": "x"})
    assert user.post("/api/foods", json={"name": "Oats"}).status_code == 201
    capped = user.post("/api/foods", json={"name": "Beans"})
    assert capped.status_code == 422
    assert capped.get_json()["manual_entry_required"] is True
    assert user.post("/api/foods", json=FOOD).status_code == 201  # entering values by hand still works


def test_daily_screenshot_cap(user, monkeypatch):
    monkeypatch.setenv("DAILY_SCREENSHOT_LIMIT", "1")
    monkeypatch.setattr(app_module, "extract_active_calories", lambda data, name: 500)
    upload = lambda: {"file": (io.BytesIO(b"png"), "rings.png")}
    assert user.post("/api/activity/screenshot/extract", data=upload(), content_type="multipart/form-data").status_code == 200
    capped = user.post("/api/activity/screenshot/extract", data=upload(), content_type="multipart/form-data")
    assert capped.status_code == 429


def test_daily_signup_cap(client, monkeypatch):
    monkeypatch.setenv("DAILY_SIGNUP_LIMIT", "1")
    assert client.post("/signup", data={"email": "one@example.com", "password": PASSWORD}).status_code == 302
    client.get("/logout")
    assert client.post("/signup", data={"email": "two@example.com", "password": PASSWORD}).status_code == 429


def test_food_library_size_cap(user, monkeypatch):
    monkeypatch.setenv("MAX_FOODS_PER_USER", "1")
    assert user.post("/api/foods", json=FOOD).status_code == 201
    full = user.post("/api/foods", json={**FOOD, "name": "Beans"})
    assert full.status_code == 400 and "full" in full.get_json()["error"]


def test_only_the_newest_plans_are_kept(user, monkeypatch):
    monkeypatch.setenv("KEEP_PLAN_BATCHES", "2")
    for _ in range(4):
        user.post("/api/generate-plan", json=PROFILE)
    conn = db.get_connection()
    try:
        batches = conn.execute("SELECT COUNT(DISTINCT plan_batch) AS n FROM plan_meals").fetchone()["n"]
    finally:
        conn.close()
    assert batches == 2
    assert len(user.get("/api/plan/latest").get_json()) == 5  # the latest plan is intact


def test_writes_are_rate_limited_but_reads_are_not(user, monkeypatch):
    monkeypatch.setenv("WRITE_LIMIT_PER_MINUTE", "2")
    codes = [user.post("/api/foods", json={**FOOD, "name": f"F{i}"}).status_code for i in range(4)]
    assert codes == [201, 201, 429, 429]
    assert user.get("/api/foods").status_code == 200


def test_login_attempts_are_rate_limited(client, monkeypatch):
    monkeypatch.setenv("AUTH_LIMIT_PER_15_MIN", "2")
    codes = [client.post("/login", data={"email": "x@example.com", "password": "wrong"}).status_code for _ in range(4)]
    assert codes == [401, 401, 429, 429]


def test_oversized_export_is_refused_before_it_is_unzipped(monkeypatch):
    monkeypatch.setenv("MAX_EXPORT_XML_MB", "1")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("export.xml", "<HealthData>" + "x" * (2 * 1024 * 1024) + "</HealthData>")
    with pytest.raises(ValueError, match="larger than"):
        parse_upload(buffer.getvalue(), "export.zip")


def test_production_refuses_to_start_with_the_default_secret_key():
    import subprocess

    code = "import sys; sys.path.insert(0, 'src'); import app"
    env = {"PRODUCTION": "true", "PATH": "/usr/bin:/bin"}
    result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).parent.parent,
                            env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "FLASK_SECRET_KEY" in result.stderr


def test_an_impossible_date_is_rejected(user):
    response = user.post("/api/activity/manual", json={"date": "2001-13-45", "active_calories": 300})
    assert response.status_code == 400

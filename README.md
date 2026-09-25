# Meal Planner

Generates a personalized, region-appropriate meal plan from your stats,
activity level, and goal, with real portion scaling and a hard safety
floor, not just a generic calorie chart. Now with accounts: every plan
you generate is saved to your own history.

## Project phases

- **Phase 1: Accounts + database foundation.** Signup, login, password
  hashing, and a real SQLite database. Every generated plan saves a
  target-history entry against your account.
- **Phase 2: Personal food library.** Add/view/remove foods you like,
  each with calories, macros (protein/carbs/fat), and micronutrients
  (calcium, vitamin C, omega-3) per 100g, categorized as breakfast,
  lunch, dinner, snack, or other. Foods display grouped by category
  rather than one long list, with a search box to filter by name and a
  per-food dropdown to re-categorize without deleting and re-adding.
  Fully isolated per user (verified: one user cannot see, delete, or
  re-categorize another user's foods, even by guessing an id). Nutrition
  data is looked up automatically from USDA FoodData Central when you
  add a food by name, with a manual-entry fallback if a food can't be
  matched. Calories-per-100g shows as a hover tooltip.
- **Your own servings, whole items, and notes.** Foods are no longer
  fixed at 100g: each has a serving you choose (10 g of cashews, 1 slice,
  1 egg, 1000 ml of yoghurt) and the calories in it. A serving can be cut
  from a whole item: enter the loaf's calories and how many slices it
  makes, and the per-slice calories are worked out (and recalculated if
  you later change either number). Every food can carry notes and be
  edited in place. Existing foods carry over as "per 100 g".
- **Daily calorie total.** On the meal plan page, add what you actually
  ate on a date (from your foods, in their own units, or typed in by
  hand) and see the day's total by meal, against an adjustable target
  range (default 1200-1500 kcal), alongside calories burned if activity
  was logged for that day.
- **Phase 3 (not built yet):** Dashboard with weight trend chart and
  target history view, reading from the data Phase 1 already saves.
- **Phase 4 (partial): Table-view plan with inline editing.** Generated
  plans now persist (previously they existed only in the response of one
  request) and display as a table - days as rows, meal types as columns
  - matching a real "food timetable" format. Click "Edit" on any cell to
  replace that meal either by picking from your food library (amount in
  the food's own unit, calories/macros scaled accordingly) or typing a food name and
  calorie count directly. Either way, the day's total recalculates to
  reflect the actual edit, not the original generated value. Verified:
  editing one meal correctly changes only that day's total, and the
  change persists across a page reload. Still to come from the original
  Phase 4 scope: suggesting a replacement meal when you ask for a swap
  rather than only supporting a direct pick, and the downloadable table
  export.
- **Phase 5: Apple Health activity upload.** Upload your Health app
  export (the .zip Apple generates via Profile → Export All Health Data)
  to extract daily Active Energy Burned - the data behind the Watch's
  Move ring. Handles the real export format (a large XML file, often
  hundreds of MB, sometimes wrapped in a zip) using a memory-safe
  streaming parser rather than loading the whole file at once - verified
  against a synthetic 50,000-record file, not just a tiny fixture.
  Re-uploading a newer export with overlapping dates updates those days
  rather than duplicating them. Shows a running average and a day-by-day
  list. **I don't have a real Apple Health export to test this against**
  - built carefully against Apple's documented, stable XML format and
  tested thoroughly with a realistic fixture (confirmed correct via a
  real end-to-end upload through the actual HTTP endpoint), but the
  first real export is the true test. If the real file's structure
  differs from what's coded here in some way, tell me the exact error
  and I'll fix the parsing. Not yet wired into the calorie-target math
  (still uses the activity-level dropdown, not your measured active
  calories) - that integration is a natural next step once this data
  exists.

## Why the safety floor matters

Naive calorie-deficit math can recommend dangerously low intakes for
smaller or less active people. This enforces a floor of 1200 kcal/day
regardless of inputs, and tells the user plainly when that floor
overrode their calculated target.

## Nutrition lookup

Adding a food by name automatically queries USDA FoodData Central for
its average calories, macros, and select micronutrients (calcium,
vitamin C, omega-3) per 100g. Foundation/SR Legacy entries are preferred
over Branded ones, since branded products sometimes report values
per-serving rather than per-100g. If nothing matches, the UI reveals a
manual-entry fallback instead of failing silently.

**Omega-3 is a sum, not a single USDA field** - USDA reports it as
separate fatty acids (ALA, EPA, DPA, DHA depending on the food), not one
combined number. This sums whichever are present for a given food, and
genuinely shows 0 for foods where USDA's entry doesn't break out fatty
acid detail (common for many legacy/branded entries) - that's a real
data limitation, not a bug.

**Confirmed working against the live API** - this required one fix on
your end unrelated to the code itself: Python installed from python.org
on macOS doesn't have access to your system's trusted certificates by
default, causing every HTTPS request to fail with
`CERTIFICATE_VERIFY_FAILED` until you run the "Install Certificates.command"
script that ships with your Python installation (in `/Applications/Python 3.x/`).
Once that ran once, the live lookup worked correctly on the first real try.

## Region-flexible by design

Meals are tagged by region (`data/meals_nigeria.json`, `data/meals_us.json`).
Adding a new region is a new JSON file with the same shape, not a rewrite
of the selection logic.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Set FLASK_SECRET_KEY to a real random value (see .env.example for how)
# ANTHROPIC_API_KEY is optional - only needed for AI-generated summaries
python src/app.py      # localhost:5040
```

First visit redirects to `/signup` - create an account, then you're
taken to the meal plan form.

## Running the tests

```bash
pytest tests/
```
92 tests: nutrition math (including the safety floor and known BMR
values), meal selection (variety tracking, portion scaling, real
integration against both regional databases), auth/database logic
(password hashing, duplicate email rejection, per-user data isolation),
food library logic (including the security-critical cases: one user
cannot delete or re-categorize another user's food), nutrition-lookup
parsing (tested against realistic USDA API response fixtures), plan
persistence (including a real bug this caught: SQLite's `datetime('now')`
only has second-level precision, fixed with an id tiebreaker), and Apple
Health parsing (including a 50,000-record synthetic file confirming the
streaming parser is actually memory-safe, not just correct on a tiny
fixture, plus the re-upload upsert behavior) - all run without touching
the real database or a live network call.

## Data storage

SQLite, stored at `data/app.db` (gitignored - never commit this, it
contains real user password hashes once you start using it for real).
Three tables so far: `users`, `target_history`, and `foods`. Phase 5
will add an `activity_log` table.

## Not medical advice

This is general wellness math using standard, widely-used formulas, not
personalized medical or nutritional guidance.

## Security notes for later

- Passwords are hashed with Werkzeug's `generate_password_hash`
  (PBKDF2), never stored in plaintext - confirmed by a test.
- `FLASK_SECRET_KEY` must be a real random value before this touches
  any real data beyond your own local testing - the fallback dev key in
  the code is intentionally insecure and only there so the app doesn't
  crash if you forget to set it locally.
- No password reset flow yet - if you forget your password during
  testing, the fastest fix is deleting `data/app.db` and signing up again
  (this wipes all saved history, so only do this in testing).

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import AliasChoices, BaseModel, Field
from sqlalchemy.orm import Session

from app.config import GOOGLE_API_KEY, NUTRITION_MODEL, WORKOUT_MODEL
from app.database.database import get_db
from app.database.models import User, WorkoutPlan

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


class UserInput(BaseModel):
	user_id: int | None = None
	name: str = Field(min_length=1, max_length=100, validation_alias=AliasChoices("name", "username"))
	age: int = Field(ge=13, le=100)
	weight: float = Field(gt=0, le=500)
	goal: str = Field(pattern="^(strength|weight-loss|fitness)$")
	intensity: str = Field(pattern="^(beginner|moderate|advanced)$")


class GeneratePlanInput(UserInput):
	user_id: int = Field(gt=0)


class PlanUpdate(BaseModel):
	updated_text: str = Field(min_length=1, max_length=20000)


class FeedbackRequest(BaseModel):
	feedback: str = Field(min_length=1, max_length=2000)


def save_user(db: Session, user_id: int | None, name: str, age: int, weight: float, goal: str, intensity: str):
	user = db.query(User).filter_by(id=user_id).first() if user_id is not None else None
	if user is None:
		user = User(id=user_id, name=name, age=age, weight=weight, goal=goal, intensity=intensity, schedule=7)
		db.add(user)
	else:
		user.name = name
		user.age = age
		user.weight = weight
		user.goal = goal
		user.intensity = intensity

	db.commit()
	db.refresh(user)
	return user


def save_plan(db: Session, user_id: int, plan: str):
	if db.query(User).filter_by(id=user_id).first() is None:
		raise HTTPException(status_code=404, detail="User not found")
	workout = WorkoutPlan(user_id=user_id, original_plan=plan)
	db.add(workout)
	db.commit()
	db.refresh(workout)
	return workout


def update_plan(db: Session, user_id: int, updated_text: str):
	workout = db.query(WorkoutPlan).filter_by(user_id=user_id).order_by(WorkoutPlan.id.desc()).first()
	if workout is None:
		raise HTTPException(status_code=404, detail="No plan found for this user")
	workout.updated_plan = updated_text
	db.commit()
	db.refresh(workout)
	return workout


def get_original_plan(db: Session, user_id: int):
	workout = db.query(WorkoutPlan).filter_by(user_id=user_id).order_by(WorkoutPlan.id.desc()).first()
	return workout.original_plan if workout else None


def get_user(db: Session, user_id: int):
	return db.query(User).filter(User.id == user_id).first()


@router.get("/", response_class=HTMLResponse)
async def home():
	page = Path(__file__).resolve().parent.parent / "templates" / "index.html"
	return HTMLResponse(page.read_text(encoding="utf-8"))


@router.get("/view-all-users", response_class=HTMLResponse)
def view_all_users(request: Request, db: Session = Depends(get_db)):
	users = db.query(User).order_by(User.id.asc()).all()
	return templates.TemplateResponse(
		request=request,
		name="all_users.html",
		context={"users": users},
	)


@router.post("/api/users")
def create_or_update_user(payload: UserInput, db: Session = Depends(get_db)):
	user = save_user(db, payload.user_id, payload.name, payload.age, payload.weight, payload.goal, payload.intensity)
	return {"id": user.id, "name": user.name, "goal": user.goal}


@router.get("/api/users/{user_id}")
def fetch_user(user_id: int, db: Session = Depends(get_db)):
	user = get_user(db, user_id)
	if user is None:
		raise HTTPException(status_code=404, detail="User not found")
	return {"id": user.id, "name": user.name, "age": user.age, "weight": user.weight, "goal": user.goal, "intensity": user.intensity}


@router.get("/api/users/{user_id}/plan")
def fetch_plan(user_id: int, db: Session = Depends(get_db)):
	user = get_user(db, user_id)
	if user is None:
		raise HTTPException(status_code=404, detail="User not found")
	workout = db.query(WorkoutPlan).filter_by(user_id=user_id).order_by(WorkoutPlan.id.desc()).first()
	if workout is None:
		raise HTTPException(status_code=404, detail="No plan found for this user")
	return {"original_plan": get_original_plan(db, user_id), "updated_plan": workout.updated_plan}


@router.put("/api/users/{user_id}/plan")
def revise_plan(user_id: int, payload: PlanUpdate, db: Session = Depends(get_db)):
	workout = update_plan(db, user_id, payload.updated_text)
	return {"user_id": user_id, "original_plan": workout.original_plan, "updated_plan": workout.updated_plan}


def local_plan(goal: str, intensity: str) -> str:
	focus = {"strength": "full-body strength", "weight-loss": "cardio and bodyweight", "fitness": "balanced fitness"}[goal]
	effort = {"beginner": "easy", "moderate": "steady", "advanced": "challenging"}[intensity]
	return "\n".join([
		"Your 7-day starter plan",
		f"Training level: {intensity.title()} | Focus: {focus}",
		"",
		f"Day 1: {effort.title()} {focus} session (25-35 min)",
		"Day 2: Brisk walk or cycling (25 min)",
		"Day 3: Mobility and light stretching (20 min)",
		"Day 4: Repeat Day 1, keeping good form",
		"Day 5: Rest or gentle walk",
		"Day 6: Low-impact cardio (25-35 min)",
		"Day 7: Rest and review how you feel",
		"",
		"Start gently, stop if you feel pain or unwell, and consult a health professional before starting a new exercise program.",
	])


def request_gemini_workout(goal: str, intensity: str, age: int | None = None, weight: float | None = None) -> str | None:
	if GOOGLE_API_KEY:
		try:
			from google import genai

			client = genai.Client(api_key=GOOGLE_API_KEY)
			prompt = "Create a conservative 7-day fitness plan with rest and recovery. This is general wellness information, not medical advice. "
			prompt += f"Format one day per line. Goal: {goal}; experience: {intensity}."
			if age is not None and weight is not None:
				prompt += f" Age: {age}; weight in kg: {weight}."
			response = client.models.generate_content(model=WORKOUT_MODEL, contents=prompt)
			if response.text:
				return response.text.strip()
		except Exception:
			pass
	return None


def generate_workout_gemini(user_data: dict) -> str:
	goal = user_data["goal"]
	intensity = user_data["intensity"]
	return request_gemini_workout(
		goal,
		intensity,
		user_data.get("age"),
		user_data.get("weight"),
	) or local_plan(goal, intensity)


def generate_plan(payload: UserInput) -> tuple[str, str]:
	plan = request_gemini_workout(payload.goal, payload.intensity, payload.age, payload.weight)
	if plan:
		return plan, "gemini"
	return local_plan(payload.goal, payload.intensity), "starter"


def generate_nutrition_tip_with_flash(goal: str) -> str:
	fallback_tips = {
		"strength": "Include a protein-rich food in each meal and pair it with carbohydrates to support training and recovery.",
		"weight-loss": "Build filling meals around vegetables, a protein source, and high-fiber foods; choose a gradual, sustainable approach.",
		"fitness": "Aim for balanced meals with vegetables or fruit, protein, and whole grains, and drink water regularly.",
	}
	fallback = fallback_tips.get(
		goal.lower(),
		"Choose mostly minimally processed foods, include a source of protein and fiber, and stay hydrated.",
	)
	if not GOOGLE_API_KEY:
		return fallback

	try:
		from google import genai

		client = genai.Client(api_key=GOOGLE_API_KEY)
		response = client.models.generate_content(
			model=NUTRITION_MODEL,
			contents=(
				"Give one concise, practical, evidence-informed nutrition tip for this fitness goal: "
				f"{goal}. Avoid calorie prescriptions, extreme diets, and medical claims."
			),
		)
		if response.text:
			return response.text.strip()
	except Exception:
		pass
	return fallback


def update_workout_plan(original: str, feedback: str) -> str:
	if GOOGLE_API_KEY:
		try:
			from google import genai

			client = genai.Client(api_key=GOOGLE_API_KEY)
			response = client.models.generate_content(
				model=WORKOUT_MODEL,
				contents=(
					"Revise the user's existing 7-day workout plan to address their feedback. "
					"Keep the result practical, include rest and recovery, and avoid medical claims. "
					f"\n\nExisting plan:\n{original}\n\nUser feedback:\n{feedback}"
				),
			)
			if response.text:
				return response.text.strip()
		except Exception:
			pass
	return f"{original.rstrip()}\n\nRequested adjustment:\n{feedback.strip()}"


@router.get("/nutrition-tip")
def get_flash_tip(goal: str = Query(min_length=2, max_length=80)):
	tip = generate_nutrition_tip_with_flash(goal.strip())
	return {"goal": goal, "nutrition_tip": tip}


@router.post("/update-plan/{user_id}", response_model=dict)
def update_user_plan(user_id: int, data: FeedbackRequest, db: Session = Depends(get_db)):
	original = get_original_plan(db, user_id)
	if not original:
		return {"error": "Original plan not found for this user."}

	updated = update_workout_plan(original, data.feedback)
	update_plan(db, user_id, updated)
	return {"updated_plan": updated}


@router.post("/api/plans")
def create_plan(payload: UserInput, db: Session = Depends(get_db)):
	user = save_user(db, payload.user_id, payload.name, payload.age, payload.weight, payload.goal, payload.intensity)
	plan, source = generate_plan(payload)
	saved_plan = save_plan(db, user.id, plan)
	return {"plan": plan, "source": source, "user_id": user.id, "plan_id": saved_plan.id}


@router.post("/generate-plan")
def generate_and_save_plan(user_data: GeneratePlanInput, db: Session = Depends(get_db)):
	user = save_user(
		db=db,
		user_id=user_data.user_id,
		name=user_data.name,
		age=user_data.age,
		weight=user_data.weight,
		goal=user_data.goal,
		intensity=user_data.intensity,
	)
	plan = generate_workout_gemini({
		"goal": user_data.goal,
		"intensity": user_data.intensity,
		"age": user_data.age,
		"weight": user_data.weight,
	})
	save_plan(db, user.id, plan)
	return {
		"message": "Workout plan generated and saved successfully!",
		"workout_plan": plan,
	}

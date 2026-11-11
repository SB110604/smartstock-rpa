from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.core.deps import DB, require
from app.core.errors import Conflict, NotFound
from app.models.catalog import Product
from app.models.core import Category, Location, User
from app.schemas.master import CategoryIn, CategoryOut, LocationIn, LocationOut
from app.services import audit

router = APIRouter(tags=["master data"])
Reader = Annotated[User, Depends(require("masters.read"))]
Writer = Annotated[User, Depends(require("masters.write"))]


@router.get("/locations", response_model=list[LocationOut])
def list_locations(user: Reader, db: DB) -> list[Location]:
    return list(db.scalars(select(Location).order_by(Location.id)))


@router.post("/locations", response_model=LocationOut, status_code=201)
def create_location(body: LocationIn, user: Writer, db: DB) -> Location:
    if db.scalar(select(Location.id).where(func.lower(Location.name) == body.name.lower())):
        raise Conflict("A location with this name already exists")
    loc = Location(**body.model_dump())
    db.add(loc)
    audit.created(db, user, loc)
    db.commit()
    return loc


@router.put("/locations/{location_id}", response_model=LocationOut)
def update_location(location_id: int, body: LocationIn, user: Writer, db: DB) -> Location:
    loc = db.get(Location, location_id)
    if not loc:
        raise NotFound("Location not found")
    audit.apply_update(db, user, loc, body.model_dump())
    db.commit()
    return loc


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(user: Reader, db: DB) -> list[Category]:
    return list(db.scalars(select(Category).order_by(Category.name)))


@router.post("/categories", response_model=CategoryOut, status_code=201)
def create_category(body: CategoryIn, user: Writer, db: DB) -> Category:
    if db.scalar(select(Category.id).where(func.lower(Category.name) == body.name.lower())):
        raise Conflict("A category with this name already exists")
    cat = Category(name=body.name.strip())
    db.add(cat)
    audit.created(db, user, cat)
    db.commit()
    return cat


@router.put("/categories/{category_id}", response_model=CategoryOut)
def update_category(category_id: int, body: CategoryIn, user: Writer, db: DB) -> Category:
    cat = db.get(Category, category_id)
    if not cat:
        raise NotFound("Category not found")
    audit.apply_update(db, user, cat, {"name": body.name.strip()})
    db.commit()
    return cat


@router.delete("/categories/{category_id}")
def delete_category(category_id: int, user: Writer, db: DB) -> dict[str, str]:
    cat = db.get(Category, category_id)
    if not cat:
        raise NotFound("Category not found")
    if db.scalar(select(func.count()).select_from(Product).where(Product.category_id == category_id)):
        raise Conflict("Category still has products; move them first")
    audit.deleted(db, user, cat)
    db.delete(cat)
    db.commit()
    return {"detail": "Category deleted"}

from src.constants.enums import Role
from fastapi import APIRouter,Depends,HTTPException
from src.config.database import session
from src.middlewares.auth import require
from src.schemas.run import RunInput
from src.controllers.run_controller import listing,create,detail
router=APIRouter(prefix='/runs')
@router.get('')
def index(db=Depends(session),u=Depends(require(Role.ADMIN,Role.ANALYST,Role.VIEWER))):return listing(db)
@router.get('/{id}')
def get(id:int,db=Depends(session),u=Depends(require(Role.ADMIN,Role.ANALYST,Role.VIEWER))):return detail(db,id)
@router.post('',status_code=202)
def add(data:RunInput,db=Depends(session),u=Depends(require(Role.ADMIN,Role.ANALYST))):return create(db,data,u)

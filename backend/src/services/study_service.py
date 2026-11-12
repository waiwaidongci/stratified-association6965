from sqlalchemy import select
from fastapi import HTTPException
from src.models import AssociationStudy
from src.utils.serializers import serialize
from src.utils.audit import record
from .worksheet_service import lock_study,bump_revision

def listing(db):return [serialize(x) for x in db.scalars(select(AssociationStudy).order_by(AssociationStudy.id))]

def create(db,data,user):
 if db.scalar(select(AssociationStudy).where(AssociationStudy.code==data.code)):raise HTTPException(409,'研究编号重复')
 row=AssociationStudy(**data.model_dump(),revision=0);db.add(row);db.flush();record(db,user,'study.created',row.id);db.commit();return serialize(row)

def patch(db,id,data,user):
 study=lock_study(db,id)
 changed=data.description!=study.description
 study.description=data.description
 if changed:
  db.flush()  # persist the annotation before expiry in bump_revision
  bump_revision(db,study)
 record(db,user,'study.annotated',id);db.commit();return serialize(study)

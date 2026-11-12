from sqlalchemy import select
from fastapi import HTTPException
from src.models import AssociationStudy,ExposureStratum
from src.utils.serializers import serialize
from src.utils.audit import record
from .worksheet_service import lock_study,bump_revision

def listing(db,study_id):return [serialize(x) for x in db.scalars(select(ExposureStratum).where(ExposureStratum.study_id==study_id).order_by(ExposureStratum.code))]

def create(db,data,user):
 study=lock_study(db,data.study_id)
 # Re-check under the lock so two concurrent creates cannot both pass the cap.
 if db.scalar(select(ExposureStratum).where(ExposureStratum.study_id==data.study_id,ExposureStratum.code==data.code)):raise HTTPException(409,'层编号重复')
 if len(listing(db,data.study_id))>=8:raise HTTPException(422,'每研究最多8层')
 row=ExposureStratum(**data.model_dump());db.add(row);db.flush();bump_revision(db,study);record(db,user,'stratum.created',row.id);db.commit();return serialize(row)

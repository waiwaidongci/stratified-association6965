from sqlalchemy import select
from fastapi import HTTPException
from src.models import ExposureStratum,TableCount
from src.utils.serializers import serialize
from src.utils.audit import record
from .cmh_algorithm import validate_tables
from .worksheet_service import lock_study,bump_revision

def listing(db,study_id):
 rows=db.execute(select(TableCount,ExposureStratum).join(ExposureStratum,ExposureStratum.id==TableCount.stratum_id).where(ExposureStratum.study_id==study_id).order_by(ExposureStratum.code)).all()
 raw=[{**serialize(t),'code':s.code,'name':s.name,'description':s.description} for t,s in rows]
 return validate_tables(raw) if raw else []

def save(db,id,data,user):
 stratum=db.get(ExposureStratum,id)
 if not stratum:raise HTTPException(404,'分层不存在')
 study=lock_study(db,stratum.study_id)
 # lock_study refreshes the parent row; re-read the stratum/count under the same lock.
 row=db.scalars(select(TableCount).where(TableCount.stratum_id==id).with_for_update()).first()
 payload=data.model_dump()
 changed=row is None or any(getattr(row,k)!=v for k,v in payload.items())
 if row is None:row=TableCount(stratum_id=id,**payload);db.add(row)
 else:
  for k,v in payload.items():setattr(row,k,v)
 db.flush()
 if changed:bump_revision(db,study)
 record(db,user,'count.saved',row.id)
 db.commit();return serialize(row)

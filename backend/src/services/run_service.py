from sqlalchemy import select
from fastapi import HTTPException
from src.models import AssociationRun
from src.config.queue import queue
from src.utils.audit import record
from src.utils.serializers import serialize
from .analysis_algorithm import analyze
from .worksheet_service import freeze,enrich
QUEUE='cenan:runs'

def listing(db):
 rows=[]
 cache={}
 for x in db.scalars(select(AssociationRun).order_by(AssociationRun.id.desc())):
  r=enrich(db,x,cache=cache);r.pop('result');r.pop('input_snapshot');rows.append(r)
 return rows

def detail(db,id):
 row=db.get(AssociationRun,id)
 if not row:raise HTTPException(404,'研究不存在')
 return enrich(db,row)

def create(db,data,user):
 if db.scalar(select(AssociationRun).where(AssociationRun.name==data.name)):raise HTTPException(409,'研究名称重复')
 # Freeze under the worksheet lock and verify the revision stayed stable while
 # the children were read. A concurrent revision either commits before this
 # freeze (the run records the newer revision) or after this run is stored (the
 # run becomes stale); no run can observe a half-applied revision.
 revision,snap=freeze(db,data.study_id,lock=True)
 row=AssociationRun(**data.model_dump(),created_by=user.id,input_snapshot=snap,worksheet_revision=revision)
 db.add(row);db.flush();record(db,user,'run.queued',row.id);db.commit();queue.rpush(QUEUE,str(row.id))
 return enrich(db,row)

def compute(db,id):
 row=db.get(AssociationRun,id)
 if not row or row.status not in ['queued','running']:return
 row.status='running';db.commit();row.result=analyze(row.input_snapshot,row.alpha);row.status='completed';row.error='';record(db,None,'worker.completed',row.id);db.commit();return serialize(row)

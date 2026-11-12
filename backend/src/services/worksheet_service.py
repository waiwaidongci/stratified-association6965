"""Worksheet versioning.

A study revision is bumped whenever the frozen input (counts, strata or study
metadata) changes. Freezes record the revision they read and verify that the
revision did not move while they were reading the children; if it did, the
freeze retries instead of storing a mixed-version snapshot. Writers bump with an
atomic SQL increment and additionally take `SELECT ... FOR UPDATE` on the parent
study row, so revisions are serialised where the database supports row locks.
The retry check does not rely on repeatable-read isolation and also works on
SQLite for local needs.

Unversioned (legacy) runs are judged by comparing their frozen content with the
current worksheet, which keeps pre-existing studies, runs and notes working.
"""
import hashlib,json
from sqlalchemy import select,update
from fastapi import HTTPException
from src.models import AssociationStudy,ExposureStratum,TableCount
from src.utils.serializers import serialize

STUDY_KEYS=('code','name','period','description')
TABLE_KEYS=('code','name','description','a','b','c','d','source')
FREEZE_RETRIES=5

def lock_study(db,id):
 """Acquire the worksheet mutation lock. Locking reads see the latest committed
 row even under MySQL REPEATABLE READ."""
 study=db.scalars(select(AssociationStudy).where(AssociationStudy.id==id).with_for_update()).one_or_none()
 if not study:raise HTTPException(404,'研究不存在')
 return study

def normalize(payload):
 if not isinstance(payload,dict) or not isinstance(payload.get('tables'),list):return None
 study=payload.get('study') if isinstance(payload.get('study'),dict) else {}
 tables=sorted((t for t in payload['tables'] if isinstance(t,dict)),key=lambda t:str(t.get('code','')))
 return {'study':{k:study.get(k) for k in STUDY_KEYS},
         'tables':[{k:t.get(k) for k in TABLE_KEYS} for t in tables]}

def digest(payload):
 """Canonical content digest of a frozen worksheet."""
 canonical=normalize(payload)
 return hashlib.sha256(json.dumps(canonical,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def worksheet_state(db,study_id,lock=False):
 """Full worksheet view (complete or not) used for freezing and legacy
 content comparison."""
 study=db.get(AssociationStudy,study_id)
 if not study:raise HTTPException(404,'研究不存在')
 strata_stmt=select(ExposureStratum).where(ExposureStratum.study_id==study_id).order_by(ExposureStratum.code)
 if lock:strata_stmt=strata_stmt.with_for_update()
 strata=db.scalars(strata_stmt).all()
 tables=[]
 for s in strata:
  stmt=select(TableCount).where(TableCount.stratum_id==s.id)
  if lock:stmt=stmt.with_for_update()
  t=db.scalars(stmt).first()
  base={'code':s.code,'name':s.name,'description':s.description}
  if t is None:tables.append({**base,'a':None,'b':None,'c':None,'d':None,'source':None})
  else:tables.append({**serialize(t),**base})
 study_payload={k:v for k,v in serialize(study).items() if k!='revision'}
 return study,{'study':study_payload,'tables':tables}

def build_snapshot(db,study_id,lock=False):
 study,payload=worksheet_state(db,study_id,lock)
 if not 2<=len(payload['tables'])<=8:raise HTTPException(422,'需要2..8个完整分层')
 if any(t['a'] is None for t in payload['tables']):raise HTTPException(422,'每层必须有2×2计数')
 from .cmh_algorithm import validate_tables
 validate_tables(payload['tables'])
 return study,payload

def snapshot(db,study_id,lock=False):
 return build_snapshot(db,study_id,lock)[1]

def bump_revision(db,study):
 """Advance the revision counter atomically in the same transaction as the
 worksheet change. The UPDATE (not an ORM read-modify-write) makes concurrent
 revisions receive distinct numbers even where row locks are unavailable, so
 every revision matches exactly the content committed with it."""
 db.execute(update(AssociationStudy).where(AssociationStudy.id==study.id).values(revision=AssociationStudy.revision+1))
 db.expire(study)

def worksheet_matches(db,run,cache=None,lock=False):
 """Legacy runs predate revision tracking; compare frozen content instead."""
 if not run.input_snapshot:return False
 study=db.get(AssociationStudy,run.study_id)
 if not study:return False
 key=run.study_id
 if cache is not None and key in cache:current=cache[key]
 else:
  try:current=snapshot(db,run.study_id,lock)
  except HTTPException:return False
  if cache is not None:cache[key]=current
 return normalize(current)==normalize(run.input_snapshot)

def version_info(db,run,current=None,cache=None,lock=False):
 """(frozen_revision,current_revision,stale) for a frozen research run. Callers
 that already hold the study lock pass `current` from that locking read, which
 sees commits a repeatable-read snapshot would hide."""
 if current is None:current=current_revision(db,run.study_id,lock)
 stored=run.worksheet_revision
 if stored is None:
  matches=worksheet_matches(db,run,cache,lock)
  return (current if matches else None),current,(not matches or current is None)
 return stored,current,(current is None or stored!=current)

def enrich(db,run,cache=None,current=None):
 data=serialize(run)
 frozen,rev,stale=version_info(db,run,current,cache)
 data['worksheet_revision']=frozen
 data['current_revision']=rev
 data['stale']=stale
 return data

def current_revision(db,study_id,lock=False):
 """Read the study revision straight from the database, bypassing the identity
 map so a cached ORM instance cannot hide it. With `lock`, the read is locking
 and therefore sees the latest committed value even inside a repeatable-read
 snapshot."""
 stmt=select(AssociationStudy.revision).where(AssociationStudy.id==study_id).execution_options(populate_existing=True)
 if lock:stmt=stmt.with_for_update()
 return db.scalar(stmt)

def freeze(db,study_id,lock=False):
 """Freeze a coherent worksheet: read it, verify the revision did not move
 while the children were read, and retry instead of persisting a mixture.
 With `lock`, the caller wants the study row locked for the freeze; the locking
 reads then also see the latest committed worksheet."""
 error=HTTPException(409,'底稿在冻结过程中被并发修订，请重试')
 for attempt in range(FREEZE_RETRIES):
  try:
   if lock and attempt==0:lock_study(db,study_id)
   db.expire_all()
   opened=current_revision(db,study_id,lock)
   if opened is None:raise HTTPException(404,'研究不存在')
   opened=opened or 0
   study,payload=build_snapshot(db,study_id,lock)
   closed=current_revision(db,study_id,lock)
   if (study.revision or 0)==opened==(closed or 0):return opened,payload
  except HTTPException as exc:
   if exc.status_code!=422:raise
   error=exc
  db.expire_all()
 raise error

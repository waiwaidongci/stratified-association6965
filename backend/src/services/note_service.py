import csv,io
from sqlalchemy import select
from fastapi import HTTPException
from src.models import VerificationNote,AssociationRun
from src.constants.enums import NoteStatus
from src.utils.audit import record
from src.utils.serializers import serialize
from .worksheet_service import lock_study,version_info,current_revision

def listing(db):
 rows=[]
 cache={}
 for x in db.scalars(select(VerificationNote).order_by(VerificationNote.id.desc())):
  rows.append(enrich(db,x,cache=cache))
 return rows

def enrich(db,note,cache=None):
 data=serialize(note)
 run=db.get(AssociationRun,note.run_id)
 if run is None:
  data.update({'worksheet_revision':None,'current_revision':None,'stale':True,'run_status':None})
  return data
 current=current_revision(db,run.study_id)
 frozen,_,stale=version_info(db,run,current,cache=cache)
 data.update({'worksheet_revision':frozen,'current_revision':current,'stale':stale,'run_status':run.status})
 return data

def create(db,data,user):
 run=db.get(AssociationRun,data.run_id)
 if not run:raise HTTPException(404,'研究不存在')
 if run.status!='completed':raise HTTPException(409,'仅已完成研究可形成复验说明')
 # Lock the worksheet row so a concurrent count revision cannot slip in between
 # the stale check and the note insert. Either the revision commits first (the
 # run is already stale and the note is refused) or the note commits first and
 # the later revision marks that note stale as well.
 lock_study(db,run.study_id)
 # The locking read sees the latest committed revision, so a concurrent revision
 # cannot hide behind a repeatable-read snapshot between check and insert.
 frozen,current,stale=version_info(db,run,current_revision(db,run.study_id,lock=True),cache={},lock=True)
 if stale:raise HTTPException(409,'该研究对应的底稿版本已过期，请基于当前版本重新冻结计算后再形成说明')
 if db.scalar(select(VerificationNote).where(VerificationNote.title==data.title)):raise HTTPException(409,'说明名称重复')
 note=VerificationNote(**data.model_dump(),created_by=user.id,worksheet_revision=frozen)
 db.add(note);db.flush();record(db,user,'note.created',note.id);db.commit();return enrich(db,note)

def review(db,id,data,user):
 note=db.get(VerificationNote,id)
 if not note:raise HTTPException(404,'复验说明不存在')
 if note.status!=NoteStatus.DRAFT:raise HTTPException(409,'复验说明已审阅')
 run=db.get(AssociationRun,note.run_id)
 if run is None:raise HTTPException(409,'关联研究不存在，无法审阅')
 lock_study(db,run.study_id)
 frozen,current,stale=version_info(db,run,current_revision(db,run.study_id,lock=True),cache={},lock=True)
 # Approval must reflect the current worksheet version. Rejection stays possible
 # so a stale draft can still be closed by the reviewer.
 if stale and data.decision=='approved':raise HTTPException(409,'关联研究已过期：底稿版本已变化，不能批准该说明；请重新冻结计算')
 if note.worksheet_revision is None:note.worksheet_revision=frozen
 elif frozen is not None and note.worksheet_revision!=frozen:raise HTTPException(409,'说明记录的底稿版本与研究冻结版本不一致')
 note.status=NoteStatus(data.decision);note.review_comment=data.comment;note.approved_by=user.email;record(db,user,'note.'+data.decision,id);db.commit();return enrich(db,note)

def export(db,id,user):
 note=db.get(VerificationNote,id)
 if not note:raise HTTPException(404,'复验说明不存在')
 if note.status!=NoteStatus.APPROVED:raise HTTPException(403,'仅已批准说明可导出')
 # Approved notes are exported from their frozen run result regardless of later
 # worksheet revisions; the CSV states the source revision explicitly.
 run=db.get(AssociationRun,note.run_id)
 if run is None or not run.result:raise HTTPException(409,'关联研究的冻结结果不存在，无法导出')
 r=run.result;frozen,current,stale=version_info(db,run,current_revision(db,run.study_id))
 out=io.StringIO();w=csv.writer(out)
 w.writerow(['note','method','fingerprint','alpha','worksheet_revision','current_worksheet_revision','worksheet_stale','adjusted_or_status','adjusted_or','cmh','asymptotic_p','asymptotic_p_log','exact_p','exact_p_log','interpretation','action','boundary'])
 w.writerow([note.title,r['method_version'],r['fingerprint'],r['alpha'],frozen,current,int(stale),r['adjusted_or']['status'],r['adjusted_or']['value'],r['cmh'],r['asymptotic_p_display'],r['asymptotic_p_log'],r['exact']['p_display'],r['exact']['p_log'],note.interpretation,note.action,r['interpretation']])
 w.writerow(['stratum','a_A_success','b_A_fail','c_B_success','d_B_fail','rate_A','rate_B','OR_status','OR','expected_a','variance_a'])
 for t in r['strata']:w.writerow([t['code'],t['a'],t['b'],t['c'],t['d'],t['rate_a'],t['rate_b'],t['odds_ratio']['status'],t['odds_ratio']['value'],t['expected_a'],t['variance_a']])
 w.writerow(['exact_support_s','probability','log_probability','included_mean_distance_tail'])
 for d in r['exact']['distribution']:w.writerow([d['s'],d['probability'],d['log_probability'],d['in_tail']])
 record(db,user,'note.exported',id);db.commit();return out.getvalue()

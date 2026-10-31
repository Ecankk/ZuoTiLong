import {MathText} from './MathText'

export type PracticeAssessment={
  correct:boolean|null;feedback:string;reference_reasoning?:string;
  first_error?:{stage:string;step:string;evidence:string}|null;
  observations?:{step:string;stage:string;status:string;evidence:string}[];
  possible_causes?:{id:string;label:string;evidence:string;alternative:string;correction:string}[];
  next_step?:string;needs_material?:string[];
}

const stages:Record<string,string>={entry:'切入',modeling:'建模',formula:'公式应用',calculation:'计算',finalization:'最终处理'}
const observations:Record<string,string>={valid:'有效步骤',error:'错误步骤',unclear:'尚不清楚',consequence:'后续影响'}

export function PracticeFeedback({assessment}:{assessment:PracticeAssessment}){
  const first=assessment.first_error
  return <section className="practice-feedback" aria-label="本次作答反馈">
    <h4>{assessment.correct===null?'暂未判定':assessment.correct?'本次布置步骤正确':'本次作答存在错误'}</h4>
    <p><MathText text={assessment.feedback}/></p>
    {!!assessment.needs_material?.length&&<div className="notice"><b>只需补充以下材料</b>{assessment.needs_material.map((s,i)=><p key={i}><MathText text={s}/></p>)}</div>}
    {first&&<section><h4>首个实质性错误{stages[first.stage]?` · ${stages[first.stage]}`:''}</h4><p><MathText text={first.step}/></p><p className="muted"><MathText text={first.evidence}/></p></section>}
    {!!assessment.possible_causes?.length&&<section><h4>可能原因 · 供复习参考</h4>{assessment.possible_causes.map(c=><div key={c.id}><p><b><MathText text={c.label}/></b></p>{c.evidence&&<p><MathText text={c.evidence}/></p>}{c.alternative&&<p className="muted"><MathText text={c.alternative}/></p>}{c.correction&&<p><MathText text={c.correction}/></p>}</div>)}</section>}
    {assessment.next_step&&<p><b>接下来：</b><MathText text={assessment.next_step}/></p>}
    {(assessment.reference_reasoning||!!assessment.observations?.length)&&<details><summary>核验解法与步骤依据</summary>{assessment.reference_reasoning&&<p><MathText text={assessment.reference_reasoning}/></p>}{assessment.observations?.map((o,i)=><p key={i}><b>{observations[o.status]||'步骤'}：</b><MathText text={o.step}/><br/><MathText text={o.evidence}/></p>)}</details>}
  </section>
}

/* Shared, dependency-free scheduling rules for the fictional workspace. */
(function(root){
  const statuses=['Scheduled','Completed','Cancelled','No-show'];
  const locations=['In community','In home','Office','Virtual'];
  function normalize(a){return {...a,duration:a.duration??60,status:a.status??'Scheduled',therapistId:a.therapistId??''}}
  function minutes(time){const [h,m]=time.split(':').map(Number);return h*60+m}
  function validate(raw){
    const a=normalize(raw);
    if(!a.title?.trim()||a.title.length>120)throw Error('Enter a session title of up to 120 characters.');
    if(!a.caseId)throw Error('Choose a case folder.');
    if(!/^\d{4}-\d{2}-\d{2}$/.test(a.date)||Number.isNaN(Date.parse(a.date+'T12:00:00Z'))||new Date(a.date+'T12:00:00Z').toISOString().slice(0,10)!==a.date)throw Error('Choose a valid date.');
    if(!/^([01]\d|2[0-3]):[0-5]\d$/.test(a.time))throw Error('Choose a valid time.');
    if(!Number.isInteger(a.duration)||a.duration<15||a.duration>240||minutes(a.time)+a.duration>1440)throw Error('Use 15–240 minutes and end the session by midnight.');
    if(!statuses.includes(a.status)||!locations.includes(a.location))throw Error('Choose a valid status and location.');
    return {...a,title:a.title.trim()};
  }
  function conflicts(candidate,appointments){
    const a=validate(candidate);if(a.status==='Cancelled')return [];
    return appointments.map(normalize).filter(b=>b.id!==a.id&&b.status!=='Cancelled'&&b.date===a.date&&(b.caseId===a.caseId||(a.therapistId&&b.therapistId===a.therapistId))&&minutes(a.time)<minutes(b.time)+b.duration&&minutes(b.time)<minutes(a.time)+a.duration);
  }
  function agenda(appointments,{from='',to='',status='',therapistId='',query='',cases=[]}={}){
    const q=query.trim().toLowerCase();
    return appointments.map(normalize).filter(a=>(!from||a.date>=from)&&(!to||a.date<=to)&&(!status||a.status===status)&&(!therapistId||(therapistId==='__unassigned__'?!a.therapistId:a.therapistId===therapistId))&&(!q||`${a.title} ${cases.find(c=>c.id===a.caseId)?.label||''} ${a.location}`.toLowerCase().includes(q))).sort((a,b)=>`${a.date} ${a.time} ${a.id}`.localeCompare(`${b.date} ${b.time} ${b.id}`));
  }
  function summary(appointments,day){const all=appointments.map(normalize);return {today:all.filter(a=>a.date===day&&a.status==='Scheduled').length,unassigned:all.filter(a=>a.date>=day&&a.status==='Scheduled'&&!a.therapistId).length,needsAttendance:all.filter(a=>a.date<day&&a.status==='Scheduled').length,completed:all.filter(a=>a.status==='Completed').length}}
  const api={statuses,locations,normalize,validate,conflicts,agenda,summary};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.EeroScheduling=api;
})(typeof globalThis==='object'?globalThis:this);

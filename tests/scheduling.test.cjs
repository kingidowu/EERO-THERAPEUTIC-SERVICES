const {test}=require('node:test');const assert=require('node:assert/strict');
const s=require('../dist/scheduling.js');
const base={id:'a',caseId:'c1',therapistId:'t1',title:'Sample session',date:'2026-10-14',time:'09:00',duration:60,location:'Office',status:'Scheduled'};
test('overlap catches case and therapist conflicts but allows back-to-back appointments',()=>{
 assert.equal(s.conflicts({...base,id:'b',time:'09:30'},[base]).length,1);
 assert.equal(s.conflicts({...base,id:'b',caseId:'c2',time:'09:30'},[base]).length,1);
 assert.equal(s.conflicts({...base,id:'b',time:'10:00'},[base]).length,0);
 assert.equal(s.conflicts({...base,id:'b',caseId:'c2',therapistId:'t2'},[base]).length,0);
});
test('editing excludes itself; cancellation frees time, reinstating checks conflicts',()=>{
 assert.equal(s.conflicts(base,[base]).length,0);
 assert.equal(s.conflicts({...base,id:'b'},[{...base,status:'Cancelled'}]).length,0);
 assert.equal(s.conflicts({...base,id:'b',status:'Cancelled'},[base]).length,0);
 assert.equal(s.conflicts({...base,id:'b',status:'Scheduled'},[base]).length,1);
});
test('legacy sessions default to scheduled, 60 minutes, and unassigned',()=>{
 const legacy={...base};delete legacy.duration;delete legacy.status;delete legacy.therapistId;
 assert.equal(s.normalize(legacy).duration,60);assert.equal(s.normalize(legacy).status,'Scheduled');
 assert.equal(s.conflicts({...base,id:'b',time:'09:30'},[legacy]).length,1);
});
test('invalid dates, midnight overflow, durations and statuses are rejected',()=>{
 for(const change of [{date:'2026-02-30'},{time:'25:00'},{time:'23:30',duration:60},{duration:0},{duration:60.5},{status:'Approved'},{title:'  '}])assert.throws(()=>s.validate({...base,...change}));
});
test('agenda combines date, therapist, status and case search and sorts chronologically',()=>{
 const rows=[{...base,id:'b',time:'11:00'},base,{...base,id:'c',date:'2026-10-15',status:'Cancelled'}];
 assert.deepEqual(s.agenda(rows,{from:'2026-10-14',to:'2026-10-14',therapistId:'t1',status:'Scheduled',query:'river',cases:[{id:'c1',label:'River sample'}]}).map(a=>a.id),['a','b']);
});
test('operational summary excludes cancelled sessions and flags overdue attendance',()=>{
 assert.deepEqual(s.summary([base,{...base,date:'2026-10-13'},{...base,therapistId:''},{...base,status:'Cancelled'},{...base,status:'Completed'}],'2026-10-14'),{today:2,unassigned:1,needsAttendance:1,completed:1});
});
test('staff can isolate unassigned sessions from all-therapist view',()=>{
 assert.equal(s.agenda([base,{...base,id:'b',therapistId:''}],{therapistId:'__unassigned__'}).length,1);
 assert.equal(s.agenda([base,{...base,id:'b',therapistId:''}],{}).length,2);
});

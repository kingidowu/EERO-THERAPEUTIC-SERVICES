const test=require('node:test'),assert=require('node:assert/strict'),{calendar}=require('../dist/calendar-export.js');
test('calendar export uses stable identifiers, UTC, escaped text and UTF8 line folding',()=>{
 const row={id:'session-1',title:'é'.repeat(90)+'; comma,\nEND:VEVENT',location:'Office',starts_at:'2099-12-01T09:00:00-05:00',ends_at:'2099-12-01T10:00:00-05:00',status:'Cancelled'};
 const output=calendar([row],'2026-10-17T00:00:00Z');
 assert.match(output,/UID:session-1@eero-schedule.local/);assert.match(output,/DTSTART:20991201T140000Z/);assert.match(output,/STATUS:CANCELLED/);
 for(const line of output.split('\r\n'))assert.ok(Buffer.byteLength(line)<=75);
 const unfolded=output.replace(/\r\n /g,'');assert.ok(unfolded.includes('\\; comma\\,\\nEND:VEVENT'));assert.equal(output.match(/\r\nEND:VEVENT/g).length,1);
 assert.throws(()=>calendar([{...row,id:'bad\r\nINJECT'}]));assert.throws(()=>calendar([{...row,starts_at:'invalid'}]));
});

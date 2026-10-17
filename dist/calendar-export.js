/* RFC 5545 export. UTC times; every event retains a stable UID. */
(function(root){
 function escape(value){return String(value??'').replace(/\\/g,'\\\\').replace(/\r\n|\r|\n/g,'\\n').replace(/;/g,'\\;').replace(/,/g,'\\,')}
 function stamp(value){const d=new Date(value);if(Number.isNaN(d.getTime()))throw Error('A session has an invalid date');return d.toISOString().replace(/[-:]/g,'').replace(/\.\d{3}Z$/,'Z')}
 function fold(line){const encoder=new TextEncoder();let out='',part='';for(const char of line){if(encoder.encode(part+char).length>75){out+=part+'\r\n';part=' '}part+=char}return out+part}
 function calendar(items,now=new Date().toISOString()){
  const lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Eero//Staff Schedule//EN','CALSCALE:GREGORIAN'];
  for(const a of items){if(!/^[A-Za-z0-9_-]+$/.test(a.id))throw Error('Invalid session identifier');lines.push('BEGIN:VEVENT',`UID:${a.id}@eero-schedule.local`,`DTSTAMP:${stamp(now)}`,`DTSTART:${stamp(a.starts_at)}`,`DTEND:${stamp(a.ends_at)}`,`SUMMARY:${escape(a.title)}`,`LOCATION:${escape(a.location)}`,`STATUS:${a.status==='Cancelled'?'CANCELLED':'CONFIRMED'}`,'END:VEVENT')}
  lines.push('END:VCALENDAR');return lines.map(fold).join('\r\n')+'\r\n';
 }
 const api={calendar,escape,fold};if(typeof module==='object'&&module.exports)module.exports=api;else root.EeroCalendarExport=api;
})(globalThis);

import fs from 'node:fs';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
const w = new Window({url:'https://ha.test/'});
w.eval(fs.readFileSync(new URL('../../www/mc3000-batteries-card.js',import.meta.url),'utf8'));
const el=w.document.createElement('mc3000-batteries-card');w.document.body.append(el);el.setConfig({});
const calls=[];
const cell={id:'cell1',name:'Samsung <30Q> #1',type_name:'30Q',chemistry:'liion',capacity_mah:3000,charge_current:1.5,discharge_current:1,charge_voltage:4200,discharge_voltage:3000,storage_voltage:3800,color:'#58a6ff',notes:'',favorite:true};
const attrs={cells:[cell],assignments:{'1':'cell1'},jobs:{},reports:[],revision:11,cell_revision:3};
const hass={language:'uk',states:{'sensor.skyrc_mc3000_batteries':{state:'1',attributes:attrs},'switch.skyrc_mc3000_companion_app_mode':{state:'off'}},callService:async(domain,service,data)=>{calls.push({domain,service,data});},callWS:async data=>{calls.push(data);return {response:{content:'{}',filename:'test.json',mime_type:'application/json'}}}};
for(let n=1;n<=4;n++)hass.states[`sensor.skyrc_mc3000_slot_${n}_status`]={state:'standby'};
el.hass=hass;
const r=el.shadowRoot;
assert.equal(r.querySelectorAll('.slot').length,4);
assert.equal(r.querySelector('.cell-item strong').textContent,'★ Samsung <30Q> #1');
assert.equal(r.querySelectorAll('script').length,0);
assert.ok(!r.querySelector('[data-action="start"][data-slot="1"]').disabled);
assert.ok(r.querySelector('[data-action="start"][data-slot="2"]').disabled);
await el._edit('cell1');
r.getElementById('cell-name').value='Changed name';
r.getElementById('cell-name').dispatchEvent(new w.Event('input',{bubbles:true}));
el.hass={...hass,states:{...hass.states,'sensor.skyrc_mc3000_batteries':{state:'1',attributes:{...attrs,revision:99}}}};
assert.equal(r.getElementById('cell-name').value,'Changed name');
assert.equal(el._revision,3);
assert.equal(el._conflict,false);
// happy-dom miscalculates decimal step; actual Chrome checks separately.
r.getElementById("cell-form").reportValidity=()=>true; await el._save();
assert.equal(calls.at(-1).service,'save_cell');
assert.equal(calls.at(-1).data.revision,3);
assert.equal(calls.at(-1).data.cell_id,'cell1');
assert.equal(calls.at(-1).data.name,'Changed name');
assert.equal(calls.at(-1).data.id,undefined);
assert.equal(calls.filter(c=>c.service==='start_quality_test').length,0);
// Assignment is selected then explicitly committed.
r.getElementById('assign-2').value='cell1';r.getElementById('assign-2').dispatchEvent(new w.Event('change',{bubbles:true}));
assert.equal(calls.filter(c=>c.service==='assign_cell').length,0);
await el._click({target:r.querySelector('[data-action="assign"][data-slot="2"]')});
assert.equal(JSON.stringify(calls.at(-1).data),JSON.stringify({slot:2,cell_id:'cell1'}));
// System changes cannot silently overwrite a dirty form.
el._dirty=true;el.hass={...hass,states:{...hass.states,'sensor.skyrc_mc3000_batteries':{state:'1',attributes:{...attrs,cells:[{...cell,name:'External rename'}],cell_revision:4}}}};
assert.equal(el._conflict,true);
assert.equal(r.getElementById('cell-name').value,'Changed name');
// Unsafe text remains text in reports.
el.hass={...hass,states:{...hass.states,'sensor.skyrc_mc3000_batteries':{state:'1',attributes:{...attrs,reports:[{id:'r1',slot:1,cell_name:'<img src=x onerror=alert(1)>',state:'completed',metrics:{capacity_mah:2840,soh_percent:94.7,ir_mohm:22}}]}}}};
assert.equal(r.querySelectorAll('img').length,0);
assert.match(r.getElementById('reports').textContent,/2840|2.?840/);
// The phone handoff blocks test start.
hass.states['switch.skyrc_mc3000_companion_app_mode'].state='on';el.hass=hass;
assert.ok(r.querySelector('[data-action="start"][data-slot="1"]').disabled);
await w.happyDOM.close();
console.log('Battery card smoke tests passed: 24 assertions');




import fs from 'node:fs';
import assert from 'node:assert/strict';
import { Window } from 'happy-dom';
const w=new Window({url:'https://ha.test/'});
w.eval(fs.readFileSync(new URL('../../www/mc3000-batteries-card.js',import.meta.url),'utf8'));
const card=w.document.createElement('mc3000-batteries-card');w.document.body.append(card);card.setConfig({});
const cell={id:'c1',name:'UI test fixture only',type_name:'',chemistry:'liion',capacity_mah:3000,charge_current:1.5,discharge_current:1,charge_voltage:4200,discharge_voltage:3000,storage_voltage:3800,color:'#58a6ff',favorite:false,notes:''};
const calls=[];
const states={'sensor.skyrc_mc3000_batteries':{state:'1',attributes:{cells:[cell],assignments:{'1':'c1'},jobs:{},reports:[],cell_revision:1}},'switch.skyrc_mc3000_companion_app_mode':{state:'off'}};
for(let slot=1;slot<=4;slot++)states[`sensor.skyrc_mc3000_slot_${slot}_status`]={state:'standby'};
const hass={language:'uk',states,callService:async(domain,service,data)=>calls.push({domain,service,data})};
const r=card.shadowRoot;
const job=(state,extra={})=>({id:'j1',slot:1,cell_id:'c1',cell_name:cell.name,state,phase:'discharge',phase_label:'Вимірювання ємності',metrics:{},...extra});
const setJob=(value)=>{states['sensor.skyrc_mc3000_batteries'].attributes.jobs=value?{'1':value}:{};card.hass={...hass};};
setJob(null);await card._edit('c1');
assert.equal(r.getElementById('save-cell').disabled,false);
// A stop transition must update controls even while the slot dropdown has focus.
r.getElementById('assign-1').focus();setJob(job('stop_unconfirmed'));
// happy-dom retains a detached activeElement; move focus outside after removal.
const focusAnchor=w.document.createElement('button');w.document.body.append(focusAnchor);focusAnchor.focus();
assert.equal(card._active(1),true);
assert.equal(r.getElementById('assign-1').disabled,true);
assert.equal(r.querySelector('[data-action="assign"][data-slot="1"]').disabled,true);
assert.equal(r.querySelector('[data-action="start"][data-slot="1"]'),null);
assert.equal(r.querySelector('[data-action="resume"][data-slot="1"]'),null);
assert.equal(r.querySelector('[data-action="pause"][data-slot="1"]'),null);
assert.equal(r.querySelector('[data-action="cancel"][data-slot="1"]').textContent,'Повторити зупинку');
assert.match(r.getElementById('slots').textContent,/Зупинку не підтверджено/);
assert.equal(r.getElementById('save-cell').disabled,true);
assert.equal(r.getElementById('delete-cell').disabled,true);
assert.equal(r.getElementById('cell-name').disabled,true);
assert.equal(r.getElementById('cell-locked').hidden,false);
const before=calls.length;
card._startDialog(1);await card._resume(1);await card._save();await card._delete();
assert.equal(calls.length,before);
assert.equal(r.getElementById('dialog').open,false);
let confirms=0;card._confirm=async()=>{confirms++;return true;};
await card._cancel(1);
assert.equal(confirms,0); // retry is a direct stop, not another physical-start confirmation
assert.equal(calls.at(-1).service,'cancel_quality_test');
assert.equal(JSON.stringify(calls.at(-1).data),'{"slots":[1]}');
assert.equal(r.getElementById('assign-1').disabled,true); // request completion alone does not unlock
assert.equal(r.getElementById('save-cell').disabled,true);
assert.match(r.getElementById('notice').textContent,/Очікуємо підтвердження/);
// A restored job retains the lock through its explicit restart flag.
setJob(job('stop_unconfirmed',{restart_stop_pending:true}));
assert.match(r.getElementById('slots').textContent,/Очікується зупинка після перезапуску/);
assert.equal(r.querySelector('[data-action="resume"][data-slot="1"]'),null);
assert.equal(r.getElementById('assign-1').disabled,true);
setJob(job('paused',{restart_stop_pending:true}));
assert.equal(r.querySelector('[data-action="resume"][data-slot="1"]'),null);
assert.equal(r.querySelector('[data-action="cancel"][data-slot="1"]').textContent,'Повторити зупинку');
// A confirmed pause can resume, but the same physical cell stays locked while the test exists.
setJob(job('paused'));
assert.ok(r.querySelector('[data-action="resume"][data-slot="1"]'));
assert.equal(r.getElementById('save-cell').disabled,true);
let confirmText='';card._confirm=async(title,text)=>{confirmText=text;return true;};
await card._resume(1);
assert.match(confirmText,/Перерваний розряд буде повторено після повного заряду/);
assert.equal(calls.at(-1).service,'resume_quality_test');
// If a stop becomes unconfirmed while the resume review is open, no resume command is sent.
const beforeRace=calls.length;
card._confirm=async()=>{setJob(job('stop_unconfirmed'));return true;};
setJob(job('paused'));await card._resume(1);
assert.equal(calls.length,beforeRace);
// Ordinary running state retains Pause and Cancel, never Start.
setJob(job('running'));
assert.ok(r.querySelector('[data-action="pause"][data-slot="1"]'));
assert.equal(r.querySelector('[data-action="resume"][data-slot="1"]'),null);
assert.equal(r.querySelector('[data-action="start"][data-slot="1"]'),null);
// Only the terminal confirmed state releases the catalog and assignment.
setJob(job('cancelled'));
assert.equal(card._active(1),false);
assert.equal(r.getElementById('assign-1').disabled,false);
assert.equal(r.getElementById('save-cell').disabled,false);
assert.equal(r.getElementById('delete-cell').disabled,false);
assert.equal(r.getElementById('cell-name').disabled,false);
assert.ok(r.querySelector('[data-action="start"][data-slot="1"]'));
assert.equal(r.querySelector('[data-action="resume"][data-slot="1"]'),null);
setJob(job('error'));assert.ok(r.querySelector('[data-action="start"][data-slot="1"]'));
assert.equal(r.querySelector('[data-action="resume"][data-slot="1"]'),null);
// IR review reflects the backend's0.5A pulse limit.
setJob(job('cancelled'));card._startDialog(1);
const dialog=r.getElementById('dialog');
for(const radio of dialog.querySelectorAll('[name="test_type"]')){radio.checked=radio.value==='ir';if(radio.checked)radio.setAttribute('checked','');else radio.removeAttribute('checked');}card._updateTestReview();
assert.match(dialog.querySelector('#test-review').textContent,/до 0,5 А/);
dialog.close('cancel');
// Empty catalog stays empty; the card does not infer records from occupied hardware slots.
states['sensor.skyrc_mc3000_batteries']={state:'0',attributes:{cells:[],assignments:{},jobs:{},reports:[],cell_revision:2}};
card.hass={...hass};
assert.equal(r.querySelectorAll('.cell-item').length,0);
assert.equal(r.getElementById('cell-count').textContent,'0');
assert.ok([...r.querySelectorAll('[data-action="start"]')].every(b=>b.disabled));
await w.happyDOM.close();console.log('Battery stop-state UI tests passed');

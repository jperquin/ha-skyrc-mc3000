import fs from 'node:fs';
import assert from 'node:assert/strict';
import {Window} from 'happy-dom';
const w=new Window({url:'https://ha.test/'});w.eval(fs.readFileSync(new URL('../../www/mc3000-batteries-card.js',import.meta.url),'utf8'));
const card=w.document.createElement('mc3000-batteries-card');w.document.body.append(card);
const ids=['sensor.charger_bay_one','sensor.charger_bay_two','sensor.charger_bay_three','sensor.charger_bay_four'];
const config={entity:'sensor.my_cell_library',companion_entity:'switch.charger_phone_access',status_entities:ids};
card.setConfig(config);
const cells=[1,2,3,4].map(n=>({id:`c${n}`,name:`Cell ${n}`,chemistry:'liion',capacity_mah:3000,charge_current:1.5,discharge_current:.5,charge_voltage:4200,discharge_voltage:3000,storage_voltage:3800,color:'#58a6ff'}));
const states={'sensor.my_cell_library':{state:'4',attributes:{cells,assignments:{1:'c1',2:'c2',3:'c3',4:'c4'},jobs:{},reports:[]}},'switch.charger_phone_access':{state:'off'},'switch.skyrc_mc3000_companion_app_mode':{state:'on'}};
for(let i=0;i<4;i++){states[ids[i]]={state:['standby','charge','done','unavailable'][i]};states[`sensor.skyrc_mc3000_slot_${i+1}_status`]={state:'standby'};}
const calls=[];const hass={language:'en',states,callService:async(...args)=>calls.push(args)};card.hass=hass;
const r=card.shadowRoot;
assert.equal(card._online,true);
assert.equal(r.getElementById('cell-count').textContent,'4');
assert.equal(card._phone,false); // conflicting default switch is ignored
assert.equal(card._ready(1),true);assert.equal(card._ready(2),false);assert.equal(card._ready(3),true);assert.equal(card._ready(4),false);
assert.equal(r.querySelector('[data-action="start"][data-slot="1"]').disabled,false);
assert.equal(r.querySelector('[data-action="start"][data-slot="2"]').disabled,true);
assert.equal(r.querySelector('[data-action="start"][data-slot="3"]').disabled,false);
assert.equal(r.querySelector('[data-action="start"][data-slot="4"]').disabled,true);
// Configuration owns its slot list; later mutation of the caller's array cannot redirect a slot.
ids[0]='sensor.changed_outside';assert.equal(card._config.status_entities[0],'sensor.charger_bay_one');
states['switch.skyrc_mc3000_companion_app_mode'].state='off';states['switch.charger_phone_access'].state='on';card.hass={...hass};
assert.equal(card._phone,true);assert.equal(r.querySelector('[data-action="start"][data-slot="1"]').disabled,true);
card._startDialog(1);assert.equal(r.getElementById('dialog').open,false);assert.equal(calls.length,0);
states['sensor.my_cell_library'].attributes.jobs={'1':{id:'j1',slot:1,cell_id:'c1',cell_name:'Cell 1',state:'paused',phase:'discharge',metrics:{}}};card.hass={...hass};
assert.equal(r.querySelector('[data-action="resume"][data-slot="1"]').disabled,true);
states['switch.charger_phone_access'].state='off';card.hass={...hass};assert.equal(r.querySelector('[data-action="resume"][data-slot="1"]').disabled,false);
for(const invalid of [null,[],['a'],['a','b','c'],['a','b','c','d','e'],['a','b','c',null],['a','b','c',3],['a','b','c','  '],'sensor.not_an_array'])assert.throws(()=>card.setConfig({status_entities:invalid}),/status_entities must contain four/);
for(const invalid of [null,3,'','  '])assert.throws(()=>card.setConfig({companion_entity:invalid}),/companion_entity must be/);
// Default IDs remain backward compatible.
card.setConfig({});assert.equal(card._config.companion_entity,'switch.skyrc_mc3000_companion_app_mode');
assert.equal(JSON.stringify(card._config.status_entities),JSON.stringify([1,2,3,4].map(n=>`sensor.skyrc_mc3000_slot_${n}_status`)));
assert.equal(card._config.entity,'sensor.skyrc_mc3000_batteries');
await w.happyDOM.close();console.log('Battery entity override tests passed');

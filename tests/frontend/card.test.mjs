import {readFile,writeFile} from 'node:fs/promises';
import {chromium} from 'playwright';
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined});
try {
const page=await browser.newPage({viewport:{width:1280,height:1000}});
await page.route('**/*',route=>route.abort());
page.on('console',msg=>console.log(msg.text()));
await page.setContent('<!doctype html><html lang="uk"><head><style>body{font:16px system-ui;background:#101821;color:#e6edf3;margin:24px;--primary-color:#3498db;--primary-text-color:#e6edf3;--secondary-text-color:#a4b1be;--card-background-color:#1c2531;--secondary-background-color:#263544;--divider-color:#455260;--text-primary-color:#fff}mc3000-programs-card{display:block;max-width:1100px;margin:0 auto 24px}</style></head><body></body></html>');
await page.addScriptTag({content:await readFile(new URL('../../www/mc3000-programs-card.js',import.meta.url),'utf8')});
const payloads=await page.evaluate(async()=>{
const win=window;
const assert={equal:(a,b,m)=>{if(!Object.is(a,b))throw Error((m||'equality')+': '+JSON.stringify(a)+' != '+JSON.stringify(b));},deepEqual:(a,b,m)=>{if(JSON.stringify(a)!==JSON.stringify(b))throw Error(m||'deep equality');},match:(s,re)=>{if(!re.test(s))throw Error('No match: '+s)}};
const library={profiles:[],selected:{},applied:{},revision:0};
const calls=[];
const cards=[];
let rejectNext=false;
let language='uk';
const snapshot=()=>({language,states:{
  'sensor.skyrc_mc3000_programs':{state:String(library.profiles.length),attributes:structuredClone(library)},
  'switch.skyrc_mc3000_companion_app_mode':{state:'off'},
  ...Object.fromEntries([1,2,3,4].map(n=>[`sensor.skyrc_mc3000_slot_${n}_status`,{state:'standby'}]))
},callService:async(domain,service,data)=>{
  calls.push({domain,service,data:structuredClone(data)});
  if(rejectNext){rejectNext=false;throw Error('Помилка перевірки сервера');}
  if(service==='save_profile'){
    assert.equal(data.revision,library.revision);
    const id=data.profile_id||`p${library.profiles.length+1}`;
    library.profiles=library.profiles.filter(p=>p.id!==id);
    library.profiles.push({id,name:data.name,program:structuredClone(data.program)});
  }else if(service==='select_profile') library.selected[String(data.slot)]=data.profile_id;
  else if(service==='apply_profile') for(const slot of data.slots) library.applied[String(slot)]=library.profiles.find(p=>p.id===data.profile_id).name;
  else if(service==='delete_profile') library.profiles=library.profiles.filter(p=>p.id!==data.profile_id);
  library.revision++;
  for(const card of cards) card.hass=snapshot();
}});
const make=(config)=>{const card=win.document.createElement('mc3000-programs-card');card.setConfig(config);win.document.body.append(card);cards.push(card);card.hass=snapshot();return card;};
const root=(card)=>card.shadowRoot;
const field=(card,name)=>root(card).getElementById(`f-${name}`);
const edit=(card,name,value)=>{const el=field(card,name);el.value=String(value);el.dispatchEvent(new win.Event('input',{bubbles:true}));el.dispatchEvent(new win.Event('change',{bubbles:true}));};
const flush=()=>new Promise(r=>setTimeout(r,0));
const editor=make({mode:'editor'});
assert.equal(field(editor,'battery_type').value,'','Chemistry must be explicit');
assert.equal(field(editor,'capacity').value,'','Capacity must be explicit');
await editor._save(); assert.equal(calls.length,0,'Empty draft must never call backend');
edit(editor,'name','18650 <img src=x onerror=alert(1)>');
edit(editor,'battery_type','liion'); edit(editor,'operation','charge');edit(editor,'capacity',3000);
const focused=field(editor,'charge_current');focused.focus();edit(editor,'charge_current',1.5);
editor.hass=snapshot();assert.equal(root(editor).activeElement,focused,'State updates must preserve focused element');assert.equal(focused.value,'1.5');
await editor._save();await flush();
assert.equal(calls.at(-1).service,'save_profile');
assert.equal(library.profiles[0].program.charge_voltage,4200,'V converts to mV');
assert.equal(library.profiles[0].program.charge_current,1.5,'Main currents stay A');
assert.equal(Object.keys(library.profiles[0].program).length,18,'Full parameter set required');
assert.equal(editor._dirty,false);assert.equal(editor._pendingSave,null);
assert.equal(root(editor).querySelector('img'),null,'Saved names cannot create HTML');
assert.equal(calls.some(c=>c.service==='apply_profile'),false,'Saving cannot touch hardware');

// Applying is asynchronous: temporary disabled controls must preserve all target slots.
editor._slots=new Set([1,2,3,4]);editor._refresh();editor._review();
const multiDialog=root(editor).getElementById('dialog');
const multiCheck=multiDialog.querySelector('#confirm-cells');multiCheck.checked=true;multiCheck.dispatchEvent(new win.Event('change',{bubbles:true}));
multiDialog.querySelector('#dialog-confirm').click();
assert.equal(editor._busy,true,'Transfer remains busy until service promise resolves');
assert.deepEqual([...editor._slots],[1,2,3,4],'Busy refresh must preserve chosen slots');
assert.equal(multiDialog.querySelector('#dialog-confirm').textContent,'Передавання параметрів…','Modal must show transmission progress');
assert.equal(root(editor).querySelector('[data-action=apply]').textContent,'Передавання параметрів…','Apply panel must show transmission progress');
for(const n of [1,2,3,4]){assert.equal(root(editor).getElementById(`target-${n}`).checked,true);assert.equal(root(editor).getElementById(`target-${n}`).disabled,true);}
await flush();
assert.deepEqual([...editor._slots],[1,2,3,4],'Chosen slots survive completed transfer');
for(const n of [1,2,3,4]){assert.equal(root(editor).getElementById(`target-${n}`).checked,true);assert.equal(root(editor).getElementById(`target-${n}`).disabled,false);}
const actuallyBusy=snapshot();actuallyBusy.states['sensor.skyrc_mc3000_slot_3_status'].state='charge';editor.hass=actuallyBusy;
assert.deepEqual([...editor._slots],[1,2,4],'Actual running slot is still removed from selection');
editor.hass=snapshot();

const slot=make({slot:1});const select=root(slot).getElementById('slot-profile');select.value='p1';select.dispatchEvent(new win.Event('change',{bubbles:true}));await flush();
assert.equal(calls.at(-1).service,'select_profile');
slot._review();const dialog=root(slot).getElementById('dialog');assert.equal(dialog.open,true);
assert.equal(dialog.querySelector('#dialog-confirm').disabled,true,'Apply requires explicit checkbox');
const check=dialog.querySelector('#confirm-cells');check.checked=true;check.dispatchEvent(new win.Event('change',{bubbles:true}));dialog.querySelector('#dialog-confirm').click();await flush();
assert.equal(calls.at(-1).service,'apply_profile');assert.deepEqual(calls.at(-1).data,{slots:[1],profile_id:'p1'});
assert.equal(calls.some(c=>/start/.test(c.service)),false,'No UI action starts a program');

const phone=snapshot();phone.states['switch.skyrc_mc3000_companion_app_mode'].state='on';slot.hass=phone;assert.equal(root(slot).querySelector('[data-action=apply]').disabled,true,'Phone mode prevents apply');
const active=snapshot();active.states['sensor.skyrc_mc3000_slot_1_status'].state='charge';slot.hass=active;assert.equal(root(slot).querySelector('[data-action=apply]').disabled,true,'Active slot prevents apply');
slot.hass=snapshot();slot._review();const stale=root(slot).getElementById('dialog');const ack=stale.querySelector('#confirm-cells');ack.checked=true;ack.dispatchEvent(new win.Event('change',{bubbles:true}));
library.profiles[0].program.charge_current=.6;slot.hass=snapshot();const before=calls.length;stale.querySelector('#dialog-confirm').click();await flush();assert.equal(calls.length,before,'Stale confirmation cannot write changed profile');assert.equal(stale.open,true);assert.match(stale.querySelector('#dialog-error').textContent,/змінилася/);stale.close();

editor._load('p1');edit(editor,'name','Моя чернетка');library.profiles.push({...structuredClone(library.profiles[0]),id:'p2',name:'Інший профіль'});library.revision++;editor.hass=snapshot();assert.equal(field(editor,'name').value,'Моя чернетка');assert.equal(editor._conflict,true);
const conflictCalls=calls.length;await editor._save();assert.equal(calls.length,conflictCalls,'Conflicting draft requires resolution');
editor._load(null);edit(editor,'name','NiMH формування');edit(editor,'battery_type','nimh');edit(editor,'operation','breakin');edit(editor,'capacity',100);
assert.equal(Number(field(editor,'charge_current').value),.01);assert.equal(Number(field(editor,'discharge_current').value),.02);
assert.equal(Number(field(editor,'charge_end_current').value),10);assert.equal(Number(field(editor,'discharge_end_current').value),20);
assert.equal(field(editor,'charge_current').readOnly,true);
await editor._save();await flush();assert.equal(calls.at(-1).service,'save_profile');assert.equal(library.profiles.at(-1).program.capacity,100);
editor._load(null);edit(editor,'name','Storage');edit(editor,'battery_type','liion');edit(editor,'operation','storage');edit(editor,'capacity',3000);
assert.equal(Number(field(editor,'charge_voltage').value),3.8);assert.equal(field(editor,'charge_voltage').max,'4');
rejectNext=true;await editor._save();assert.equal(editor._pendingSave,null);assert.equal(editor._dirty,true);assert.match(root(editor).getElementById('notice').textContent,/Помилка перевірки/);

editor._load('p1');library.profiles[0].program.charge_current=.8;library.revision++;editor.hass=snapshot();assert.equal(Number(field(editor,'charge_current').value),.8,'Clean editor must reload external profile changes');
const payloads=[];
for(const chemistry of ['liion','life','liion_4_35','nimh','nicd','eneloop','nizn','ram','batlto','naion']){
  editor._load(null);edit(editor,'battery_type',chemistry);
  const modes=[...field(editor,'operation').options].map(o=>o.value).filter(Boolean);
  for(const operation of modes){
    editor._load(null);edit(editor,'name',`${chemistry} ${operation}`);edit(editor,'battery_type',chemistry);edit(editor,'operation',operation);edit(editor,'capacity',2000);
    const count=calls.length;await editor._save();await flush();
    assert.equal(calls.length,count+1,`${chemistry}/${operation} must produce valid profile form`);
    payloads.push(calls.at(-1).data.program);
  }
}

console.log('PASS: explicit chemistry/capacity, validation, full payload, unit conversion, XSS escaping, dirty focus preservation, save/select/apply separation, confirmations, phone/running/stale guards, conflict handling, break-in derivation, storage voltages, service errors.');

language=undefined;
const english=make({mode:'editor'});
assert.equal(root(english).querySelector('h2').textContent,'My programs','Missing HA language defaults to English');
assert.equal(root(english).querySelector('label[for=f-charge_current]').textContent,'Charge current · A');
await english._save();assert.match(root(english).getElementById('notice').textContent,/Complete the field/);
edit(english,'name','English profile');edit(english,'battery_type','liion');edit(english,'operation','storage');edit(english,'capacity',3000);
assert.equal(field(english,'operation').selectedOptions[0].textContent,'Storage');
assert.equal(field(english,'cycle_type').options[1].textContent,'C → D → C');
assert.match(root(english).getElementById('h-maintenance_voltage').textContent,/3\.98–4\.18 V/);
await english._save();await flush();
assert.match(root(english).getElementById('notice').textContent,/Program saved in Home Assistant/);
english._slots=new Set([1,2,3,4]);english._refresh();english._review();
const englishDialog=root(english).getElementById('dialog');
assert.equal(englishDialog.querySelector('h3').textContent,'Apply program?');
assert.match(englishDialog.textContent,/3\.8 V/);
const englishCheck=englishDialog.querySelector('#confirm-cells');englishCheck.checked=true;englishCheck.dispatchEvent(new win.Event('change',{bubbles:true}));
englishDialog.querySelector('#dialog-confirm').click();
assert.equal(englishDialog.querySelector('#dialog-confirm').textContent,'Transmitting parameters…');
assert.deepEqual([...english._slots],[1,2,3,4]);await flush();
assert.match(root(english).getElementById('notice').textContent,/Parameters transmitted: slot 1, slot 2, slot 3, slot 4/);
edit(english,'name','User name Заряд must stay unchanged');
field(english,'name').focus();field(english,'name').setSelectionRange(2,5);root(english).getElementById('advanced').open=true;
english.hass={...snapshot(),language:'uk-UA'};
assert.equal(root(english).querySelector('h2').textContent,'Мої програми');
assert.equal(field(english,'name').value,'User name Заряд must stay unchanged');assert.equal(english._dirty,true);
assert.equal(root(english).activeElement,field(english,'name'));assert.equal(field(english,'name').selectionStart,2);assert.equal(root(english).getElementById('advanced').open,true);
assert.equal(field(english,'operation').selectedOptions[0].textContent,'Зберігання');
assert.match(root(english).getElementById('h-maintenance_voltage').textContent,/3,98–4,18 В/);
english.hass={...snapshot(),language:'de'};assert.equal(root(english).querySelector('h2').textContent,'My programs','Unsupported HA language falls back to English');
english.setConfig({mode:'editor',language:'uk'});english.hass={...snapshot(),language:'en'};assert.equal(root(english).querySelector('h2').textContent,'Мої програми','Ukrainian override wins over HA English');
english.setConfig({mode:'editor',language:'en'});english.hass={...snapshot(),language:'uk'};assert.equal(root(english).querySelector('h2').textContent,'My programs','English override wins over HA Ukrainian');
let invalidLanguage=false;try{english.setConfig({mode:'editor',language:'fr'});}catch(e){invalidLanguage=/language must be en or uk/.test(e.message);}assert.equal(invalidLanguage,true);
english.remove();
const renamedStatuses=[1,2,3,4].map(n=>`sensor.renamed_charger_bay_${n}`);
const renamed=make({slot:2,companion_entity:'switch.renamed_phone_access',status_entities:renamedStatuses});
const renamedHass=snapshot();delete renamedHass.states['switch.skyrc_mc3000_companion_app_mode'];
renamedHass.states['sensor.skyrc_mc3000_programs'].attributes.selected['2']='p1';
for(const n of [1,2,3,4]){delete renamedHass.states[`sensor.skyrc_mc3000_slot_${n}_status`];renamedHass.states[renamedStatuses[n-1]]={state:'standby'};}
renamedHass.states['switch.renamed_phone_access']={state:'off'};renamed.hass=renamedHass;
assert.equal(renamed._ready(2),true,'Configured status entity controls readiness');
assert.equal(root(renamed).querySelector('[data-action=apply]').disabled,false,'Renamed ready slot can be configured');
renamedHass.states[renamedStatuses[1]].state='charge';renamed.hass=renamedHass;
assert.equal(root(renamed).querySelector('[data-action=apply]').disabled,true,'Renamed running status blocks apply');
renamedHass.states[renamedStatuses[1]].state='standby';renamedHass.states['switch.renamed_phone_access'].state='on';renamed.hass=renamedHass;
const renamedCalls=calls.length;renamed._review();assert.equal(calls.length,renamedCalls,'Renamed phone mode prevents commands');assert.equal(root(renamed).getElementById('dialog').open,false);
for(const bad of [{status_entities:['sensor.one']},{status_entities:['sensor.one','sensor.two','sensor.three',null]},{companion_entity:'sensor.wrong_domain'}]){
 let failed=false;try{renamed.setConfig({slot:2,...bad});}catch(e){failed=true;}assert.equal(failed,true,'Invalid portability override must be rejected');
}
renamed.remove();
console.log('PASS: English default and save/apply-busy flow, both override directions, Ukrainian HA language prefixes, fallback language, translated errors/options/units, number locales, language changes preserve dirty draft/focus/selection/details and user names.');

window.previewEditor=editor;
editor._load(null);
edit(editor,'name','Моя програма');edit(editor,'battery_type','liion');edit(editor,'operation','charge');edit(editor,'capacity',3000);
root(editor).getElementById('advanced').open=true;
return payloads;
});
await writeFile('.test-artifacts/generated-profiles.json',JSON.stringify(payloads,null,2));
await page.screenshot({path:'.test-artifacts/editor-desktop.png',fullPage:true});
await page.setViewportSize({width:390,height:844});
await page.screenshot({path:'.test-artifacts/editor-mobile.png',fullPage:true});
const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
if(overflow)throw Error('Mobile horizontal overflow');
console.log('PASS: desktop/mobile layout has no horizontal overflow.');
} finally {await browser.close();}


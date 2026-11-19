import {readFile} from 'node:fs/promises';
import {chromium} from 'playwright';
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined});
try{
  const page=await browser.newPage({viewport:{width:900,height:620}});
  await page.route('**/*',route=>route.abort());
  await page.setContent('<!doctype html><html lang="uk"><style>body{font:16px system-ui;background:#101821;color:#e6edf3;margin:20px;--primary-color:#3498db;--primary-text-color:#e6edf3;--secondary-text-color:#a4b1be;--card-background-color:#1c2531;--secondary-background-color:#263544;--divider-color:#455260;--text-primary-color:#fff}mc3000-curve-card{display:block;max-width:800px;margin:auto}</style><body></body></html>');
  await page.addScriptTag({content:await readFile(new URL('../../www/mc3000-curve-card.js',import.meta.url),'utf8')});
  await page.evaluate(async()=>{
    const assert=(condition,message)=>{if(!condition)throw Error(message);};
    const card=document.createElement('mc3000-curve-card');card.setConfig({slot:2});document.body.append(card);
    let samples=[4200,4180,0,4150,4120,...Array(115).fill(0)],interval=30,until=null,phone=false,reject=false,calls=[],language='uk';
    const update=()=>{card.hass={language,states:{
      'sensor.skyrc_mc3000_slot_2_voltage_curve_points':{state:'4',attributes:{samples_mv:samples,interval_seconds:interval,plot_until_index:until,last_fetched:'2026-11-19T18:30:00',plot_reason:'last_nonzero_sample'}},
      'button.skyrc_mc3000_slot_2_fetch_voltage_curve':{state:'unknown'},
      'switch.skyrc_mc3000_companion_app_mode':{state:phone?'on':'off'}
    },callService:async(domain,service,data)=>{calls.push({domain,service,data});if(reject)throw Error('Помилка Bluetooth');}};};
    update();const root=card.shadowRoot;
    assert(card._curve.points.length===4,'Trailing zeroes must not be plotted');
    assert(card._curve.points.at(-1).seconds===120,'Time must preserve original index through interior zero');
    assert(root.querySelector('.line').getAttribute('d').match(/M/g).length===2,'Interior zero must break line');
    assert(root.getElementById('selection').textContent.includes('120 с'),'Selected detail uses elapsed seconds');
    const svg=root.querySelector('svg');svg.focus();svg.dispatchEvent(new KeyboardEvent('keydown',{key:'Home',bubbles:true}));
    assert(card._selected===0,'Keyboard Home selects first point');
    svg.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));assert(card._selected===1,'ArrowRight moves to next sample');
    until=1;update();assert(card._curve.points.length===2,'plot_until_index is inclusive');assert(root.activeElement===root.querySelector('svg'),'HA updates preserve graph focus');
    until=0;update();assert(card._curve.points.length===1,'Single point index0 is not mistaken for missing');
    assert(!root.querySelector('svg').innerHTML.includes('NaN'),'Single point has finite axes');
    const csv=card._csv();assert(csv.charCodeAt(0)===0xfeff,'CSV needs UTF-8 BOM');assert(csv.split('\r\n').length===122,'CSV includes all120 raw samples');assert(csv.includes('\r\n60,0\r\n'),'CSV preserves interior zero');assert(csv.includes('\r\n3570,0\r\n'),'CSV preserves trailing buffer');
    phone=true;update();assert(root.querySelector('[data-action=fetch]').disabled,'Phone mode blocks fetch');
    await card._fetch();assert(calls.length===0,'Blocked fetch calls no service');
    phone=false;update();await card._fetch();assert(calls.length===1&&calls[0].domain==='button'&&calls[0].service==='press'&&calls[0].data.entity_id==='button.skyrc_mc3000_slot_2_fetch_voltage_curve','Fetch invokes exact slot button');
    reject=true;await card._fetch();assert(root.getElementById('notice').textContent==='Помилка Bluetooth','Errors are visible');
    interval=0;update();assert(!root.querySelector('svg'),'Unknown interval must not fabricate elapsed time');assert(card._csv()===null,'CSV without elapsed interval is disabled');
    interval=30;samples=Array(120).fill(0);until=null;update();assert(!root.querySelector('svg'),'Allzero buffer shows empty state');
    samples=Array.from({length:120},(_,i)=>i<85?Math.round(4200-8*i-25*Math.sin(i/10)):0);until=80;reject=false;card._notice=null;update();
    assert(card._csv().startsWith('\uFEFFчас_секунди,напруга_мВ\r\n'),'Ukrainian CSV header');
    assert(root.querySelector('.stats').textContent.includes('4,2 В'),'Ukrainian decimal separator and unit');
    assert(root.querySelector('.meta').textContent.includes('лист'),'Ukrainian date locale');
    language=undefined;update();
    assert(root.querySelector('h3').textContent==='Voltage curve','Curve defaults to English');
    assert(root.querySelector('.stats').textContent.includes('4.2 V'),'English decimal separator and unit');
    assert(root.querySelector('.meta').textContent.includes('Nov'),'English date locale');
    assert(card._csv().startsWith('\uFEFFelapsed_seconds,millivolts\r\n'),'English CSV header');
    assert(card._csv().includes('\r\n30,4190\r\n'),'CSV numeric rows remain machine-readable in either language');
    let releaseRead;
    const savedHass=card.hass;card.hass={...savedHass,callService:()=>new Promise(resolve=>{releaseRead=resolve;})};
    const reading=card._fetch();assert(root.querySelector('[data-action=fetch]').textContent==='Reading…','English busy label');
    language='uk-UA';update();assert(root.querySelector('[data-action=fetch]').textContent==='Зчитування…','Busy label changes with HA language');
    releaseRead();await reading;assert(root.querySelector('#notice').textContent.startsWith('Запит на зчитування'),'Completion follows current language');
    language='fr';update();assert(root.querySelector('h3').textContent==='Voltage curve','Unsupported HA language falls back to English');
    card.setConfig({slot:2,language:'uk'});language='en';update();assert(root.querySelector('h3').textContent==='Крива напруги','Curve Ukrainian override');
    card.setConfig({slot:2,language:'en'});language='uk';update();assert(root.querySelector('h3').textContent==='Voltage curve','Curve English override');
    card.setConfig({slot:2});language='uk';update();
    card.setConfig({slot:2,companion_entity:'switch.renamed_phone_access'});
    const renamedHass=card.hass;delete renamedHass.states['switch.skyrc_mc3000_companion_app_mode'];renamedHass.states['switch.renamed_phone_access']={state:'on'};card.hass=renamedHass;
    const renamedCalls=calls.length;await card._fetch();assert(calls.length===renamedCalls,'Renamed companion switch blocks fetch commands');assert(root.querySelector('[data-action=fetch]').disabled,'Renamed phone mode disables fetch');
    renamedHass.states['switch.renamed_phone_access'].state='off';card.hass=renamedHass;assert(!root.querySelector('[data-action=fetch]').disabled,'Renamed phone mode off allows fetch');
    let badCompanion=false;try{card.setConfig({slot:2,companion_entity:['switch.invalid']});}catch(e){badCompanion=true;}assert(badCompanion,'Malformed companion override rejected');
    card.setConfig({slot:2});update();
    window.card=card;
  });
  await page.screenshot({path:'.test-artifacts/curve-desktop.png',fullPage:true});
  await page.setViewportSize({width:360,height:640});
  await page.screenshot({path:'.test-artifacts/curve-mobile.png',fullPage:true});
  const box=await page.locator('mc3000-curve-card').locator('svg').boundingBox();
  await page.mouse.click(box.x+box.width*.5,box.y+box.height*.5);
  const checked=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth,selected:window.card._selected}));
  if(checked.overflow)throw Error('Mobile horizontal overflow');
  if(checked.selected<25||checked.selected>50)throw Error('Tap selection does not match chart position');
  console.log('PASS: curve parsing, inclusive bound, gap handling, singleton axes, elapsed time, keyboard and tap selection, focus preservation, UTF-8 BOM/raw CSV, phone blocking, correct button service, visible errors, missing interval, zero buffer, desktop/mobile layout.');
}finally{await browser.close();}

/* Cached MC3000 voltage curve: elapsed sampling time, never wall-clock history. */
(() => {
  "use strict";
  const TAG = "mc3000-curve-card";
  // English source messages are the stable translation keys. User data is never translated.
  const UK = {
  "companion_entity must be a switch entity ID": "companion_entity має бути ідентифікатором сутності switch",
  "elapsed_seconds,millivolts": "час_секунди,напруга_мВ",
  "language must be en or uk": "language має бути en або uk",
  "“": "«",
  "”": "»",
  "Set an MC3000 slot: 1–4": "Вкажіть слот MC3000: 1–4",
  "The curve requires a sensor and a fetch button entity": "Для кривої потрібні sensor та кнопка зчитування button",
  "Minimum": "Мінімум",
  " V": " В",
  "Maximum": "Максимум",
  "Duration": "Тривалість",
  " min": " хв",
  "interactive chart": "інтерактивний графік",
  "Slot voltage · ": "Напруга слота ",
  " by elapsed time since recording started. Left and right arrows select points.": " за часом від початку запису. Стрілки ліворуч і праворуч перемикають точки.",
  "V": "В",
  "min since recording started": "хв від початку запису",
  "Tap the graph or hover over a point. Keyboard: ← →.": "Торкніться графіка або наведіть курсор на точку. На клавіатурі — ← →.",
  "Unknown sampling interval": "Невідомий інтервал запису",
  "The buffer is empty": "Буфер поки порожній",
  "No curve has been read yet": "Криву ще не зчитано",
  "Voltage samples are available, but the charger did not report an interval. Read the curve again to display an accurate time axis.": "Значення напруги є, але зарядка не передала інтервал. Зчитайте криву повторно, щоб побудувати шкалу часу.",
  "Press “Read” to retrieve samples from charger memory. Empty buffer entries are not plotted as a drop to zero.": "Натисніть «Зчитати», щоб отримати точки з пам’яті зарядки. Порожній буфер не відображається як падіння до нуля.",
  " · interval ": " · крок ",
  " s": " с",
  "The graph ends when current stopped. ": "Графік обмежено моментом зупинки струму. ",
  "Slot ": "Слот ",
  " · charger memory": " · пам’ять зарядки",
  "Voltage curve": "Крива напруги",
  "Measurements by elapsed time since recording started": "Вимірювання за часом від початку запису",
  "Read": "Зчитати",
  "All buffer samples: elapsed seconds and voltage in mV": "Усі точки буфера: час у секундах і напруга в мВ",
  " points plotted": " точок на графіку",
  "Read at: ": "Зчитано: ",
  "CSV includes the full buffer (": "CSV містить весь буфер (",
  " points), including zero values.": " точок), зокрема нульові значення.",
  "Point ": "Точка ",
  " s (": " с (",
  " min)": " хв)",
  " V · ": " В · ",
  " mV": " мВ",
  "Reading…": "Зчитування…",
  "Phone access is enabled. Disable it to read again; the cached curve is still available.": "Увімкнено доступ із телефона. Для нового зчитування вимкніть його; збережена крива доступна.",
  "Read request completed. The retrieval time is shown below the graph.": "Запит на зчитування виконано. Час отримання показано під графіком.",
  "MC3000 · Voltage curve": "MC3000 · Крива напруги",
  "Voltage curve from charger memory, point selection and CSV export": "Крива напруги з пам’яті зарядки, вибір точки та CSV"
};
  const EN = new Map(Object.entries(UK).map(([en,uk])=>[uk,en]));
  const escape = (v) => String(v ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const W=640, H=250, LEFT=58, RIGHT=18, TOP=18, BOTTOM=48;
  const STYLE = `
    :host{display:block;color:var(--primary-text-color,#e6edf3);font:inherit;line-height:1.45;container:mc-curve / inline-size}*{box-sizing:border-box}ha-card{display:block;background:var(--ha-card-background,var(--card-background-color,#1c2531));border-radius:var(--ha-card-border-radius,16px);border:var(--ha-card-border-width,1px) solid var(--ha-card-border-color,var(--divider-color,#394554));box-shadow:var(--ha-card-box-shadow,none)}.card{padding:18px}.head{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;flex-wrap:wrap}.eyebrow{font-size:10px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--secondary-text-color,#a4b1be);margin-block-end:4px}h3{margin:0;font-size:17px;font-weight:650}.subtitle{font-size:12px;color:var(--secondary-text-color,#a4b1be);margin-block-start:4px}.actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center}button{font:inherit;font-size:12px;font-weight:600;line-height:1.35;color:var(--primary-text-color,#e6edf3);background:transparent;border:1px solid var(--divider-color,#394554);border-radius:9px;padding:10px 13px;min-block-size:44px;cursor:pointer;touch-action:manipulation}button.primary{background:var(--primary-color,#48a9fa);border-color:var(--primary-color,#48a9fa);color:var(--text-primary-color,#fff)}button:hover:not(:disabled){filter:brightness(1.12)}button:disabled{cursor:default;opacity:.45}button:focus-visible,.chart:focus-visible{outline:3px solid var(--primary-color,#48a9fa);outline-offset:3px}.stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-block:18px 4px}.stat small{display:block;font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:var(--secondary-text-color,#a4b1be)}.stat strong{font-size:16px;font-weight:600;overflow-wrap:anywhere}.chart{display:block;width:100%;height:auto;min-height:160px;margin-block:8px;touch-action:pan-y;cursor:crosshair}.chart text{fill:var(--secondary-text-color,#a4b1be);font:12px system-ui,sans-serif}.grid{stroke:var(--divider-color,#394554);stroke-width:1;stroke-dasharray:3 5}.line{fill:none;stroke:var(--primary-color,#48a9fa);stroke-width:2.6;stroke-linejoin:round;stroke-linecap:round;vector-effect:non-scaling-stroke}.point{fill:var(--primary-color,#48a9fa)}.crosshair{stroke:var(--secondary-text-color,#a4b1be);stroke-width:1;stroke-dasharray:4 4;pointer-events:none}.selected{fill:var(--primary-color,#48a9fa);stroke:var(--card-background-color,#1c2531);stroke-width:2;pointer-events:none}.selection{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;padding:10px 12px;border-radius:9px;background:var(--secondary-background-color,#263544);font-size:12px;min-block-size:38px;font-variant-numeric:tabular-nums}.selection strong{font-weight:650}.meta{display:flex;justify-content:space-between;gap:5px 14px;flex-wrap:wrap;margin-block-start:12px;font-size:11px;color:var(--secondary-text-color,#a4b1be)}.help{font-size:11px;color:var(--secondary-text-color,#a4b1be);margin-block:9px 0}.empty{display:grid;place-content:center;min-block-size:170px;text-align:center;gap:8px;margin-block:16px;padding:18px;border:1px dashed var(--divider-color,#394554);border-radius:12px}.empty strong{font-size:15px}.empty span{max-inline-size:44ch;font-size:12px;color:var(--secondary-text-color,#a4b1be)}.notice{font-size:12px;margin-block-start:12px;padding:10px 12px;border-inline-start:3px solid var(--primary-color,#48a9fa);border-radius:8px;background:var(--secondary-background-color,#263544);overflow-wrap:anywhere}.notice.error{border-color:var(--error-color,#ef7979)}[hidden]{display:none!important}@container mc-curve (max-width:360px){.card{padding:14px}.head{gap:10px}.actions{width:100%}.actions button{flex:1}.stats{gap:8px}.stat strong{font-size:14px}.chart{min-height:150px}.chart text{font-size:22px}.selection{font-size:11px}}@media(forced-colors:active){.line{stroke:Highlight}.point,.selected{fill:Highlight}.grid,.crosshair{stroke:CanvasText}}
  `;

  class MC3000CurveCard extends HTMLElement {
    constructor() {
      super(); this.attachShadow({mode:"open"}); this._busy=false; this._notice=null; this._selected=null;
      this.shadowRoot.addEventListener("click",e=>{const b=e.target.closest("button");if(b?.disabled)return;if(b?.dataset.action==="fetch")this._fetch();if(b?.dataset.action==="csv")this._download();});
    }
    setConfig(config) {
      if (config.language !== undefined && !["en","uk"].includes(config.language)) throw new Error(this._t("language must be en or uk"));
      const slot=Number(config.slot); if(![1,2,3,4].includes(slot))throw new Error(this._t("Set an MC3000 slot: 1–4"));
      this._config={entity:`sensor.skyrc_mc3000_slot_${slot}_voltage_curve_points`,fetch_entity:`button.skyrc_mc3000_slot_${slot}_fetch_voltage_curve`,companion_entity:"switch.skyrc_mc3000_companion_app_mode",...config,slot};
      if(typeof this._config.companion_entity!=="string"||!/^switch\.[a-z0-9_]+$/.test(this._config.companion_entity))throw new Error(this._t("companion_entity must be a switch entity ID"));
      if(!this._config.entity.startsWith("sensor.")||!this._config.fetch_entity.startsWith("button."))throw new Error(this._t("The curve requires a sensor and a fetch button entity"));
      this._signature=null; this._render();
    }
    set hass(hass) {
      this._hass=hass;if(!this._config)return;
      const signature=JSON.stringify([this._attributes,this._entity?.state,this._language]);
      if(signature!==this._signature){this._signature=signature;this._render();}else this._controls();
    }
    get _language() { return String(this._config?.language ?? this._hass?.language ?? "en").toLowerCase().startsWith("uk") ? "uk" : "en"; }
    get _locale() { return this._language === "uk" ? "uk-UA" : "en-US"; }
    _t(message) { const key = EN.get(message) ?? message; return this._language === "uk" ? UK[key] ?? key : key; }
    _fmt(value, digits=2) { return Number.isFinite(Number(value)) ? Number(value).toLocaleString(this._locale, {maximumFractionDigits:digits}) : "—"; }
    get hass(){return this._hass;}
    get _entity(){return this._hass?.states?.[this._config?.entity];}
    get _attributes(){return this._entity?.attributes||{};}
    get _phone(){return this._hass?.states?.[this._config?.companion_entity]?.state==="on";}
    getCardSize(){return 6;}
    getGridOptions(){return{columns:12,rows:"auto",min_columns:6};}
    static getStubConfig(){return{slot:1};}
    _data() {
      const attrs=this._attributes;
      const samples=Array.isArray(attrs.samples_mv)?attrs.samples_mv.slice(0,120).map(v=>typeof v==="number"&&Number.isFinite(v)&&v>=0?v:null):[];
      const interval=typeof attrs.interval_seconds==="number"&&Number.isFinite(attrs.interval_seconds)&&attrs.interval_seconds>0?attrs.interval_seconds:null;
      let last=samples.findLastIndex(v=>v!==null&&v>0);
      if(typeof attrs.plot_until_index==="number"&&Number.isFinite(attrs.plot_until_index))last=Math.max(-1,Math.min(last,Math.floor(attrs.plot_until_index)));
      const plotted=samples.slice(0,last+1);
      const points=plotted.map((mv,index)=>({mv,index,seconds:interval===null?null:index*interval})).filter(p=>p.mv!==null&&p.mv>0);
      return{samples,interval,points,last};
    }
    _render() {
      if(!this._config)return;
      const focusedChart=this.shadowRoot.activeElement?.classList.contains("chart");
      const focusedAction=this.shadowRoot.activeElement?.dataset.action;
      this._curve=this._data();
      const {points,interval}=this._curve;
      this._selected=points.some(p=>p.index===this._selected)?this._selected:points.at(-1)?.index??null;
      const valid=points.length>0&&interval!==null;
      const duration=points.at(-1)?.seconds??0;
      const minimum=points.length?Math.min(...points.map(p=>p.mv)):0;
      const maximum=points.length?Math.max(...points.map(p=>p.mv)):0;
      let content;
      if(valid){
        const span=Math.max(maximum-minimum,40),padding=span*.12;
        const step=Math.pow(10,Math.floor(Math.log10(span/4)));
        const yStep=[1,2,5,10].map(n=>n*step).find(n=>n>=(span+2*padding)/4)||step*10;
        const yMin=Math.max(0,Math.floor((minimum-padding)/yStep)*yStep);
        const yMax=Math.ceil((maximum+padding)/yStep)*yStep;
        const end=Math.max(duration,interval);
        this._scale={x:index=>LEFT+(index*interval/end)*(W-LEFT-RIGHT),y:mv=>TOP+(1-(mv-yMin)/(yMax-yMin))*(H-TOP-BOTTOM),end};
        const ticks=[];for(let y=yMin;y<=yMax+yStep*.01;y+=yStep)ticks.push(y);
        const yGrid=ticks.map(y=>`<line class="grid" x1="${LEFT}" x2="${W-RIGHT}" y1="${this._scale.y(y)}" y2="${this._scale.y(y)}"/><text x="${LEFT-10}" y="${this._scale.y(y)+4}" text-anchor="end">${this._fmt(y/1000,3)}</text>`).join("");
        const xGrid=[0,.25,.5,.75,1].map(f=>`<text x="${LEFT+f*(W-LEFT-RIGHT)}" y="${H-BOTTOM+23}" text-anchor="middle">${this._fmt(f*end/60,2)}</text>`).join("");
        let prev=-2;
        const path=points.map(p=>{const command=p.index===prev+1?"L":"M";prev=p.index;return`${command}${this._scale.x(p.index).toFixed(2)} ${this._scale.y(p.mv).toFixed(2)}`;}).join(" ");
        const isolated=points.filter((p,i)=>points[i-1]?.index!==p.index-1&&points[i+1]?.index!==p.index+1).map(p=>`<circle class="point" cx="${this._scale.x(p.index)}" cy="${this._scale.y(p.mv)}" r="3"/>`).join("");
        content=`<div class="stats"><div class="stat"><small>${this._t("Minimum")}</small><strong>${this._fmt(minimum/1000,3)}${this._t(" V")}</strong></div><div class="stat"><small>${this._t("Maximum")}</small><strong>${this._fmt(maximum/1000,3)}${this._t(" V")}</strong></div><div class="stat"><small>${this._t("Duration")}</small><strong>${this._fmt(duration/60,2)}${this._t(" min")}</strong></div></div><svg class="chart" viewBox="0 0 ${W} ${H}" role="group" aria-roledescription="${this._t("interactive chart")}" aria-label="${this._t("Slot voltage · ")}${this._config.slot}${this._t(" by elapsed time since recording started. Left and right arrows select points.")}" tabindex="0"><text x="${LEFT}" y="11">${this._t("V")}</text>${yGrid}${xGrid}<text x="${W-RIGHT}" y="${H-3}" text-anchor="end">${this._t("min since recording started")}</text><path class="line" d="${path}"/>${isolated}<line id="crosshair" class="crosshair" y1="${TOP}" y2="${H-BOTTOM}"/><circle id="selected" class="selected" r="5"/></svg><div class="selection" id="selection" role="status" aria-live="polite"></div><p class="help">${this._t("Tap the graph or hover over a point. Keyboard: ← →.")}</p>`;
      }else{
        this._scale=null;
        const missingTime=points.length>0&&interval===null;
        content=`<div class="empty"><strong>${missingTime?this._t("Unknown sampling interval"):this._curve.samples.length?this._t("The buffer is empty"):this._t("No curve has been read yet")}</strong><span>${missingTime?this._t("Voltage samples are available, but the charger did not report an interval. Read the curve again to display an accurate time axis."):this._t("Press “Read” to retrieve samples from charger memory. Empty buffer entries are not plotted as a drop to zero.")}</span></div>`;
      }
      const fetched=this._attributes.last_fetched;
      const fetchedDate = typeof fetched === "string" ? new Date(fetched) : null;
      const fetchedText = fetchedDate && Number.isFinite(fetchedDate.getTime()) ? fetchedDate.toLocaleString(this._locale, {dateStyle:"medium",timeStyle:"medium"}) : "—";
      this.shadowRoot.innerHTML=`<style>${STYLE}</style><ha-card lang="${this._language}"><div class="card"><header class="head"><div><div class="eyebrow">${this._t("Slot ")}${this._config.slot}${this._t(" · charger memory")}</div><h3>${this._t("Voltage curve")}</h3><div class="subtitle">${this._t("Measurements by elapsed time since recording started")}</div></div><div class="actions"><button type="button" data-action="fetch" class="primary">${this._t("Read")}</button><button type="button" data-action="csv" title="${this._t("All buffer samples: elapsed seconds and voltage in mV")}">CSV ↓</button></div></header>${content}<div class="meta"><span>${points.length}${this._t(" points plotted")}${interval===null?"":`${this._t(" · interval ")}${this._fmt(interval,3)}${this._t(" s")}`}</span><span>${this._t("Read at: ")}${escape(fetchedText)}</span></div><p class="help">${this._attributes.plot_reason==="current_zero_elapsed"?this._t("The graph ends when current stopped. "):""}${this._t("CSV includes the full buffer (")}${this._curve.samples.length}${this._t(" points), including zero values.")}</p><div id="notice" class="notice" role="status" aria-live="polite" hidden></div></div></ha-card>`;
      const chart=this.shadowRoot.querySelector("svg");
      if(chart){
        chart.addEventListener("pointermove",e=>{if(e.pointerType!=="touch")this._pick(e);});
        chart.addEventListener("pointerdown",e=>this._pick(e));
        chart.addEventListener("keydown",e=>{
          if(!["ArrowLeft","ArrowRight","Home","End"].includes(e.key))return;
          e.preventDefault();const i=points.findIndex(p=>p.index===this._selected);
          const next=e.key==="Home"?0:e.key==="End"?points.length-1:Math.max(0,Math.min(points.length-1,i+(e.key==="ArrowRight"?1:-1)));
          this._selected=points[next].index;this._selection();
        });
      }
      this._selection();this._controls();
      if(focusedChart)chart?.focus({preventScroll:true});
      else if(focusedAction)this.shadowRoot.querySelector(`[data-action="${focusedAction}"]`)?.focus({preventScroll:true});
    }
    _pick(event){
      const svg=this.shadowRoot.querySelector("svg");const bounds=svg.getBoundingClientRect();
      if(!bounds.width)return;
      const viewX=(event.clientX-bounds.left)/bounds.width*W;
      const closest=this._curve.points.reduce((best,p)=>Math.abs(this._scale.x(p.index)-viewX)<Math.abs(this._scale.x(best.index)-viewX)?p:best);
      if(this._selected!==closest.index){this._selected=closest.index;this._selection();}
    }
    _selection(){
      if(!this._scale)return;
      const p=this._curve.points.find(p=>p.index===this._selected);if(!p)return;
      const line=this.shadowRoot.getElementById("crosshair");line.setAttribute("x1",this._scale.x(p.index));line.setAttribute("x2",this._scale.x(p.index));
      const circle=this.shadowRoot.getElementById("selected");circle.setAttribute("cx",this._scale.x(p.index));circle.setAttribute("cy",this._scale.y(p.mv));
      this.shadowRoot.getElementById("selection").innerHTML=`<span>${this._t("Point ")}${p.index+1} · ${this._fmt(p.seconds,3)}${this._t(" s (")}${this._fmt(p.seconds/60,2)}${this._t(" min)")}</span><strong>${this._fmt(p.mv/1000,3)}${this._t(" V · ")}${this._fmt(p.mv,0)}${this._t(" mV")}</strong>`;
    }
    _controls(){
      if(!this._config||!this.shadowRoot.querySelector("ha-card"))return;
      const button=this._hass?.states?.[this._config.fetch_entity];
      const fetch=this.shadowRoot.querySelector('[data-action="fetch"]');
      fetch.disabled=this._busy||this._phone||!this._hass||!button||button.state==="unavailable";
      fetch.textContent=this._busy?this._t("Reading…"):this._t("Read");
      this.shadowRoot.querySelector('[data-action="csv"]').disabled=!this._curve?.samples.length||this._curve.interval===null;
      const notice=this._phone?{text:this._t("Phone access is enabled. Disable it to read again; the cached curve is still available.")}:this._notice;
      const box=this.shadowRoot.getElementById("notice");box.hidden=!notice;box.textContent=this._t(notice?.text||"");box.classList.toggle("error",!!notice?.error);
    }
    async _fetch(){
      if(this.shadowRoot.querySelector('[data-action="fetch"]').disabled)return;
      this._busy=true;this._notice=null;this._controls();
      try{await this._hass.callService("button","press",{entity_id:this._config.fetch_entity});this._notice={text:this._t("Read request completed. The retrieval time is shown below the graph.")};}
      catch(error){this._notice={text:error?.message||String(error),error:true};}
      finally{this._busy=false;this._controls();}
    }
    _csv(){
      const {samples,interval}=this._data();if(!samples.length||interval===null)return null;
      return "\uFEFF"+this._t("elapsed_seconds,millivolts")+"\r\n"+samples.map((mv,index)=>`${Number((index*interval).toFixed(6))},${mv??""}`).join("\r\n")+"\r\n";
    }
    _download(){
      const csv=this._csv();if(csv===null)return;
      const url=URL.createObjectURL(new Blob([csv],{type:"text/csv;charset=utf-8"}));
      const a=document.createElement("a");a.href=url;a.download=`mc3000-slot-${this._config.slot}-voltage.csv`;a.style.display="none";this.shadowRoot.append(a);a.click();a.remove();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
    }
  }
  if(!customElements.get(TAG))customElements.define(TAG,MC3000CurveCard);
  window.customCards=window.customCards||[];
  if(!window.customCards.some(c=>c.type===TAG))window.customCards.push({type:TAG,name:"MC3000 · Voltage curve",description:"Voltage curve from charger memory, point selection and CSV export",preview:false});
})();

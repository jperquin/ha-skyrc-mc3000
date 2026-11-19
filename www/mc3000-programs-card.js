/* MC3000 profile editor. No network access except Home Assistant service calls. */
(() => {
  "use strict";
  const TAG = "mc3000-programs-card";
  // English source messages are the stable translation keys. User data is never translated.
  const UK = {
  "companion_entity must be a switch entity ID": "companion_entity має бути ідентифікатором сутності switch",
  "status_entities must contain four sensor entity IDs": "status_entities має містити чотири ідентифікатори сутностей sensor",
  "language must be en or uk": "language має бути en або uk",
  "“": "«",
  "”": "»",
  "Li-ion · 4.20 V": "Li-ion · 4,20 В",
  "Li-ion · 4.35 V": "Li-ion · 4,35 В",
  "Charge": "Заряд",
  "Discharge": "Розряд",
  "Cycle": "Цикл",
  "Storage": "Зберігання",
  "Refresh": "Оновлення",
  "Break-in": "Формування",
  "Capacity limit": "Ліміт ємності",
  "mAh": "мА·год",
  "Step 100. 0 disables the limit; Break-in requires the rated capacity.": "Крок 100. 0 — без ліміту; для формування потрібна номінальна ємність.",
  "Charge current": "Струм заряду",
  "A": "А",
  "Choose a current appropriate for this cell.": "Підберіть струм для конкретного акумулятора.",
  "Discharge current": "Струм розряду",
  "Actual current also depends on the charger power limit.": "Фактичний струм також обмежує потужність зарядки.",
  "Charge termination voltage": "Завершення заряду",
  "V": "В",
  "Upper voltage; the target voltage in Storage mode.": "Верхня напруга; для зберігання — цільова.",
  "Discharge termination voltage": "Завершення розряду",
  "Lower discharge cutoff voltage.": "Нижня напруга розряду.",
  "Charge end current": "Кінцевий струм заряду",
  "mA": "мА",
  "No higher than the main current. Use the main current in mA to disable tapering.": "Не більше основного струму. Для вимкнення зниження — основний струм у мА.",
  "Discharge end current": "Кінцевий струм розряду",
  "Cycle count": "Кількість циклів",
  "Used in Cycle mode.": "Застосовується в режимі циклу.",
  "Rest after charge": "Відпочинок після заряду",
  "min": "хв",
  "Rest before the next stage.": "Пауза перед наступним етапом.",
  "Rest after discharge": "Відпочинок після розряду",
  "Voltage drop −ΔV": "Падіння напруги −ΔV",
  "mV": "мВ",
  "For NiMH, NiCd and Eneloop; 0 disables termination.": "Для NiMH, NiCd та Eneloop; 0 — вимкнено.",
  "Trickle current": "Підтримувальний струм",
  "For nickel cells; 0 disables trickle charging.": "Для нікелевих акумуляторів; 0 — вимкнено.",
  "Restart charge below": "Повторний заряд нижче",
  "0 disables restart. Voltage threshold for resuming charge.": "0 — вимкнено. Поріг відновлення заряду.",
  "Temperature protection": "Температурний захист",
  "20–70 °C; 0 disables protection.": "20–70 °C; 0 — вимкнено.",
  "Time limit": "Ліміт часу",
  "0 disables this limit.": "0 — вимкнено.",
  "C → D": "З → Р",
  "C → D → C": "З → Р → З",
  "D → C": "Р → З",
  "D → C → D": "Р → З → Р",
  "Set slot: 1–4 or mode: editor": "Вкажіть slot: 1–4 або mode: editor",
  "editor_path must be a local Home Assistant path": "editor_path має бути локальним шляхом Home Assistant",
  "Ready": "Готовий",
  "Done": "Завершено",
  "Pause": "Пауза",
  "No data": "Немає даних",
  "Unavailable": "Недоступний",
  "Low input voltage": "Низька вхідна напруга",
  "High input voltage": "Висока вхідна напруга",
  "Measurement error": "Помилка вимірювання",
  "Connection lost": "Обрив контакту",
  "Check voltage": "Перевірте напругу",
  "Charger overheating": "Перегрів зарядки",
  "Cell overheating": "Перегрів акумулятора",
  "Short circuit": "Коротке замикання",
  "Reversed polarity": "Зворотна полярність",
  "Check charger": "Перевірте зарядку",
  "Choose a saved program.": "Оберіть збережену програму.",
  "Chemistry": "Хімія",
  "Mode": "Режим",
  " A · ": " А · ",
  " V": " В",
  "Program": "Програма",
  "Slot parameters · ": "Параметри слота ",
  "Saved program": "Збережена програма",
  "Apply to slot ": "Застосувати до слота ",
  "My programs · create and edit": "Мої програми · створити й редагувати",
  "Choose a chemistry": "Оберіть хімію",
  "Slot ": "Слот ",
  "MC3000 · library": "MC3000 · бібліотека",
  "My programs": "Мої програми",
  "Keep all cell parameters in one profile. Save your settings and send them to the slots you choose.": "Один профіль — усі параметри акумулятора. Зберігайте свої налаштування й передавайте їх у потрібні слоти.",
  "＋ New program": "＋ Нова програма",
  "Saved programs": "Збережені програми",
  "SAVED": "ЗБЕРЕЖЕНІ",
  "New program": "Нова програма",
  "Draft": "Чернетка",
  "The library changed in another window. Your draft is still in the form.": "Бібліотека змінилася в іншому вікні. Ваша чернетка збережена у формі.",
  "Load saved version": "Завантажити збережену версію",
  "Save as new": "Зберегти як нову",
  "Basic parameters ": "Основні параметри ",
  "· all fields are required": "· усі поля обов’язкові",
  "Program name": "Назва програми",
  "For example, cell model and operating mode": "Наприклад, модель акумулятора та режим",
  "Up to 60 characters. Program names must be unique.": "До 60 символів. Назви програм мають бути різними.",
  "Cell chemistry": "Хімія акумулятора",
  "Operating mode": "Режим роботи",
  "The initial current is 0.5 A. Voltages are filled in after selecting a chemistry. Set the parameters for your specific cell before saving.": "Початковий струм — 0,5 А. Напруги підставляються після вибору хімії. Перед збереженням задайте параметри саме вашого акумулятора.",
  "Advanced parameters and protection": "Додаткові параметри та захист",
  "Cycle sequence": "Порядок циклу",
  "C — charge, D — discharge.": "З — заряд, Р — розряд.",
  "Saving updates only the program library in Home Assistant.": "Збереження змінює лише бібліотеку програм у Home Assistant.",
  "Save program": "Зберегти програму",
  "Create copy": "Створити копію",
  "Delete": "Видалити",
  "Send to charger": "Передати у зарядку",
  "Choose slots": "Виберіть слоти",
  "Review and apply": "Перевірити й застосувати",
  "No programs yet.": "Ще немає програм.",
  "Copy the parameters from your Android profile into this form.": "Перенесіть параметри зі свого Android-профілю у форму поруч.",
  "Edit program": "Редагування програми",
  "Waiting for update…": "Очікуємо оновлення…",
  "Unsaved changes": "Є незбережені зміни",
  "Saved": "Збережено",
  "Saving…": "Збереження…",
  "Choose a program": "Оберіть програму",
  "Create a program first": "Спочатку створіть програму",
  "Last transmitted: ": "Остання передана: ",
  "Transmitting parameters… Please wait for completion.": "Передавання параметрів… Дочекайтеся завершення.",
  "Apply sends the parameters. Start separately using the slot button.": "Застосування передає параметри. Запуск — окремою кнопкою слота.",
  "Transmitting parameters…": "Передавання параметрів…",
  "The program library is unavailable. Check the MC3000 integration.": "Бібліотека програм недоступна. Перевірте інтеграцію MC3000.",
  "The program library is unavailable.": "Бібліотека програм недоступна.",
  "Phone access is enabled. Disable it to send a program from HA.": "Увімкнено доступ із телефона. Вимкніть його, щоб передати програму з HA.",
  "Save and select a program first.": "Спочатку збережіть та оберіть програму.",
  "Save the program changes first.": "Спочатку збережіть зміни програми.",
  "Choose ready slots for this program.": "Оберіть готові слоти для цієї програми.",
  "Stop the slot first and wait until it is ready.": "Спочатку зупиніть слот і дочекайтеся стану готовності.",
  "Choose a mode": "Оберіть режим",
  "Break-in: C/10, calculated from capacity.": "Формування: C/10, розраховується з ємності.",
  "Break-in: C/5, calculated from capacity.": "Формування: C/5, розраховується з ємності.",
  "0 disables restart; otherwise ": "0 — вимкнено; або ",
  " V.": " В.",
  "Program selected. Parameters have not been sent to the slot yet.": "Програму обрано. Параметри ще не передано у слот.",
  "Voltages updated for the selected chemistry. Review them and the other profile parameters.": "Напруги оновлено для обраної хімії. Перевірте їх та інші параметри свого профілю.",
  " — copy": " — копія",
  "Delete program?": "Видалити програму?",
  "” will be deleted from the Home Assistant library.": "» буде видалено з бібліотеки Home Assistant.",
  "Program deleted from the library.": "Програму видалено з бібліотеки.",
  "Discard unsaved changes?": "Відкинути незбережені зміни?",
  "<p>The current draft has not been saved. Go back, or discard the changes and open another program.</p>": "<p>Поточна чернетка ще не збережена. Поверніться до неї або відкиньте зміни й відкрийте іншу програму.</p>",
  "Discard and continue": "Відкинути й продовжити",
  "Complete the field “": "Заповніть поле «",
  "Check “": "Перевірте «",
  ", step ": ", крок ",
  "Enter a program name.": "Введіть назву програми.",
  "Restart voltage: 0 or ": "Напруга повторного заряду: 0 або ",
  "Temperature protection: 20–70 °C or 0 (disabled).": "Температурний захист: 20–70 °C або 0 (вимкнено).",
  "Load the latest saved version or copy this draft before saving.": "Завантажте актуальну збережену версію або створіть копію чернетки перед збереженням.",
  "Program saved in Home Assistant. Choose slots below to send it to the charger.": "Програму збережено у Home Assistant. Щоб передати її у зарядку, виберіть слоти нижче.",
  "I checked the cell chemistry and parameters in the selected slots.": "Перевірив хімію акумуляторів і параметри в обраних слотах.",
  "Go back": "Повернутися",
  "Apply program?": "Застосувати програму?",
  "View all parameters": "Переглянути всі параметри",
  "Parameters will be sent to the selected slots. The charger will stay stopped; start it separately.": "Параметри буде передано у вибрані слоти. Зарядка залишиться зупиненою; запуск виконується окремо.",
  "Transmit parameters": "Передати параметри",
  "The program changed. Close this dialog and review the current parameters.": "Програма змінилася. Закрийте вікно й перевірте актуальні параметри.",
  "slot ": "слот ",
  "Parameters transmitted: ": "Параметри передано: ",
  ". Use the slot button to start.": ". Для запуску скористайтеся кнопкою слота.",
  "Could not transmit the program.": "Не вдалося передати програму.",
  "MC3000 · My programs": "MC3000 · Мої програми",
  "MC3000 program library, full editor and slot configuration": "Бібліотека програм MC3000, повний редактор і передавання параметрів у слоти"
};
  const EN = new Map(Object.entries(UK).map(([en,uk])=>[uk,en]));
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const copy = (value) => JSON.parse(JSON.stringify(value));
  const CHEM = {
    liion: {name:"Li-ion · 4.20 V", volt:[4.2,3,4.15], charge:[4,4.25], discharge:[2.5,3.65], restart:[3.98,4.18], storage:[3.65,4,3.8], family:"li"},
    life: {name:"LiFePO₄", volt:[3.6,2.9,3.55], charge:[3.4,3.65], discharge:[2,3.15], restart:[3.38,3.58], storage:[3.15,3.4,3.3], family:"li"},
    liion_4_35: {name:"Li-ion · 4.35 V", volt:[4.35,3.3,4.25], charge:[4.1,4.4], discharge:[2.65,3.75], restart:[4.08,4.33], storage:[3.75,4.1,3.9], family:"li"},
    nimh: {name:"NiMH", volt:[1.65,1,1.35], charge:[1.47,1.8], discharge:[0.5,1.1], restart:[1.3,1.45], family:"ni"},
    nicd: {name:"NiCd", volt:[1.65,1,1.35], charge:[1.47,1.8], discharge:[0.5,1.1], restart:[1.3,1.45], family:"ni"},
    eneloop: {name:"Eneloop", volt:[1.65,0.9,1.35], charge:[1.47,1.8], discharge:[0.5,1], restart:[1.3,1.45], family:"ni"},
    nizn: {name:"NiZn", volt:[1.9,1.2,1.6], charge:[1.85,1.95], discharge:[1,1.3], restart:[1.5,1.88], family:"other"},
    ram: {name:"RAM", volt:[1.65,0.9,1.45], charge:[1.4,1.7], discharge:[0.5,1.3], restart:[1.4,1.5], family:"other"},
    batlto: {name:"LTO", volt:[2.85,1.8,2.7], charge:[2.6,2.9], discharge:[1.5,2.25], restart:[2.58,2.83], storage:[2.25,2.6,2.4], family:"li"},
    naion: {name:"Na-ion", volt:[4,2,4.15], charge:[3.2,4.15], discharge:[1.5,3.5], restart:[3.98,4.18], storage:[3.2,4.15,4], family:"li"}
  };
  const MODES = {charge:"Charge", discharge:"Discharge", cycle:"Cycle", storage:"Storage", refresh:"Refresh", breakin:"Break-in"};
  const FIELDS = {
    capacity: ["Capacity limit", "mAh", 0, 50000, 100, "Step 100. 0 disables the limit; Break-in requires the rated capacity."],
    charge_current: ["Charge current", "A", .05, 3, .01, "Choose a current appropriate for this cell."],
    discharge_current: ["Discharge current", "A", .05, 2, .01, "Actual current also depends on the charger power limit."],
    charge_voltage: ["Charge termination voltage", "V", .5, 4.4, .01, "Upper voltage; the target voltage in Storage mode."],
    discharge_voltage: ["Discharge termination voltage", "V", .5, 4, .01, "Lower discharge cutoff voltage."],
    charge_end_current: ["Charge end current", "mA", 0, 3000, 10, "No higher than the main current. Use the main current in mA to disable tapering."],
    discharge_end_current: ["Discharge end current", "mA", 0, 2000, 10, "No higher than the main current. Use the main current in mA to disable tapering."],
    cycle_count: ["Cycle count", "", 1, 99, 1, "Used in Cycle mode."],
    cycle_time: ["Rest after charge", "min", 0, 240, 1, "Rest before the next stage."],
    discharge_time: ["Rest after discharge", "min", 0, 240, 1, "Rest before the next stage."],
    delta_v: ["Voltage drop −ΔV", "mV", 0, 20, 1, "For NiMH, NiCd and Eneloop; 0 disables termination."],
    trickle_current: ["Trickle current", "mA", 0, 300, 10, "For nickel cells; 0 disables trickle charging."],
    maintenance_voltage: ["Restart charge below", "V", 0, 4.4, .01, "0 disables restart. Voltage threshold for resuming charge."],
    protection_temperature: ["Temperature protection", "°C", 0, 70, 1, "20–70 °C; 0 disables protection."],
    protection_time: ["Time limit", "min", 0, 1440, 1, "0 disables this limit."]
  };
  const VOLTS = new Set(["charge_voltage", "discharge_voltage", "maintenance_voltage"]);
  const defaultDraft = () => ({name:"", program:{battery_type:"", operation:"", capacity:"", charge_current:.5, discharge_current:.5, charge_voltage:"", discharge_voltage:"", charge_end_current:100, discharge_end_current:500, cycle_time:0, cycle_count:1, cycle_type:0, delta_v:0, trickle_current:0, maintenance_voltage:0, protection_temperature:45, protection_time:0, discharge_time:0}});
  const REST = {charge:[0,0], refresh:[30,60], storage:[0,0], breakin:[60,60], discharge:[0,0], cycle:[20,10]};
  const CYCLES = ["C → D","C → D → C","D → C","D → C → D"];
  const modesFor = (chem) => {
    const family = CHEM[chem]?.family;
    return family ? ["charge","discharge","cycle","refresh", ...(family === "li" ? ["storage"] : family === "ni" ? ["breakin"] : [])] : [];
  };
  const css = `
    :host{display:block;color:var(--primary-text-color,#e6edf3);font-family:var(--paper-font-body1_-_font-family,inherit);line-height:1.45;container:mc3000 / inline-size}
    *{box-sizing:border-box}ha-card{display:block;background:var(--ha-card-background,var(--card-background-color,#1c2531));border-radius:var(--ha-card-border-radius,16px);border:var(--ha-card-border-width,1px) solid var(--ha-card-border-color,var(--divider-color,#394554));box-shadow:var(--ha-card-box-shadow,none)}
    .wrap{padding:20px}.compact{padding:16px}h2,h3,p{margin:0}h2{font-size:22px;font-weight:650;letter-spacing:-.02em}h3{font-size:17px;font-weight:600}.muted,.hint{color:var(--secondary-text-color,#a4b1be)}.hint{font-size:12px;line-height:1.45;display:block;margin-block-start:5px}.intro{font-size:14px;margin-block-start:5px;max-inline-size:72ch}.head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap}.eyebrow{text-transform:uppercase;letter-spacing:.12em;font-size:10px;font-weight:700;color:var(--secondary-text-color,#a4b1be);margin-block-end:5px}.icon{display:inline-flex;align-items:center;justify-content:center;inline-size:38px;block-size:38px;border-radius:12px;background:var(--secondary-background-color,#263544);color:var(--primary-color,#48a9fa);flex:none}.title-row{display:flex;align-items:center;gap:10px}.title-row h3{font-size:16px}.count{font-size:12px;white-space:nowrap}.library-layout{display:grid;grid-template-columns:minmax(190px,.8fr) minmax(0,2fr);gap:24px;margin-block-start:24px}.library{min-inline-size:0}.library-label{display:flex;justify-content:space-between;gap:8px;margin-block-end:10px;font-size:12px;color:var(--secondary-text-color,#a4b1be)}.profile-list{display:grid;gap:8px;max-block-size:620px;overflow:auto;padding:2px}.profile-item{display:block;text-align:start;width:100%;border-radius:12px;padding:12px;border:1px solid var(--divider-color,#394554);background:transparent}.profile-item[aria-current=true]{border-color:var(--primary-color,#48a9fa);background:var(--secondary-background-color,#263544);box-shadow:inset 3px 0 0 var(--primary-color,#48a9fa)}.profile-item strong{display:block;font-size:14px;overflow-wrap:anywhere}.profile-item small{display:block;color:var(--secondary-text-color,#a4b1be);font-size:12px;margin-block-start:4px}.empty{padding:20px 12px;border:1px dashed var(--divider-color,#394554);border-radius:12px;font-size:13px;color:var(--secondary-text-color,#a4b1be);text-align:center}.editor{min-inline-size:0}.editor-heading{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-block-end:16px}.badge{font-size:11px;border:1px solid var(--divider-color,#394554);border-radius:20px;padding:4px 9px;color:var(--secondary-text-color,#a4b1be)}.badge.dirty{color:var(--warning-color,#e4b95b)}fieldset{margin:0;padding:0;border:0;min-inline-size:0}legend{padding:0;font-size:13px;font-weight:650;margin-block-end:12px}.fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.full{grid-column:1/-1}.field{min-inline-size:0}.field label{display:block;font-size:13px;font-weight:500;margin-block-end:6px}.unit{font-size:12px;font-weight:400;color:var(--secondary-text-color,#a4b1be)}input,select,button{font:inherit;font-size:16px;color:var(--primary-text-color,#e6edf3)}input:not([type=checkbox]),select{display:block;width:100%;min-inline-size:0;min-block-size:48px;border:1px solid var(--input-outlined-idle-border-color,var(--divider-color,#65717d));border-radius:9px;padding:10px 12px;background:var(--input-fill-color,var(--secondary-background-color,#263544));color-scheme:inherit}select{padding-inline-end:8px}input[type=checkbox]{accent-color:var(--primary-color,#48a9fa);inline-size:20px;block-size:20px;flex:none}button,a{touch-action:manipulation}button{cursor:pointer;min-block-size:44px;padding:10px 14px;border:1px solid var(--divider-color,#394554);border-radius:10px;background:transparent;font-size:13px;font-weight:600;line-height:1.35}button:hover:not(:disabled){background:var(--secondary-background-color,#263544)}button.primary{background:var(--primary-color,#48a9fa);border-color:var(--primary-color,#48a9fa);color:var(--text-primary-color,#fff)}button.primary:hover:not(:disabled){filter:brightness(1.08)}button.danger{color:var(--error-color,#ef7979)}button:disabled{opacity:.46;cursor:default}button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:3px solid var(--primary-color,#48a9fa);outline-offset:3px}input:user-invalid,input[aria-invalid=true],select[aria-invalid=true]{border-color:var(--error-color,#ef7979)}.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.save-bar{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap;margin-block-start:20px;padding-block-start:18px;border-block-start:1px solid var(--divider-color,#394554)}.save-bar .hint{margin:0;max-inline-size:34ch}.section{padding-block-start:22px;margin-block-start:22px;border-block-start:1px solid var(--divider-color,#394554)}details{margin-block-start:20px;border:1px solid var(--divider-color,#394554);border-radius:12px;padding:0 14px}summary{cursor:pointer;font-size:14px;font-weight:600;padding-block:15px;min-block-size:48px}details .fields{padding-block:4px 17px}.note{font-size:12px;padding:10px 12px;background:var(--secondary-background-color,#263544);border-radius:9px;margin-block:14px;line-height:1.5}.notice{padding:11px 13px;border-inline-start:3px solid var(--primary-color,#48a9fa);background:var(--secondary-background-color,#263544);border-radius:8px;font-size:13px;margin-block-start:14px;overflow-wrap:anywhere}.notice.error{border-color:var(--error-color,#ef7979)}.notice.warning{border-color:var(--warning-color,#e4b95b)}.notice[hidden],[hidden]{display:none!important}.notice button{margin-block-start:8px}.apply-panel{padding:16px;border-radius:12px;background:var(--secondary-background-color,#263544);margin-block-start:22px}.apply-panel p{font-size:12px;margin-block-start:5px}.slot-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-block:14px}.slot-choice{display:flex;gap:5px;align-items:center;min-block-size:54px;padding:6px;border:1px solid var(--divider-color,#394554);border-radius:9px;font-size:12px}.slot-choice label{cursor:pointer;min-inline-size:0}.slot-choice span{display:block;font-size:10px;color:var(--secondary-text-color,#a4b1be);overflow-wrap:anywhere}.slot-choice:has(input:checked){border-color:var(--primary-color,#48a9fa)}.slot-choice:has(input:disabled){opacity:.5}.apply-panel>.primary,.compact>.primary{width:100%}.profile-summary{display:grid;grid-template-columns:1fr 1fr;gap:12px 8px;margin-block:16px}.metric{min-inline-size:0}.metric small{display:block;font-size:10px;color:var(--secondary-text-color,#a4b1be);text-transform:uppercase;letter-spacing:.05em}.metric strong{font-weight:600;font-size:14px;overflow-wrap:anywhere}.compact .field{margin-block-start:16px}.compact .apply-hint{margin-block:10px;font-size:12px}.manage{display:flex;justify-content:space-between;gap:10px;align-items:center;min-block-size:44px;font-size:12px;text-decoration:none;color:var(--primary-color,#48a9fa);margin-block-start:8px}.manage span:last-child{font-size:20px}.applied{font-size:11px;color:var(--secondary-text-color,#a4b1be);margin-block-start:8px;overflow-wrap:anywhere}dialog{color:var(--primary-text-color,#e6edf3);background:var(--card-background-color,#1c2531);border:1px solid var(--divider-color,#394554);border-radius:18px;inline-size:min(520px,calc(100vw - 28px));max-block-size:calc(100dvh - 40px);padding:24px;overflow:auto;box-shadow:0 20px 80px #0006}dialog::backdrop{background:#0008}dialog h3{font-size:20px;margin-block-end:10px}dialog p{font-size:14px;overflow-wrap:anywhere}dialog .toolbar{justify-content:flex-end;margin-block-start:20px}dialog .review-slots{display:flex;gap:8px;flex-wrap:wrap;margin-block:16px}dialog .review-slots span{padding:6px 12px;border-radius:8px;background:var(--secondary-background-color,#263544);font-size:13px}dialog .review-name{font-size:16px;font-weight:600}.review-table{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px 18px;font-size:12px;margin-block:16px}.review-table dt{color:var(--secondary-text-color,#a4b1be)}.review-table dd{margin:0;text-align:end;overflow-wrap:anywhere}.review-more{font-size:12px}.review-more .review-table{padding-block-end:12px}.review-more summary{font-size:12px}.confirm-cell{display:flex;gap:10px;align-items:flex-start;font-size:13px;margin-block-start:18px}.confirm-cell label{padding-block-start:3px}.busy-label{font-size:12px;color:var(--secondary-text-color,#a4b1be)}
    @container mc3000 (max-width:650px){.library-layout{grid-template-columns:minmax(0,1fr);gap:22px}.profile-list{display:flex;max-block-size:180px;overflow:auto}.profile-item{min-inline-size:160px;max-inline-size:230px;flex:1 0 160px}.wrap{padding:16px}.editor-heading{margin-block-end:14px}.head h2{font-size:20px}}
    @container mc3000 (max-width:390px){.fields{grid-template-columns:minmax(0,1fr)}.slot-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.save-bar .primary{width:100%}.save-bar .hint{max-inline-size:none}.head{gap:12px}.head>.primary{width:100%}}
    @media (prefers-reduced-motion:no-preference){button{transition:background .15s ease,border-color .15s ease}}@media (forced-colors:active){.profile-item[aria-current=true]{border:3px solid Highlight}.badge{border-color:CanvasText}}
  `;

  class MC3000ProgramsCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({mode:"open"});
      this._draft = defaultDraft();
      this._dirty = false;
      this._editingId = null;
      this._slots = new Set();
      this._message = null;
      this._lastProfiles = null;
      this._busy = false;
      this._revision = 0;
      this.shadowRoot.addEventListener("click", (e) => this._click(e));
      this.shadowRoot.addEventListener("input", (e) => this._input(e));
      this.shadowRoot.addEventListener("change", (e) => this._change(e));
      this.shadowRoot.addEventListener("submit", (e) => { e.preventDefault(); if (e.target.id === "profile-form") this._save(); });
    }
    setConfig(config) {
      if (config.language !== undefined && !["en","uk"].includes(config.language)) throw new Error(this._t("language must be en or uk"));
      if (config.mode !== "editor" && ![1,2,3,4].includes(Number(config.slot))) throw new Error(this._t("Set slot: 1–4 or mode: editor"));
      this._config = {entity:"sensor.skyrc_mc3000_programs", editor_path:"/dashboard-mc3000/programs", companion_entity:"switch.skyrc_mc3000_companion_app_mode", status_entities:[1,2,3,4].map(slot=>`sensor.skyrc_mc3000_slot_${slot}_status`), ...config};
      if (typeof this._config.companion_entity !== "string" || !/^switch\.[a-z0-9_]+$/.test(this._config.companion_entity)) throw new Error(this._t("companion_entity must be a switch entity ID"));
      if (!Array.isArray(this._config.status_entities) || this._config.status_entities.length !== 4 || this._config.status_entities.some(entity=>typeof entity !== "string" || !/^sensor\.[a-z0-9_]+$/.test(entity))) throw new Error(this._t("status_entities must contain four sensor entity IDs"));
      if (!this._config.editor_path.startsWith("/") || this._config.editor_path.startsWith("//")) throw new Error(this._t("editor_path must be a local Home Assistant path"));
      this._render();
    }
    set hass(hass) {
      const languageChanged = this._language !== (String(this._config?.language ?? hass?.language ?? "en").toLowerCase().startsWith("uk") ? "uk" : "en");
      this._hass = hass;
      if (!this._config) return;
      const profiles = JSON.stringify(this._profiles);
      const changed = this._lastProfiles !== null && profiles !== this._lastProfiles;
      if (changed && !this._dirty && !this._pendingSave && !this._busy && this._editingId) {
        if (this.shadowRoot.getElementById("dialog")?.open) this._reloadOnClose = true;
        else this._load(this._editingId, true);
      }
      if (changed && this._dirty && !this._pendingSave) this._conflict = true;
      if (!this._dirty || !changed && !this._conflict) this._revision = this._attrs.revision || 0;
      this._lastProfiles = profiles;
      if (!this._editor && this._slotSelection && this._attrs.selected?.[String(this._config.slot)] === this._slotSelection) this._slotSelection = undefined;
      if (this._pendingSave) {
        const p = this._profiles.find((p) => p.name === this._pendingSave.name && JSON.stringify(p.program) === JSON.stringify(this._pendingSave.program));
        // Backends may serialize keys in a different order.
        const matched = p || this._profiles.find((p) => p.name === this._pendingSave.name && Object.keys(this._pendingSave.program).every((k) => p.program[k] === this._pendingSave.program[k]));
        if (matched) { this._editingId = matched.id; this._dirty = false; this._conflict = false; this._pendingSave = null; this._revision = this._attrs.revision || 0; }
      }
      if (languageChanged) this._renderLanguage();
      else if (!this.shadowRoot.querySelector("ha-card")) this._render();
      else this._refresh();
    }
    get _language() { return String(this._config?.language ?? this._hass?.language ?? "en").toLowerCase().startsWith("uk") ? "uk" : "en"; }
    get _locale() { return this._language === "uk" ? "uk-UA" : "en-US"; }
    _t(message) { const key = EN.get(message) ?? message; return this._language === "uk" ? UK[key] ?? key : key; }
    _fmt(value, digits=2) { return Number.isFinite(Number(value)) ? Number(value).toLocaleString(this._locale, {maximumFractionDigits:digits}) : "—"; }
    get hass() { return this._hass; }
    get _editor() { return this._config?.mode === "editor"; }
    get _attrs() { return this._hass?.states?.[this._config?.entity]?.attributes || {}; }
    get _profiles() { return Array.isArray(this._attrs.profiles) ? this._attrs.profiles : []; }
    get _online() { const s = this._hass?.states?.[this._config?.entity]?.state; return s !== undefined && !["unknown","unavailable"].includes(s); }
    get _phone() { return this._hass?.states?.[this._config?.companion_entity]?.state === "on"; }
    get _profile() { const id = this._editor ? this._editingId : this._slotSelection ?? this._attrs.selected?.[String(this._config.slot)]; return this._profiles.find((p) => p.id === id); }
    getCardSize() { return this._editor ? 14 : 5; }
    getGridOptions() { return {columns:12, rows:"auto", min_columns:this._editor ? 6 : 3}; }
    static getStubConfig() { return {mode:"editor"}; }
    _state(slot) { return this._hass?.states?.[this._config?.status_entities?.[slot-1]]?.state || "unavailable"; }
    _ready(slot) { return ["standby","done","Standby","Done","0","4"].includes(this._state(slot)); }
    _status(slot) { return ({standby:this._t("Ready"),done:this._t("Done"),charge:this._t("Charge"),discharge:this._t("Discharge"),pause:this._t("Pause"),unknown:this._t("No data"),unavailable:this._t("Unavailable"),input_voltage_low:this._t("Low input voltage"),input_voltage_high:this._t("High input voltage"),mcp3424_1_error:this._t("Measurement error"),mcp3424_2_error:this._t("Measurement error"),connection_break:this._t("Connection lost"),check_voltage:this._t("Check voltage"),capacity_protection:this._t("Capacity limit"),time_protection:this._t("Time limit"),temp_high:this._t("Charger overheating"),battery_temp_high:this._t("Cell overheating"),battery_short_circuit:this._t("Short circuit"),reverse_polarity:this._t("Reversed polarity")})[this._state(slot)] || this._t("Check charger"); }
    _options(values, selected, placeholder) { return `${placeholder ? `<option value="">${esc(placeholder)}</option>` : ""}${values.map(([v,n]) => `<option value="${esc(v)}"${String(v) === String(selected) ? " selected" : ""}>${esc(n)}</option>`).join("")}`; }
    _setOptions(el, values, selected, placeholder) {
      const signature = JSON.stringify([values,placeholder]);
      if (el.dataset.options !== signature) { el.innerHTML = this._options(values,selected,placeholder); el.dataset.options = signature; }
      if (el.value !== String(selected ?? "")) el.value = String(selected ?? "");
    }
    _field(key) {
      const [sourceLabel, sourceUnit, min, max, step, sourceHint] = FIELDS[key];
      const [label,unit,hint] = [sourceLabel,sourceUnit,sourceHint].map(text=>this._t(text));
      const value = this._draft.program[key];
      return `<div class="field"><label for="f-${key}">${label}${unit ? ` <span class="unit">· ${unit}</span>` : ""}</label><input id="f-${key}" name="${key}" type="number" inputmode="${step < 1 ? "decimal" : "numeric"}" min="${min}" max="${max}" step="${step}" value="${esc(value)}" required aria-describedby="h-${key}"><span class="hint" id="h-${key}">${hint}</span></div>`;
    }
    _summary(profile) {
      if (!profile) return `<p class="muted apply-hint">${this._t("Choose a saved program.")}</p>`;
      const p = profile.program;
      return `<div class="profile-summary"><div class="metric"><small>${this._t("Chemistry")}</small><strong>${esc(this._t(CHEM[p.battery_type]?.name || p.battery_type))}</strong></div><div class="metric"><small>${this._t("Mode")}</small><strong>${esc(this._t(MODES[p.operation] || p.operation))}</strong></div><div class="metric"><small>${this._t("Charge")}</small><strong>${this._fmt(p.charge_current)}${this._t(" A · ")}${this._fmt(p.charge_voltage/1000,3)}${this._t(" V")}</strong></div><div class="metric"><small>${this._t("Discharge")}</small><strong>${this._fmt(p.discharge_current)}${this._t(" A · ")}${this._fmt(p.discharge_voltage/1000,3)}${this._t(" V")}</strong></div></div>`;
    }
    _renderLanguage() {
      // Keep the draft and selection when HA changes language. An unsubmitted
      // confirmation is closed so it can be reviewed in the new language.
      const active = this.shadowRoot.activeElement;
      const focusId = active?.id;
      const selection = active?.selectionStart === undefined ? null : [active.selectionStart,active.selectionEnd];
      const advanced = this.shadowRoot.getElementById("advanced")?.open;
      this._message = null;
      this._render();
      const details = this.shadowRoot.getElementById("advanced"); if (details) details.open = !!advanced;
      const target = focusId ? this.shadowRoot.getElementById(focusId) : null;
      target?.focus({preventScroll:true});
      if (selection && target?.type === "text") target.setSelectionRange(...selection);
    }
    _render() {
      if (!this._config) return;
      const editor = this._editor;
      this.shadowRoot.innerHTML = `<style>${css}</style><ha-card lang="${this._language}"><div class="${editor ? "wrap" : "compact"}">${editor ? this._editorHTML() : this._slotHTML()}<div id="notice" class="notice" role="status" aria-live="polite" hidden></div></div></ha-card><dialog id="dialog" aria-labelledby="dialog-title"></dialog>`;
      this._refresh();
    }
    _slotHTML() {
      return `<div class="title-row"><span class="icon"><ha-icon icon="mdi:playlist-edit"></ha-icon></span><div><div class="eyebrow">${this._t("Program")}</div><h3>${this._t("Slot parameters · ")}${Number(this._config.slot)}</h3></div></div><div class="field"><label for="slot-profile">${this._t("Saved program")}</label><select id="slot-profile" name="slot-profile"></select></div><div id="slot-summary"></div><button type="button" class="primary" data-action="apply">${this._t("Apply to slot ")}${Number(this._config.slot)}</button><p class="muted apply-hint" id="apply-hint"></p><p class="applied" id="applied"></p><a class="manage" href="${esc(this._config.editor_path)}"><span>${this._t("My programs · create and edit")}</span><span aria-hidden="true">↗</span></a>`;
    }
    _editorHTML() {
      const d = this._draft;
      return `<header class="head"><div><div class="eyebrow">${this._t("MC3000 · library")}</div><h2>${this._t("My programs")}</h2><p class="intro muted">${this._t("Keep all cell parameters in one profile. Save your settings and send them to the slots you choose.")}</p></div><button type="button" class="primary" data-action="new">${this._t("＋ New program")}</button></header><div class="library-layout"><aside class="library" aria-label="${this._t("Saved programs")}"><div class="library-label"><span>${this._t("SAVED")}</span><span id="profile-count"></span></div><div class="profile-list" id="profile-list"></div></aside><section class="editor"><div class="editor-heading"><h3 id="editor-title">${this._t("New program")}</h3><span class="badge" id="dirty-badge">${this._t("Draft")}</span></div><div id="conflict" class="notice warning" hidden><p>${this._t("The library changed in another window. Your draft is still in the form.")}</p><button type="button" data-action="reload">${this._t("Load saved version")}</button><button type="button" data-action="copy">${this._t("Save as new")}</button></div><form id="profile-form" aria-labelledby="editor-title" novalidate><fieldset><legend>${this._t("Basic parameters ")}<span class="unit">${this._t("· all fields are required")}</span></legend><div class="fields"><div class="field full"><label for="f-name">${this._t("Program name")}</label><input id="f-name" name="name" type="text" maxlength="60" required value="${esc(d.name)}" placeholder="${this._t("For example, cell model and operating mode")}" autocomplete="off" aria-describedby="name-help"><span class="hint" id="name-help">${this._t("Up to 60 characters. Program names must be unique.")}</span></div><div class="field"><label for="f-battery_type">${this._t("Cell chemistry")}</label><select id="f-battery_type" name="battery_type" required>${this._options(Object.entries(CHEM).map(([k,v])=>[k,this._t(v.name)]),d.program.battery_type,this._t("Choose a chemistry"))}</select></div><div class="field"><label for="f-operation">${this._t("Operating mode")}</label><select id="f-operation" name="operation" required></select></div>${["capacity","charge_current","discharge_current","charge_voltage","discharge_voltage"].map(k=>this._field(k)).join("")}</div></fieldset><p class="note">${this._t("The initial current is 0.5 A. Voltages are filled in after selecting a chemistry. Set the parameters for your specific cell before saving.")}</p><details id="advanced"><summary>${this._t("Advanced parameters and protection")}</summary><div class="fields">${["charge_end_current","discharge_end_current","cycle_count"].map(k=>this._field(k)).join("")}<div class="field"><label for="f-cycle_type">${this._t("Cycle sequence")}</label><select id="f-cycle_type" name="cycle_type" required></select><span class="hint">${this._t("C — charge, D — discharge.")}</span></div>${["cycle_time","discharge_time","delta_v","trickle_current","maintenance_voltage","protection_temperature","protection_time"].map(k=>this._field(k)).join("")}</div></details><div class="save-bar"><span class="hint">${this._t("Saving updates only the program library in Home Assistant.")}</span><button type="submit" class="primary" id="save">${this._t("Save program")}</button></div></form><div class="toolbar" style="margin-block-start:12px"><button type="button" data-action="copy" id="copy">${this._t("Create copy")}</button><button type="button" data-action="delete" id="delete" class="danger">${this._t("Delete")}</button></div><section class="apply-panel" aria-labelledby="apply-title"><h3 id="apply-title">${this._t("Send to charger")}</h3><p class="muted" id="apply-hint"></p><fieldset><legend style="margin-block-start:14px;margin-block-end:0">${this._t("Choose slots")}</legend><div class="slot-grid" id="slot-grid">${[1,2,3,4].map(n=>`<div class="slot-choice"><input id="target-${n}" name="target-${n}" type="checkbox" data-slot="${n}"><label for="target-${n}">${this._t("Slot ")}${n}<span id="status-${n}"></span></label></div>`).join("")}</div></fieldset><button type="button" class="primary" data-action="apply">${this._t("Review and apply")}</button></section></section></div>`;
    }
    _refresh() {
      if (!this.shadowRoot.querySelector("ha-card")) return;
      const root = this.shadowRoot;
      if (this._editor) {
        const list = root.getElementById("profile-list");
        const listHTML = this._profiles.map(p=>`<button type="button" class="profile-item" data-profile="${esc(p.id)}" aria-current="${p.id === this._editingId}"><strong>${esc(p.name)}</strong><small>${esc(this._t(CHEM[p.program.battery_type]?.name || p.program.battery_type))} · ${esc(this._t(MODES[p.program.operation] || p.program.operation))}</small></button>`).join("") || `<div class="empty">${this._t("No programs yet.")}<br>${this._t("Copy the parameters from your Android profile into this form.")}</div>`;
        if (list.innerHTML !== listHTML) list.innerHTML = listHTML;
        root.getElementById("profile-count").textContent = `${this._profiles.length} / 100`;
        root.getElementById("editor-title").textContent = this._editingId ? this._t("Edit program") : this._t("New program");
        const badge = root.getElementById("dirty-badge");
        badge.textContent = this._pendingSave ? this._t("Waiting for update…") : this._dirty ? this._t("Unsaved changes") : this._editingId ? this._t("Saved") : this._t("Draft");
        badge.classList.toggle("dirty", this._dirty);
        root.getElementById("conflict").hidden = !this._conflict;
        root.getElementById("save").disabled = this._busy || !!this._pendingSave || !this._online;
        root.getElementById("save").textContent = this._busyService === "save_profile" ? this._t("Saving…") : this._t("Save program");
        root.getElementById("delete").disabled = !this._profile || this._busy;
        root.getElementById("copy").disabled = this._busy;
        for (const input of root.querySelectorAll("#profile-form input,#profile-form select")) input.disabled = this._busy || !!this._pendingSave;
        this._updateConstraints();
        for (const n of [1,2,3,4]) {
          const el = root.getElementById(`target-${n}`);
          const unavailable = !this._ready(n) || this._phone || !this._online;
          el.disabled = unavailable || this._busy;
          if (unavailable) this._slots.delete(n);
          el.checked = this._slots.has(n);
          root.getElementById(`status-${n}`).textContent = this._status(n);
        }
      } else {
        const select = root.getElementById("slot-profile");
        const selected = this._profile?.id || "";
        this._setOptions(select,this._profiles.map(p=>[p.id,p.name]),selected,this._profiles.length ? this._t("Choose a program") : this._t("Create a program first"));
        select.disabled = this._busy || !this._online;
        root.getElementById("slot-summary").innerHTML = this._summary(this._profile);
        const applied = this._attrs.applied?.[String(this._config.slot)];
        root.getElementById("applied").textContent = applied ? `${this._t("Last transmitted: ")}${applied}` : "";
      }
      const targets = this._editor ? [...this._slots] : [Number(this._config.slot)];
      const blocked = this._blockReason(targets);
      const applying = this._busyService === "apply_profile";
      root.getElementById("apply-hint").textContent = applying ? this._t("Transmitting parameters… Please wait for completion.") : blocked || this._t("Apply sends the parameters. Start separately using the slot button.");
      const applyButton = root.querySelector('[data-action="apply"]');
      applyButton.disabled = !!blocked || this._busy;
      applyButton.textContent = applying ? this._t("Transmitting parameters…") : this._editor ? this._t("Review and apply") : `${this._t("Apply to slot ")}${Number(this._config.slot)}`;
      const dialogConfirm = root.getElementById("dialog-confirm");
      if (dialogConfirm) {
        dialogConfirm.textContent = applying ? this._t("Transmitting parameters…") : dialogConfirm.dataset.label;
        dialogConfirm.setAttribute("aria-busy",String(applying));
      }
      for (const b of root.querySelectorAll('[data-action="new"],.profile-item')) b.disabled = this._busy;
      const notice = root.getElementById("notice");
      const msg = !this._online ? {text:this._t("The program library is unavailable. Check the MC3000 integration."),error:true} : this._message;
      notice.hidden = !msg;
      notice.className = `notice${msg?.error ? " error" : ""}`;
      notice.textContent = this._t(msg?.text || "");
    }
    _blockReason(targets) {
      if (!this._online) return this._t("The program library is unavailable.");
      if (this._phone) return this._t("Phone access is enabled. Disable it to send a program from HA.");
      if (!this._profile) return this._t("Save and select a program first.");
      if (this._editor && (this._dirty || this._pendingSave)) return this._t("Save the program changes first.");
      if (!targets.length) return this._t("Choose ready slots for this program.");
      if (targets.some(n=>!this._ready(n))) return this._t("Stop the slot first and wait until it is ready.");
      return "";
    }
    _updateConstraints() {
      const p = this._draft.program;
      const chem = CHEM[p.battery_type];
      const root = this.shadowRoot;
      const op = root.getElementById("f-operation");
      this._setOptions(op,modesFor(p.battery_type).map(k=>[k,this._t(MODES[k])]),p.operation,this._t("Choose a mode"));
      const cycle = root.getElementById("f-cycle_type");
      const cycles = (p.operation === "breakin" ? [this._t("C → D → C"),this._t("D → C → D")] : CYCLES).map((label,n)=>[n,this._t(label)]);
      this._setOptions(cycle,cycles,p.cycle_type);
      const breakin = p.operation === "breakin";
      const nickel = chem?.family === "ni" && ["charge","refresh","cycle"].includes(p.operation);
      root.getElementById("f-capacity").min = breakin ? 100 : 0;
      for (const key of ["charge_current","discharge_current"]) {
        const el = root.getElementById(`f-${key}`); el.readOnly = breakin; el.min = breakin ? .01 : .05;
      }
      for (const key of ["delta_v","trickle_current"]) { const el = root.getElementById(`f-${key}`); el.readOnly = !nickel; }
      root.getElementById("f-protection_time").readOnly = breakin;
      root.getElementById("h-charge_current").textContent = breakin ? this._t("Break-in: C/10, calculated from capacity.") : this._t(FIELDS.charge_current[5]);
      root.getElementById("h-discharge_current").textContent = breakin ? this._t("Break-in: C/5, calculated from capacity.") : this._t(FIELDS.discharge_current[5]);
      for (const [end,main] of [["charge_end_current","charge_current"],["discharge_end_current","discharge_current"]]) {
        const el = root.getElementById(`f-${end}`); el.max = Math.round(Number(p[main])*1000); el.min = ["refresh","cycle"].includes(p.operation) || p.battery_type === "naion" ? 10 : 0;
      }
      if (chem) {
        const charge = root.getElementById("f-charge_voltage");
        const range = p.operation === "storage" ? chem.storage : chem.charge;
        charge.min = range[0]; charge.max = range[1];
        const discharge = root.getElementById("f-discharge_voltage"); discharge.min = chem.discharge[0]; discharge.max = chem.discharge[1];
        root.getElementById("f-maintenance_voltage").max = chem.restart[1];
        root.getElementById("h-maintenance_voltage").textContent = `${this._t("0 disables restart; otherwise ")}${this._fmt(chem.restart[0])}–${this._fmt(chem.restart[1])}${this._t(" V.")}`;
      }
    }
    _input(e) {
      const el = e.target;
      if (!el.closest("#profile-form")) return;
      el.setCustomValidity?.(""); el.removeAttribute("aria-invalid");
      if (el.name === "name") this._draft.name = el.value;
      else if (el.name in this._draft.program) this._draft.program[el.name] = el.value;
      this._dirty = true;
      this._message = null;
      if (this._draft.program.operation === "breakin" && el.name === "capacity") this._derivedBreakin();
      // Update labels and buttons without replacing the form or losing input focus.
      this._refresh();
    }
    async _change(e) {
      const el = e.target;
      if (el.id === "slot-profile") {
        if (!el.value) { this._slotSelection = ""; this._refresh(); return; }
        const before = this._slotSelection;
        this._slotSelection = el.value;
        await this._service("select_profile", {slot:Number(this._config.slot),profile_id:el.value}, this._t("Program selected. Parameters have not been sent to the slot yet."), ()=>{ this._slotSelection = before; });
      } else if (el.dataset.slot) {
        const n = Number(el.dataset.slot); if (el.checked) this._slots.add(n); else this._slots.delete(n); this._refresh();
      } else if (el.name === "battery_type") {
        const chem = CHEM[el.value];
        if (chem) {
          ["charge_voltage","discharge_voltage","maintenance_voltage"].forEach((key,i)=>{ this._draft.program[key] = chem.volt[i]; this.shadowRoot.getElementById(`f-${key}`).value = chem.volt[i]; });
          if (!modesFor(el.value).includes(this._draft.program.operation)) this._draft.program.operation = "";
          if (chem.family === "ni") this._setDraftValue("delta_v",3);
          this._normalizeInactive();
          this._message = {text:this._t("Voltages updated for the selected chemistry. Review them and the other profile parameters.")};
        }
        this._refresh();
      } else if (el.name === "operation") {
        if (el.value === "breakin" && Number(this._draft.program.cycle_type) > 1) { this._draft.program.cycle_type = 0; }
        const p = this._draft.program;
        const chem = CHEM[p.battery_type];
        if (chem) this._setDraftValue("charge_voltage", p.operation === "storage" ? chem.storage[2] : chem.volt[0]);
        if (REST[p.operation]) ["cycle_time","discharge_time"].forEach((key,i)=>this._setDraftValue(key,REST[p.operation][i]));
        if (p.operation === "breakin") this._derivedBreakin();
        if (chem?.family === "ni" && ["charge","refresh","cycle"].includes(p.operation) && !Number(p.delta_v)) this._setDraftValue("delta_v",3);
        this._normalizeInactive();
        this._refresh();
      }
    }
    _setDraftValue(key,value) { this._draft.program[key] = value; const input = this.shadowRoot.getElementById(`f-${key}`); if (input) input.value = value; }
    _derivedBreakin() {
      const capacity = Number(this._draft.program.capacity);
      if (!Number.isFinite(capacity) || capacity < 100) return;
      for (const [main,end,divisor,max] of [["charge_current","charge_end_current",10000,3],["discharge_current","discharge_end_current",5000,2]]) {
        const current = Math.min(capacity/divisor,max);
        this._setDraftValue(main,current);
        if (Number(this._draft.program[end]) > current*1000) this._setDraftValue(end,Math.round(current*1000));
      }
    }
    _normalizeInactive() {
      const p = this._draft.program;
      if (CHEM[p.battery_type]?.family !== "ni" || !["charge","refresh","cycle"].includes(p.operation)) ["delta_v","trickle_current"].forEach(k=>this._setDraftValue(k,0));
      if (p.operation === "breakin") this._setDraftValue("protection_time",0);
    }
    async _click(e) {
      const b = e.target.closest("button");
      if (!b || b.disabled) return;
      if (b.dataset.profile) { this._navigate(()=>this._load(b.dataset.profile)); return; }
      const action = b.dataset.action;
      if (action === "new") this._navigate(()=>this._load(null));
      else if (action === "reload") this._navigate(()=>this._load(this._editingId));
      else if (action === "copy") {
        this._editingId = null; this._draft.name = this._draft.name ? `${this._draft.name.slice(0,51)}${this._t(" — copy")}` : "";
        this._dirty = true; this._conflict = false; this._revision = this._attrs.revision || 0; this._message = null; this._render(); this.shadowRoot.getElementById("f-name").focus();
      } else if (action === "delete") {
        const p = this._profile; if (!p) return;
        this._dialog(this._t("Delete program?"), `<p>${this._t("“")}${esc(p.name)}${this._t("” will be deleted from the Home Assistant library.")}</p>`, this._t("Delete"), async()=>{
          if (await this._service("delete_profile", {profile_id:p.id}, this._t("Program deleted from the library."))) this._load(null, true);
        }, true);
      } else if (action === "apply") this._review();
    }
    _load(id, keepMessage=false) {
      const p = this._profiles.find(p=>p.id === id);
      this._editingId = p?.id || null;
      this._draft = p ? {name:p.name, program:copy(p.program)} : defaultDraft();
      if (p) for (const k of VOLTS) this._draft.program[k] = p.program[k]/1000;
      this._dirty = false; this._conflict = false; this._pendingSave = null; this._revision = this._attrs.revision || 0;
      if (!keepMessage) this._message = null;
      this._render();
    }
    _navigate(fn) {
      if (!this._dirty) { fn(); return; }
      this._dialog(this._t("Discard unsaved changes?"), this._t("<p>The current draft has not been saved. Go back, or discard the changes and open another program.</p>"), this._t("Discard and continue"), fn);
    }
    _invalid(el, message) {
      el.setCustomValidity(message); el.setAttribute("aria-invalid","true");
      const details = el.closest("details"); if (details) details.open = true;
      el.reportValidity(); el.focus();
      this._message = {text:message,error:true}; this._refresh();
    }
    async _save() {
      if (this._busy || this._pendingSave) return;
      const form = this.shadowRoot.getElementById("profile-form");
      for (const el of form.querySelectorAll("input,select")) {
        el.setCustomValidity(""); el.removeAttribute("aria-invalid");
        if (!el.validity.valid) {
          const label = form.querySelector(`label[for="${el.id}"]`)?.textContent || el.name;
          this._invalid(el, el.validity.valueMissing ? `${this._t("Complete the field “")}${label.trim()}${this._t("”")}.` : `${this._t("Check “")}${label.trim()}${this._t("”")}: ${el.min || ""}–${el.max || ""}${this._t(", step ")}${el.step || "1"}.`); return;
        }
      }
      const name = this._draft.name.trim();
      if (!name) { this._invalid(form.elements.name,this._t("Enter a program name.")); return; }
      const p = this._draft.program;
      const chem = CHEM[p.battery_type];
      const restart = Number(p.maintenance_voltage);
      if (restart !== 0 && restart < chem.restart[0]) { this._invalid(form.elements.maintenance_voltage,`${this._t("Restart voltage: 0 or ")}${this._fmt(chem.restart[0])}–${this._fmt(chem.restart[1])}${this._t(" V.")}`); return; }
      if (Number(p.protection_temperature) > 0 && Number(p.protection_temperature) < 20) { this._invalid(form.elements.protection_temperature,this._t("Temperature protection: 20–70 °C or 0 (disabled).")); return; }
      if (this._conflict) { this._message = {text:this._t("Load the latest saved version or copy this draft before saving."),error:true}; this._refresh(); return; }
      const program = {};
      for (const [key,value] of Object.entries(this._draft.program)) program[key] = ["battery_type","operation"].includes(key) ? value : VOLTS.has(key) ? Math.round(Number(value)*1000) : Number(value);
      const payload = {name,program,revision:this._revision};
      if (this._editingId) payload.profile_id = this._editingId;
      this._pendingSave = {name,program};
      const ok = await this._service("save_profile", payload, this._t("Program saved in Home Assistant. Choose slots below to send it to the charger."), ()=>{this._pendingSave=null;});
      if (ok) { this.hass = this._hass; this._refresh(); }
    }
    async _service(service, data, success, rollback) {
      if (this._busy) return false;
      this._busy = true; this._busyService = service; this._message = null; this._refresh();
      try { await this._hass.callService("skyrc_mc3000", service, data); this._message = {text:typeof success === "function" ? success() : this._t(success)}; return true; }
      catch (err) { rollback?.(); this._message = {text:err?.message || String(err),error:true}; return false; }
      finally { this._busy = false; this._busyService = null; this._refresh(); }
    }
    _dialog(title, body, confirmLabel, action, danger=false, requireCheck=false) {
      const dialog = this.shadowRoot.getElementById("dialog");
      if (dialog.open) dialog.close();
      dialog.onclose = ()=>{ if (this._reloadOnClose) { this._reloadOnClose=false; if (!this._dirty) this._load(this._editingId,true); } };
      dialog.innerHTML = `<h3 id="dialog-title">${esc(title)}</h3>${body}${requireCheck ? `<div class="confirm-cell"><input type="checkbox" id="confirm-cells"><label for="confirm-cells">${this._t("I checked the cell chemistry and parameters in the selected slots.")}</label></div>` : ""}<div id="dialog-error" class="notice error" role="alert" hidden></div><div class="toolbar"><button type="button" id="dialog-cancel">${this._t("Go back")}</button><button type="button" id="dialog-confirm" class="${danger ? "danger" : "primary"}"${requireCheck ? " disabled" : ""}>${esc(confirmLabel)}</button></div>`;
      const confirm = dialog.querySelector("#dialog-confirm");
      confirm.dataset.label = confirmLabel;
      dialog.querySelector("#dialog-cancel").onclick = ()=>dialog.close();
      if (requireCheck) dialog.querySelector("#confirm-cells").onchange = (e)=>{confirm.disabled = !e.target.checked;};
      confirm.onclick = async()=>{
        if (confirm.disabled) return;
        confirm.disabled = true;
        try { await action(); dialog.close(); }
        catch (err) { const box = dialog.querySelector("#dialog-error"); box.hidden=false; box.textContent=err?.message || String(err); confirm.disabled=false; }
      };
      dialog.showModal();
      dialog.querySelector("#dialog-cancel").focus();
    }
    _review() {
      const slots = this._editor ? [...this._slots].sort() : [Number(this._config.slot)];
      const reason = this._blockReason(slots);
      if (reason) { this._message = {text:reason,error:true}; this._refresh(); return; }
      const profile = copy(this._profile);
      const p = profile.program;
      const full = Object.keys(FIELDS).map(k=>`<dt>${this._t(FIELDS[k][0])}</dt><dd>${this._fmt(VOLTS.has(k) ? p[k]/1000 : p[k],3)} ${this._t(FIELDS[k][1])}</dd>`).join("");
      this._dialog(this._t("Apply program?"), `<p class="review-name">${esc(profile.name)}</p><div class="review-slots">${slots.map(n=>`<span>${this._t("Slot ")}${n}</span>`).join("")}</div>${this._summary(profile)}<details class="review-more"><summary>${this._t("View all parameters")}</summary><dl class="review-table">${full}<dt>${this._t("Cycle sequence")}</dt><dd>${esc(p.operation === "breakin" ? [this._t("C → D → C"),this._t("D → C → D")][p.cycle_type] : this._t(CYCLES[p.cycle_type]))}</dd></dl></details><p class="note">${this._t("Parameters will be sent to the selected slots. The charger will stay stopped; start it separately.")}</p>`, this._t("Transmit parameters"), async()=>{
        const current = this._profiles.find(p=>p.id === profile.id);
        if (!current || JSON.stringify(current.program) !== JSON.stringify(profile.program)) throw new Error(this._t("The program changed. Close this dialog and review the current parameters."));
        const blocked = this._blockReason(slots); if (blocked) throw new Error(blocked);
        const ok = await this._service("apply_profile", {slots,profile_id:profile.id}, () => `${this._t("Parameters transmitted: ")}${slots.map(n=>`${this._t("slot ")}${n}`).join(", ")}${this._t(". Use the slot button to start.")}`);
        if (!ok) throw new Error(this._message?.text || this._t("Could not transmit the program."));
      }, false, true);
    }
  }
  if (!customElements.get(TAG)) customElements.define(TAG, MC3000ProgramsCard);
  window.customCards = window.customCards || [];
  if (!window.customCards.some(c=>c.type===TAG)) window.customCards.push({type:TAG,name:"MC3000 · My programs",description:"MC3000 program library, full editor and slot configuration",preview:false});
})();

const state={month:new Date().toISOString().slice(0,7),categories:[],transactions:[]};
const money=new Intl.NumberFormat("de-DE",{style:"currency",currency:"EUR"});
const qs=s=>document.querySelector(s);
const qsa=s=>[...document.querySelectorAll(s)];

async function api(path,options={}){const res=await fetch(path,options);const data=await res.json().catch(()=>({}));if(!res.ok)throw new Error(data.error||"Fehler bei der Anfrage");return data}
function toast(message){const el=qs("#toast");el.textContent=message;el.classList.add("show");setTimeout(()=>el.classList.remove("show"),2600)}
function escapeHtml(value=""){return value.replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[ch]))}
function formatDate(value){return new Intl.DateTimeFormat("de-DE").format(new Date(value+"T12:00:00"))}

async function loadCategories(){
  state.categories=await api("/api/categories");
  const options=state.categories.map(c=>`<option value="${escapeHtml(c.name)}">${escapeHtml(c.name)}</option>`).join("");
  qs("#category-filter").insertAdjacentHTML("beforeend",options);
  qs('#rule-form select[name="category"]').innerHTML=options;
}

async function loadDashboard(){
  const data=await api(`/api/dashboard?month=${state.month}`);
  qs("#income").textContent=money.format(data.totals.income);
  qs("#expenses").textContent=money.format(data.totals.expenses);
  qs("#balance").textContent=money.format(data.balance);
  qs("#uncategorized").textContent=data.uncategorized;
  qs("#fixed").textContent=money.format(data.totals.fixed);
  qs("#variable").textContent=money.format(data.totals.variable);
  const cost=data.totals.fixed+data.totals.variable;
  const share=cost?Math.round(data.totals.fixed/cost*100):0;
  qs("#fixed-share").textContent=`${share}%`;
  qs("#cost-donut").style.background=`conic-gradient(var(--purple) 0 ${share}%,#d8dcff ${share}% 100%)`;
  const max=Math.max(...data.categories.map(c=>c.amount),1);
  qs("#category-bars").innerHTML=data.categories.length?data.categories.map(c=>`
    <div class="category-row"><label>${escapeHtml(c.category)}</label><div class="bar-track"><div class="bar-fill" style="width:${Math.max(2,c.amount/max*100)}%;background:${c.color}"></div></div><strong>${money.format(c.amount)}</strong></div>`).join(""):'<p class="hint">Fuer diesen Monat sind noch keine Ausgaben vorhanden.</p>';
  const monthMax=Math.max(...data.months.flatMap(m=>[m.income,m.expenses]),1);
  qs("#timeline").innerHTML=data.months.map(m=>`<div class="month-col" title="${m.month}: ${money.format(m.income)} rein, ${money.format(m.expenses)} raus"><div class="bars"><i style="height:${m.income/monthMax*100}%"></i><i class="out" style="height:${m.expenses/monthMax*100}%"></i></div><span>${m.month.slice(5)}</span></div>`).join("");
}

async function loadTransactions(){
  const search=encodeURIComponent(qs("#search").value);
  const category=encodeURIComponent(qs("#category-filter").value);
  state.transactions=await api(`/api/transactions?month=${state.month}&q=${search}&category=${category}`);
  qs("#transaction-rows").innerHTML=state.transactions.map(t=>`
    <tr>
      <td>${formatDate(t.booked_on)}</td>
      <td class="transaction-main"><strong>${escapeHtml(t.payee||t.booking_type||"Buchung")}</strong><span>${escapeHtml(t.description||t.booking_type||"")}</span></td>
      <td><span class="pill ${t.is_transfer?"transfer":""}">${escapeHtml(t.category)}</span></td>
      <td>${t.is_transfer?"Transfer":t.expense_type==="fixed"?"Fixkosten":t.expense_type==="income"?"Einnahme":"Variabel"}</td>
      <td class="amount ${t.amount>0?"positive":""}">${money.format(t.amount)}</td>
      <td><button class="small-button make-rule" data-id="${t.id}">Regel</button></td>
    </tr>`).join("");
}

async function loadRules(){
  const rules=await api("/api/rules");
  qs("#rule-list").innerHTML=rules.map(r=>`
    <article class="rule-card"><div><strong>${escapeHtml(r.name)}</strong><small>${r.match_type==="regex"?"RegEx":"Keyword"} · Prioritaet ${r.priority}</small></div><code>${escapeHtml(r.pattern)}</code><span class="pill">${escapeHtml(r.category)}</span><span>${r.expense_type==="fixed"?"Fixkosten":r.expense_type==="income"?"Einnahme":"Variabel"}</span><button class="small-button delete" data-rule="${r.id}">Loeschen</button></article>`).join("");
}

async function loadImports(){
  const rows=await api("/api/imports");
  qs("#import-history").innerHTML=rows.length?rows.map(r=>`<div class="import-row"><strong>${escapeHtml(r.filename)}<small> · ${r.source}</small></strong><span>${r.new_count} neu</span><span>${r.duplicate_count} doppelt</span><span>${r.imported_at.slice(0,16)}</span></div>`).join(""):'<p class="hint">Noch keine Dateien importiert.</p>';
}

function openRule(transaction){
  const form=qs("#rule-form");
  form.reset();
  const selected=window.getSelection().toString().trim();
  const suggested=selected||transaction.payee||transaction.description.split(/\s+/).slice(0,3).join(" ");
  form.elements.pattern.value=suggested;
  form.elements.name.value=suggested;
  form.elements.expense_type.value=transaction.amount>0?"income":"variable";
  qs("#rule-dialog").showModal();
}

async function saveRule(event){
  event.preventDefault();
  const data=Object.fromEntries(new FormData(event.target));
  data.priority=Number(data.priority);
  await api("/api/rules",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});
  qs("#rule-dialog").close();
  toast("Regel gespeichert und auf Buchungen angewendet");
  await Promise.all([loadRules(),loadTransactions(),loadDashboard()]);
}

async function upload(){
  const file=qs("#csv-file").files[0];if(!file)return;
  const button=qs("#upload");button.disabled=true;button.textContent="Import laeuft...";
  try{
    const result=await api("/api/import",{method:"POST",headers:{"Content-Type":"text/csv","X-Source":qs("#source").value,"X-Filename":file.name},body:file});
    const el=qs("#import-result");el.classList.remove("hidden");el.innerHTML=`<strong>${result.new} neue Buchungen</strong><br>${result.duplicates} Duplikate uebersprungen, ${result.transfer_pairs} Transfer-Paare erkannt.`;
    toast("Import abgeschlossen");
    await Promise.all([loadDashboard(),loadTransactions(),loadImports()]);
  }catch(error){toast(error.message)}
  finally{button.disabled=false;button.textContent="Import starten"}
}

async function init(){
  qs("#month").value=state.month;
  await loadCategories();
  await Promise.all([loadDashboard(),loadTransactions(),loadRules(),loadImports()]);
  qsa(".nav").forEach(button=>button.addEventListener("click",()=>{
    qsa(".nav,.view").forEach(el=>el.classList.remove("active"));button.classList.add("active");qs(`#${button.dataset.view}`).classList.add("active");
    qs("#page-title").textContent=button.textContent;qs("#month").parentElement.style.display=["dashboard","transactions"].includes(button.dataset.view)?"flex":"none";
  }));
  qs("#month").addEventListener("change",async e=>{state.month=e.target.value;await Promise.all([loadDashboard(),loadTransactions()])});
  let timer;qs("#search").addEventListener("input",()=>{clearTimeout(timer);timer=setTimeout(loadTransactions,250)});
  qs("#category-filter").addEventListener("change",loadTransactions);
  qs("#transaction-rows").addEventListener("click",e=>{const button=e.target.closest(".make-rule");if(button)openRule(state.transactions.find(t=>t.id===Number(button.dataset.id)))});
  qs("#new-rule").addEventListener("click",()=>openRule({payee:"",description:"",amount:-1}));
  qs("#rule-form").addEventListener("submit",saveRule);
  qsa("[data-close-dialog]").forEach(button=>button.addEventListener("click",()=>qs("#rule-dialog").close()));
  qs("#rule-list").addEventListener("click",async e=>{const button=e.target.closest("[data-rule]");if(!button)return;if(!confirm("Diese Regel loeschen?"))return;await api(`/api/rules/${button.dataset.rule}`,{method:"DELETE"});toast("Regel geloescht");await Promise.all([loadRules(),loadTransactions(),loadDashboard()])});
  qs("#csv-file").addEventListener("change",e=>{qs("#upload").disabled=!e.target.files.length;if(e.target.files[0])qs("#dropzone strong").textContent=e.target.files[0].name});
  qs("#upload").addEventListener("click",upload);
  const drop=qs("#dropzone");["dragenter","dragover"].forEach(name=>drop.addEventListener(name,e=>{e.preventDefault();drop.classList.add("drag")}));["dragleave","drop"].forEach(name=>drop.addEventListener(name,e=>{e.preventDefault();drop.classList.remove("drag")}));drop.addEventListener("drop",e=>{qs("#csv-file").files=e.dataTransfer.files;qs("#csv-file").dispatchEvent(new Event("change"))});
  qs("#reconcile").addEventListener("click",async()=>{const r=await api("/api/reconcile",{method:"POST"});toast(`${r.transfer_pairs} Transfer-Paare erkannt`);await Promise.all([loadDashboard(),loadTransactions()])});
  if("serviceWorker" in navigator)navigator.serviceWorker.register("service-worker.js");
}
init().catch(error=>toast(error.message));

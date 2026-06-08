const state={month:new Date().toISOString().slice(0,7),source:"",dashboardMode:"gross",categories:[],transactions:[],sankey:{data:null,expandedCategories:new Set(),expandedParties:new Set(),zoom:1,panX:0,panY:0,graph:null}};
const money=new Intl.NumberFormat("de-DE",{style:"currency",currency:"EUR"});
const qs=s=>document.querySelector(s);
const qsa=s=>[...document.querySelectorAll(s)];

async function api(path,options={}){const res=await fetch(path,options);const data=await res.json().catch(()=>({}));if(!res.ok)throw new Error(data.error||"Fehler bei der Anfrage");return data}
function toast(message){const el=qs("#toast");el.textContent=message;el.classList.add("show");setTimeout(()=>el.classList.remove("show"),2600)}
function escapeHtml(value=""){return value.replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[ch]))}
function formatDate(value){return new Intl.DateTimeFormat("de-DE").format(new Date(value+"T12:00:00"))}
function sourceName(value){return {sparkasse:"Sparkasse",n26:"N26",paypal:"PayPal"}[value]||value}
function categoryOptions(selected=""){
  const byName=(a,b)=>a.name.localeCompare(b.name,"de");
  const regular=state.categories.filter(c=>!c.name.startsWith("Investieren · ")).sort(byName);
  const investments=state.categories.filter(c=>c.name.startsWith("Investieren · ")).sort(byName);
  const options=regular.map(c=>`<option value="${escapeHtml(c.name)}" ${c.name===selected?"selected":""}>${escapeHtml(c.name)}</option>`).join("");
  const investmentOptions=investments.map(c=>`<option value="${escapeHtml(c.name)}" ${c.name===selected?"selected":""}>${escapeHtml(c.name.replace("Investieren · ",""))}</option>`).join("");
  return `${options}<optgroup label="Investieren">${investmentOptions}</optgroup>`;
}

async function loadCategories(){
  state.categories=await api("/api/categories");
  const options=categoryOptions();
  qs("#category-filter").innerHTML=`<option value="">Alle Kategorien</option>${options}`;
  qs('#rule-form select[name="category"]').innerHTML=options;
  qs("#sankey-categories").innerHTML=state.categories.map(c=>`
    <label><input type="checkbox" name="sankey-category" value="${escapeHtml(c.name)}" checked>
    <i style="background:${c.color}"></i>${escapeHtml(c.name)}</label>`).join("");
}

async function loadDashboard(){
  const data=await api(`/api/dashboard?month=${state.month}&source=${encodeURIComponent(state.source)}&view=${state.dashboardMode}`);
  qs("#income").textContent=money.format(data.totals.income);
  qs("#expenses").textContent=money.format(data.totals.expenses);
  qs("#balance").textContent=money.format(data.balance);
  qs("#expenses-label").textContent=state.dashboardMode==="personal"?"Persoenliche Nettokosten":"Ausgaben";
  qs("#expenses-note").textContent=state.dashboardMode==="personal"?"WG-Einnahmen bereits abgezogen":"ohne interne Transfers";
  qs("#balance-note").textContent=state.dashboardMode==="personal"?"Einnahmen minus persoenliche Nettokosten":"Einnahmen minus Ausgaben";
  qs("#uncategorized").textContent=data.uncategorized;
  qs("#fixed").textContent=money.format(data.totals.fixed);
  qs("#variable").textContent=money.format(data.totals.variable);
  const fixed=Math.max(0,data.totals.fixed);
  const variable=Math.max(0,data.totals.variable);
  const cost=fixed+variable;
  const share=cost?Math.round(fixed/cost*100):0;
  qs("#fixed-share").textContent=`${share}%`;
  qs("#cost-donut").style.background=`conic-gradient(var(--purple) 0 ${share}%,#d8dcff ${share}% 100%)`;
  const max=Math.max(...data.categories.map(c=>c.amount),1);
  qs("#category-bars").innerHTML=data.categories.length?data.categories.map(c=>`
    <div class="category-row"><label>${escapeHtml(c.category)}</label><div class="bar-track"><div class="bar-fill" style="width:${Math.max(2,c.amount/max*100)}%;background:${c.color}"></div></div><strong>${money.format(c.amount)}</strong></div>`).join(""):'<p class="hint">Fuer diesen Monat sind noch keine Ausgaben vorhanden.</p>';
  const monthMax=Math.max(...data.months.flatMap(m=>[m.income,m.expenses]),1);
  qs("#timeline").innerHTML=data.months.map(m=>`<div class="month-col" title="${m.month}: ${money.format(m.income)} rein, ${money.format(m.expenses)} raus"><div class="bars"><i style="height:${m.income/monthMax*100}%"></i><i class="out" style="height:${m.expenses/monthMax*100}%"></i></div><span>${m.month.slice(5)}</span></div>`).join("");
}

async function loadSharedHousehold(){
  const start=qs("#wg-start").value;
  const end=qs("#wg-end").value;
  const data=await api(`/api/shared-household?start=${start}&end=${end}`);
  qs("#wg-paid").textContent=money.format(data.paid);
  qs("#wg-received").textContent=money.format(data.received);
  qs("#wg-net").textContent=money.format(data.net);
  qs("#wg-breakdown").innerHTML=data.categories.map(c=>`
    <article class="panel wg-category">
      <p class="eyebrow">${escapeHtml(c.category.toUpperCase())}</p>
      <div><span>Gezahlt</span><strong>${money.format(c.paid)}</strong></div>
      <div><span>Erhalten</span><strong class="positive">${money.format(c.received)}</strong></div>
      <div class="wg-net"><span>Dein Anteil</span><strong>${money.format(c.net)}</strong></div>
    </article>`).join("");
  qs("#wg-rows").innerHTML=data.transactions.length?data.transactions.map(t=>`
    <tr><td>${formatDate(t.booked_on)}</td><td class="transaction-main"><strong>${escapeHtml(t.payee||t.booking_type||"Buchung")}</strong><span>${escapeHtml(t.description||"")}</span></td><td><span class="pill">${escapeHtml(t.category)}</span></td><td>${escapeHtml(sourceName(t.source))}</td><td class="amount ${t.amount>0?"positive":""}">${money.format(t.amount)}</td></tr>`).join(""):'<tr><td colspan="5" class="hint">Keine WG-Buchungen in diesem Zeitraum.</td></tr>';
}

async function loadTransactions(){
  const search=encodeURIComponent(qs("#search").value);
  const category=encodeURIComponent(qs("#category-filter").value);
  state.transactions=await api(`/api/transactions?month=${state.month}&q=${search}&category=${category}&source=${encodeURIComponent(state.source)}`);
  qs("#transaction-rows").innerHTML=state.transactions.map(t=>`
    <tr>
      <td>${formatDate(t.booked_on)}</td>
      <td class="transaction-main"><strong>${escapeHtml(t.payee||t.booking_type||"Buchung")}</strong><span>${escapeHtml(t.description||t.booking_type||"")}</span></td>
      <td><select class="transaction-category" data-id="${t.id}" aria-label="Kategorie">${categoryOptions(t.category)}</select></td>
      <td>${t.is_transfer?"Transfer":t.expense_type==="fixed"?"Fixkosten":t.expense_type==="income"?"Einnahme":"Variabel"}</td>
      <td class="amount ${t.amount>0?"positive":""}">${money.format(t.amount)}</td>
      <td><button class="small-button make-rule" data-id="${t.id}">Regel</button></td>
    </tr>`).join("");
}

async function loadInvestments(){
  const data=await api("/api/investments");
  qs("#invested-total").textContent=money.format(data.invested);
  qs("#investment-returns").textContent=money.format(data.returned);
  qs("#investment-net").textContent=money.format(data.net);
  const max=Math.max(...data.categories.map(c=>c.invested),1);
  qs("#investment-breakdown").innerHTML=data.categories.length?data.categories.map(c=>`
    <div class="investment-row"><i style="background:${c.color}"></i><div><strong>${escapeHtml(c.label)}</strong><span>${c.count} Buchungen</span></div><div class="bar-track"><div class="bar-fill" style="width:${Math.max(2,c.invested/max*100)}%;background:${c.color}"></div></div><b>${money.format(c.invested)}</b></div>`).join(""):'<p class="hint">Ordne Buchungen einer Investment-Kategorie zu. Sie erscheinen dann automatisch hier.</p>';
  const monthMax=Math.max(...data.months.map(m=>m.invested),1);
  qs("#investment-timeline").innerHTML=data.months.length?data.months.slice(-12).map(m=>`<div class="month-col" title="${m.month}: ${money.format(m.invested)}"><div class="bars"><i class="investment-bar" style="height:${m.invested/monthMax*100}%"></i></div><span>${m.month.slice(5)}</span></div>`).join(""):'<p class="hint">Noch keine Investment-Einzahlungen vorhanden.</p>';
  qs("#investment-rows").innerHTML=data.transactions.length?data.transactions.map(t=>`
    <tr><td>${formatDate(t.booked_on)}</td><td class="transaction-main"><strong>${escapeHtml(t.payee||t.booking_type||"Buchung")}</strong><span>${escapeHtml(t.description||"")}</span></td><td><span class="pill investment">${escapeHtml(t.category.replace("Investieren · ",""))}</span></td><td class="amount ${t.amount>0?"positive":""}">${money.format(t.amount)}</td></tr>`).join(""):'<tr><td colspan="4" class="hint">Noch keine Investment-Buchungen vorhanden.</td></tr>';
}

async function loadOutlays(){
  const data=await api("/api/outlays");
  qs("#outlays-paid").textContent=money.format(data.paid);
  qs("#outlays-reimbursed").textContent=money.format(data.reimbursed);
  qs("#outlays-open").textContent=money.format(data.open);
  const status={settled:"Ausgeglichen",open:"Offen",unassigned:"Nicht zugeordnet"};
  qs("#outlay-rows").innerHTML=data.transactions.length?data.transactions.map(t=>`
    <tr><td>${formatDate(t.booked_on)}</td><td class="transaction-main"><strong>${escapeHtml(t.payee||t.booking_type||"Buchung")}</strong><span>${escapeHtml(t.description||"")}</span></td><td>${escapeHtml(sourceName(t.source))}</td><td><span class="pill ${t.amount>0?"reimbursed":"outlay"}">${t.amount>0?"Erstattung":"Ausgelegt"}</span></td><td>${status[t.outlay_status]}</td><td class="amount ${t.amount>0?"positive":""}">${money.format(t.amount)}</td></tr>`).join(""):'<tr><td colspan="6" class="hint">Noch keine Buchungen als Auslagen markiert.</td></tr>';
}

async function loadRules(){
  const rules=await api("/api/rules");
  qs("#rule-list").innerHTML=rules.map(r=>`
    <article class="rule-card"><div><strong>${escapeHtml(r.name)}</strong><small>${r.match_type==="regex"?"RegEx":"Keyword"} · Prioritaet ${r.priority}</small></div><code>${escapeHtml(r.pattern)}</code><span class="pill">${escapeHtml(r.category)}</span><span>${r.expense_type==="fixed"?"Fixkosten":r.expense_type==="income"?"Einnahme":"Variabel"}</span><button class="small-button delete" data-rule="${r.id}">Loeschen</button></article>`).join("");
}

async function loadCategoryUsage(){
  const categories=await api("/api/categories");
  qs("#category-usage").innerHTML=categories.map(c=>`
    <div class="category-usage-row">
      <i style="background:${c.color}"></i>
      <strong>${escapeHtml(c.name)}</strong>
      <span>${c.usage_count} Buchungen</span>
      <span>${money.format(c.spent)} Ausgaben</span>
      ${c.removable?`<button class="small-button delete" data-category="${escapeHtml(c.name)}">Entfernen</button>`:"<small>System</small>"}
    </div>`).join("");
}

async function loadImports(){
  const rows=await api("/api/imports");
  qs("#import-history").innerHTML=rows.length?rows.map(r=>`<div class="import-row"><strong>${escapeHtml(r.filename)}<small> · ${r.source}</small></strong><span>${r.new_count} neu</span><span>${r.duplicate_count} doppelt</span><span>${r.imported_at.slice(0,16)}</span></div>`).join(""):'<p class="hint">Noch keine Dateien importiert.</p>';
}

function sankeySelected(name){return qsa(`input[name="${name}"]:checked`).map(input=>input.value)}
function sankeyNodeId(value){return encodeURIComponent(value).replace(/%/g,"_")}
function shortLabel(value,max=24){return value.length>max?`${value.slice(0,max-1)}…`:value}
function sankeyTransactionLabel(transaction){
  return `${formatDate(transaction.booked_on)} · ${transaction.description||transaction.booking_type||transaction.counterparty}`;
}

function buildSankeyGraph(){
  const data=state.sankey.data;
  const showIncome=qs("#sankey-income-toggle").checked;
  const showExpenses=qs("#sankey-expense-toggle").checked;
  const showTransfers=qs("#sankey-transfer-toggle").checked;
  const nodes=new Map();
  const links=new Map();
  const accountBalances=new Map();
  const addNode=(definition,transaction)=>{
    if(!nodes.has(definition.id))nodes.set(definition.id,{...definition,transactions:new Set()});
    if(transaction)nodes.get(definition.id).transactions.add(transaction.id);
    return nodes.get(definition.id);
  };
  const addPath=(path,transaction,value)=>{
    path.forEach(node=>addNode(node,transaction));
    for(let index=0;index<path.length-1;index++){
      const source=path[index],target=path[index+1],key=`${source.id}>${target.id}`;
      if(!links.has(key))links.set(key,{id:key,source:source.id,target:target.id,value:0,color:source.color||target.color,transactions:new Set()});
      const link=links.get(key);link.value+=value;if(transaction)link.transactions.add(transaction.id);
    }
  };
  const transferGroups=new Map();
  data.transactions.forEach(transaction=>{
    if(transaction.is_transfer){
      if(!showTransfers)return;
      if(!transferGroups.has(transaction.transfer_group))transferGroups.set(transaction.transfer_group,[]);
      transferGroups.get(transaction.transfer_group).push(transaction);
      return;
    }
    const value=Math.abs(transaction.amount);
    const direction=transaction.amount>0?"income":"expense";
    if(direction==="income"&&!showIncome)return;
    if(direction==="expense"&&!showExpenses)return;
    const categoryId=`${direction}-category:${transaction.category}`;
    const partyId=`${direction}-party:${transaction.category}:${transaction.counterparty}`;
    const account={id:`account:${transaction.source}`,label:transaction.account_label,layer:3,type:"account",color:"#101828"};
    if(!accountBalances.has(transaction.source))accountBalances.set(transaction.source,{account,income:0,expenses:0});
    if(transaction.amount>0)accountBalances.get(transaction.source).income+=value;
    else accountBalances.get(transaction.source).expenses+=value;
    const category={id:categoryId,label:transaction.category,layer:direction==="income"?2:4,type:"category",color:transaction.color,direction};
    const party={id:partyId,label:transaction.counterparty,layer:direction==="income"?1:5,type:"party",color:transaction.color,direction,parent:categoryId};
    const detail={id:`transaction:${transaction.id}`,label:sankeyTransactionLabel(transaction),layer:direction==="income"?0:6,type:"transaction",color:transaction.color,direction,parent:partyId};
    if(direction==="income"){
      const path=[category,account];
      if(state.sankey.expandedCategories.has(categoryId))path.unshift(party);
      if(state.sankey.expandedParties.has(partyId))path.unshift(detail);
      addPath(path,transaction,value);
    }else{
      const path=[account,category];
      if(state.sankey.expandedCategories.has(categoryId))path.push(party);
      if(state.sankey.expandedParties.has(partyId))path.push(detail);
      addPath(path,transaction,value);
    }
  });
  if(showIncome&&showExpenses){
    accountBalances.forEach(balance=>{
      const difference=balance.income-balance.expenses;
      if(Math.abs(difference)<.005)return;
      if(difference>0)addPath([
        balance.account,
        {id:`balance:${balance.account.id}:positive`,label:"Zeitraumueberschuss",layer:4,type:"balance",color:"#1f9d73"}
      ],null,difference);
      else addPath([
        {id:`balance:${balance.account.id}:negative`,label:"Aus Startbestand / Ruecklagen",layer:2,type:"balance",color:"#f59e0b"},
        balance.account
      ],null,-difference);
    });
  }
  transferGroups.forEach((group,groupId)=>{
    const outgoing=group.find(item=>item.amount<0);
    const incoming=group.find(item=>item.amount>0);
    if(!outgoing&&!incoming)return;
    const value=Math.abs((outgoing||incoming).amount);
    const from=outgoing?.account_label||"Anderes eigenes Konto";
    const to=incoming?.account_label||"Anderes eigenes Konto";
    addPath([
      {id:`account:${outgoing?.source||"external"}`,label:from,layer:3,type:"account",color:"#101828"},
      {id:`transfer:${groupId}`,label:`Transfer → ${to}`,layer:4,type:"transfer",color:"#94a3b8"}
    ],outgoing||incoming,value);
  });
  const transactionById=new Map(data.transactions.map(transaction=>[transaction.id,transaction]));
  return {
    nodes:[...nodes.values()].map(node=>({...node,transactions:[...node.transactions].map(id=>transactionById.get(id)).filter(Boolean)})),
    links:[...links.values()].map(link=>({...link,transactions:[...link.transactions].map(id=>transactionById.get(id)).filter(Boolean)}))
  };
}

function layoutSankey(graph){
  const layers=new Map();
  graph.nodes.forEach(node=>{if(!layers.has(node.layer))layers.set(node.layer,[]);layers.get(node.layer).push(node)});
  graph.links.forEach(link=>{
    link.sourceNode=graph.nodes.find(node=>node.id===link.source);
    link.targetNode=graph.nodes.find(node=>node.id===link.target);
    link.sourceNode.outgoing=(link.sourceNode.outgoing||0)+link.value;
    link.targetNode.incoming=(link.targetNode.incoming||0)+link.value;
  });
  graph.nodes.forEach(node=>node.value=Math.max(node.incoming||0,node.outgoing||0));
  layers.forEach(nodes=>nodes.sort((a,b)=>b.value-a.value||a.label.localeCompare(b.label,"de")));
  const maxNodes=Math.max(...[...layers.values()].map(nodes=>nodes.length),1);
  const height=Math.max(640,maxNodes*24+105);
  const width=Math.max(1150,Math.max(...layers.keys())*250+260),nodeWidth=16,gap=10,top=55;
  let scale=Infinity;
  layers.forEach(nodes=>{
    const total=nodes.reduce((sum,node)=>sum+node.value,0);
    const available=height-top-30-gap*Math.max(0,nodes.length-1)-8*nodes.length;
    if(total)scale=Math.min(scale,Math.max(.02,available/total));
  });
  if(!Number.isFinite(scale))scale=1;
  layers.forEach((nodes,layer)=>{
    const columnHeight=nodes.reduce((sum,node)=>sum+8+node.value*scale,0)+gap*Math.max(0,nodes.length-1);
    let y=Math.max(top,top+(height-top-30-columnHeight)/2);
    nodes.forEach(node=>{
      node.x=45+layer*250;
      node.y=y;
      node.height=8+node.value*scale;
      node.width=nodeWidth;
      node.sourceOffset=4;
      node.targetOffset=4;
      y+=node.height+gap;
    });
  });
  graph.links.sort((a,b)=>a.targetNode.y-b.targetNode.y);
  graph.links.forEach(link=>{
    link.width=Math.max(1,link.value*scale);
    link.sy=link.sourceNode.y+link.sourceNode.sourceOffset+link.width/2;
    link.ty=link.targetNode.y+link.targetNode.targetOffset+link.width/2;
    link.sourceNode.sourceOffset+=link.width;
    link.targetNode.targetOffset+=link.width;
  });
  return {width,height,layers};
}

function sankeyDetail(item){
  const transactions=item.transactions||[];
  const total=item.value||transactions.reduce((sum,transaction)=>sum+Math.abs(transaction.amount),0);
  const sorted=[...transactions].sort((a,b)=>Math.abs(b.amount)-Math.abs(a.amount));
  qs("#sankey-detail-title").textContent=item.label||"Geldstrom";
  qs("#sankey-detail").innerHTML=`
    <div class="sankey-detail-summary">
      <div><span>Betrag</span><strong>${money.format(total)}</strong></div>
      <div><span>Buchungen</span><strong>${transactions.length}</strong></div>
      <div><span>Anteil am sichtbaren Volumen</span><strong>${state.sankey.data.summary.income+state.sankey.data.summary.expenses?Math.round(total/(state.sankey.data.summary.income+state.sankey.data.summary.expenses)*100):0}%</strong></div>
    </div>
    ${sorted.slice(0,100).map(transaction=>`<div class="sankey-detail-row"><span>${formatDate(transaction.booked_on)}</span><strong>${escapeHtml(transaction.counterparty)}<small>${escapeHtml(transaction.description||transaction.booking_type||"")}</small></strong><strong>${money.format(transaction.amount)}</strong></div>`).join("")}
    ${sorted.length>100?`<p class="hint">Weitere ${sorted.length-100} Buchungen sind in dieser Summe enthalten.</p>`:""}`;
}

function applySankeyTransform(){
  const viewport=qs("#sankey-viewport");if(!viewport)return;
  viewport.setAttribute("transform",`translate(${state.sankey.panX} ${state.sankey.panY}) scale(${state.sankey.zoom})`);
  qsa("[data-sankey-zoom='reset']").forEach(button=>button.textContent=`${Math.round(state.sankey.zoom*100)}%`);
}

function renderSankey(){
  const graph=buildSankeyGraph();
  state.sankey.graph=graph;
  const svg=qs("#sankey-svg");
  const empty=qs("#sankey-empty");
  const visible=state.sankey.data.transactions.filter(transaction=>!transaction.is_transfer);
  const income=qs("#sankey-income-toggle").checked?visible.filter(transaction=>transaction.amount>0).reduce((sum,transaction)=>sum+transaction.amount,0):0;
  const expenses=qs("#sankey-expense-toggle").checked?visible.filter(transaction=>transaction.amount<0).reduce((sum,transaction)=>sum-transaction.amount,0):0;
  qs("#sankey-income").textContent=money.format(income);
  qs("#sankey-expenses").textContent=money.format(expenses);
  qs("#sankey-balance").textContent=money.format(income-expenses);
  if(!graph.links.length){
    svg.innerHTML="";empty.classList.remove("hidden");return;
  }
  empty.classList.add("hidden");
  const layout=layoutSankey(graph);
  const layerNames={0:"EINZELBUCHUNGEN",1:"EINNAHMEQUELLEN",2:"EINNAHMEKATEGORIEN",3:"KONTEN",4:"AUSGABEKATEGORIEN",5:"EMPFAENGER",6:"EINZELBUCHUNGEN"};
  svg.setAttribute("viewBox",`0 0 ${layout.width} ${layout.height}`);
  const links=graph.links.map(link=>{
    const bend=(link.targetNode.x-link.sourceNode.x)*.48;
    const path=`M ${link.sourceNode.x+link.sourceNode.width} ${link.sy} C ${link.sourceNode.x+link.sourceNode.width+bend} ${link.sy}, ${link.targetNode.x-bend} ${link.ty}, ${link.targetNode.x} ${link.ty}`;
    return `<path class="sankey-link" data-link="${escapeHtml(link.id)}" d="${path}" stroke="${link.color}" stroke-width="${link.width}"/>`;
  }).join("");
  const titles=[...layout.layers.keys()].sort((a,b)=>a-b).map(layer=>`<text class="sankey-column-title" x="${45+layer*250}" y="25">${layerNames[layer]}</text>`).join("");
  const nodes=graph.nodes.map(node=>{
    const expandable=node.type==="category"||node.type==="party";
    const expanded=state.sankey.expandedCategories.has(node.id)||state.sankey.expandedParties.has(node.id);
    const labelX=node.layer<=2?node.x-8:node.x+node.width+8;
    const anchor=node.layer<=2?"end":"start";
    return `<g class="sankey-node ${expandable?"expandable":""}" data-node="${escapeHtml(node.id)}">
      <rect x="${node.x}" y="${node.y}" width="${node.width}" height="${node.height}" rx="4" fill="${node.color}"/>
      ${expandable&&node.height>=15?`<text class="expand-marker" x="${node.x+node.width/2}" y="${node.y+Math.min(node.height/2+4,15)}" text-anchor="middle">${expanded?"−":"+"}</text>`:""}
      <text x="${labelX}" y="${node.y+Math.min(13,node.height/2)}" text-anchor="${anchor}">${escapeHtml(shortLabel(node.label))}</text>
      <text class="node-value" x="${labelX}" y="${node.y+Math.min(27,node.height/2+14)}" text-anchor="${anchor}">${escapeHtml(money.format(node.value))}</text>
    </g>`;
  }).join("");
  svg.innerHTML=`<g id="sankey-viewport">${titles}${links}${nodes}</g>`;
  applySankeyTransform();
  qsa(".sankey-node").forEach(element=>{
    const node=graph.nodes.find(item=>item.id===element.dataset.node);
    element.addEventListener("mouseenter",()=>sankeyDetail(node));
    element.addEventListener("click",event=>{
      event.stopPropagation();
      if(node.type==="category"){
        state.sankey.expandedCategories.has(node.id)?state.sankey.expandedCategories.delete(node.id):state.sankey.expandedCategories.add(node.id);
        renderSankey();
      }else if(node.type==="party"){
        state.sankey.expandedParties.has(node.id)?state.sankey.expandedParties.delete(node.id):state.sankey.expandedParties.add(node.id);
        renderSankey();
      }else sankeyDetail(node);
    });
  });
  qsa(".sankey-link").forEach(element=>{
    const link=graph.links.find(item=>item.id===element.dataset.link);
    element.addEventListener("mouseenter",()=>sankeyDetail({...link,label:`${link.sourceNode.label} → ${link.targetNode.label}`}));
  });
  applySankeySearch();
  const detailCount=state.sankey.expandedCategories.size+state.sankey.expandedParties.size;
  qs("#sankey-depth").textContent=detailCount?`${detailCount} Bereiche aufgeklappt`:"Kategorien sichtbar";
}

function applySankeySearch(){
  const term=text_key_js(qs("#sankey-search").value);
  const graph=state.sankey.graph;if(!graph)return;
  const matching=new Set();
  graph.nodes.forEach(node=>{
    if(!term||text_key_js(node.label).includes(term)||node.transactions.some(transaction=>text_key_js(`${transaction.counterparty} ${transaction.description} ${transaction.category}`).includes(term)))matching.add(node.id);
  });
  qsa(".sankey-node").forEach(element=>element.classList.toggle("dim",term&&!matching.has(element.dataset.node)));
  qsa(".sankey-link").forEach(element=>{
    const link=graph.links.find(item=>item.id===element.dataset.link);
    element.classList.toggle("dim",term&&!matching.has(link.source)&&!matching.has(link.target));
  });
}
function text_key_js(value=""){return value.normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase()}

async function loadSankey(){
  const sources=sankeySelected("sankey-source");
  const categories=sankeySelected("sankey-category");
  if(!sources.length){toast("Waehle mindestens ein Konto aus");return}
  if(!categories.length){
    state.sankey.data={summary:{income:0,expenses:0,balance:0,transfers:0,count:0},transactions:[]};
  }else{
    const params=new URLSearchParams({start:qs("#sankey-start").value,end:qs("#sankey-end").value,transfers:qs("#sankey-transfer-toggle").checked?"1":"0"});
    sources.forEach(source=>params.append("source",source));
    if(categories.length<state.categories.length)categories.forEach(category=>params.append("category",category));
    state.sankey.data=await api(`/api/sankey?${params}`);
  }
  const summary=state.sankey.data.summary;
  qs("#sankey-income").textContent=money.format(summary.income);
  qs("#sankey-expenses").textContent=money.format(summary.expenses);
  qs("#sankey-balance").textContent=money.format(summary.balance);
  qs("#sankey-count").textContent=summary.count;
  if(summary.truncated)toast("Das Diagramm zeigt die ersten 5.000 Buchungen dieses Filters");
  renderSankey();
}

async function openRule(transaction){
  const form=qs("#rule-form");
  form.reset();
  const conflicts=qs("#rule-conflicts");
  conflicts.classList.add("hidden");
  conflicts.innerHTML="";
  const selected=window.getSelection().toString().trim();
  const suggested=selected||transaction.payee||transaction.description.split(/\s+/).slice(0,3).join(" ");
  form.elements.pattern.value=suggested;
  form.elements.name.value=suggested;
  form.elements.expense_type.value=transaction.amount>0?"income":"variable";
  if(transaction.category)form.elements.category.value=transaction.category;
  form.elements.priority.value=100;
  if(transaction.id){
    const matches=await api(`/api/transactions/${transaction.id}/matching-rules`);
    if(matches.length){
      const highest=Math.max(...matches.map(rule=>rule.priority));
      form.elements.priority.value=Math.min(999,Math.max(100,highest+10));
      conflicts.classList.remove("hidden");
      conflicts.innerHTML=`<strong>Bereits passende Regeln</strong>${matches.map(rule=>`
        <span>${escapeHtml(rule.name)} → ${escapeHtml(rule.category)} (Prioritaet ${rule.priority})</span>`).join("")}<small>Die neue Regel wurde automatisch hoeher priorisiert.</small>`;
    }
  }
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
  const today=new Date();
  qs("#wg-start").value=`${today.getFullYear()}-01-01`;
  qs("#wg-end").value=today.toISOString().slice(0,10);
  qs("#sankey-start").value=`${today.getFullYear()}-01-01`;
  qs("#sankey-end").value=today.toISOString().slice(0,10);
  await loadCategories();
  await Promise.all([loadDashboard(),loadSankey(),loadSharedHousehold(),loadTransactions(),loadInvestments(),loadOutlays(),loadRules(),loadCategoryUsage(),loadImports()]);
  qsa(".nav").forEach(button=>button.addEventListener("click",()=>{
    qsa(".nav,.view").forEach(el=>el.classList.remove("active"));button.classList.add("active");qs(`#${button.dataset.view}`).classList.add("active");
    qs("#page-title").textContent=button.textContent;
    const filtered=["dashboard","transactions"].includes(button.dataset.view);
    qs("#month").parentElement.style.display=filtered?"flex":"none";
    qs("#source-filter").parentElement.style.display=filtered?"flex":"none";
    if(button.dataset.view==="cashflow")setTimeout(()=>renderSankey(),0);
  }));
  qs("#month").addEventListener("change",async e=>{state.month=e.target.value;await Promise.all([loadDashboard(),loadTransactions()])});
  qs("#source-filter").addEventListener("change",async e=>{state.source=e.target.value;await Promise.all([loadDashboard(),loadTransactions()])});
  qsa(".dashboard-mode").forEach(button=>button.addEventListener("click",async()=>{
    qsa(".dashboard-mode").forEach(item=>item.classList.remove("active"));
    button.classList.add("active");
    state.dashboardMode=button.dataset.mode;
    await loadDashboard();
  }));
  qs("#wg-apply").addEventListener("click",()=>loadSharedHousehold().catch(error=>toast(error.message)));
  let timer;qs("#search").addEventListener("input",()=>{clearTimeout(timer);timer=setTimeout(loadTransactions,250)});
  qs("#category-filter").addEventListener("change",loadTransactions);
  qs("#sankey-apply").addEventListener("click",()=>loadSankey().catch(error=>toast(error.message)));
  qs("#sankey-collapse").addEventListener("click",()=>{
    state.sankey.expandedCategories.clear();state.sankey.expandedParties.clear();renderSankey();
  });
  const updateCategoryCount=()=>{
    const selected=sankeySelected("sankey-category").length;
    qs("#sankey-category-count").textContent=selected===state.categories.length?"Alle":`${selected} von ${state.categories.length}`;
  };
  qs("#sankey-categories").addEventListener("change",updateCategoryCount);
  qs("#sankey-category-all").addEventListener("click",()=>{qsa('input[name="sankey-category"]').forEach(input=>input.checked=true);updateCategoryCount()});
  qs("#sankey-category-none").addEventListener("click",()=>{qsa('input[name="sankey-category"]').forEach(input=>input.checked=false);updateCategoryCount()});
  qs("#sankey-income-toggle").addEventListener("change",renderSankey);
  qs("#sankey-expense-toggle").addEventListener("change",renderSankey);
  qs("#sankey-transfer-toggle").addEventListener("change",()=>loadSankey().catch(error=>toast(error.message)));
  qs("#sankey-search").addEventListener("input",applySankeySearch);
  qsa("[data-sankey-zoom]").forEach(button=>button.addEventListener("click",()=>{
    if(button.dataset.sankeyZoom==="in")state.sankey.zoom=Math.min(2.5,state.sankey.zoom*1.2);
    else if(button.dataset.sankeyZoom==="out")state.sankey.zoom=Math.max(.45,state.sankey.zoom/1.2);
    else{state.sankey.zoom=1;state.sankey.panX=0;state.sankey.panY=0}
    applySankeyTransform();
  }));
  const sankeySvg=qs("#sankey-svg");
  sankeySvg.addEventListener("wheel",event=>{
    event.preventDefault();
    state.sankey.zoom=Math.max(.45,Math.min(2.5,state.sankey.zoom*(event.deltaY<0?1.1:.9)));
    applySankeyTransform();
  },{passive:false});
  let dragging=false,lastPoint=null;
  sankeySvg.addEventListener("pointerdown",event=>{dragging=true;lastPoint={x:event.clientX,y:event.clientY};sankeySvg.setPointerCapture(event.pointerId);sankeySvg.classList.add("dragging")});
  sankeySvg.addEventListener("pointermove",event=>{
    if(!dragging)return;
    const scale=sankeySvg.viewBox.baseVal.width/sankeySvg.clientWidth;
    state.sankey.panX+=(event.clientX-lastPoint.x)*scale;
    state.sankey.panY+=(event.clientY-lastPoint.y)*scale;
    lastPoint={x:event.clientX,y:event.clientY};applySankeyTransform();
  });
  const stopDragging=()=>{dragging=false;lastPoint=null;sankeySvg.classList.remove("dragging")};
  sankeySvg.addEventListener("pointerup",stopDragging);sankeySvg.addEventListener("pointercancel",stopDragging);
  qs("#transaction-rows").addEventListener("click",e=>{const button=e.target.closest(".make-rule");if(button)openRule(state.transactions.find(t=>t.id===Number(button.dataset.id))).catch(error=>toast(error.message))});
  qs("#transaction-rows").addEventListener("change",async e=>{
    const select=e.target.closest(".transaction-category");if(!select)return;
    await api(`/api/transactions/${select.dataset.id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({category:select.value})});
    toast("Kategorie gespeichert");
    await Promise.all([loadTransactions(),loadDashboard(),loadInvestments(),loadOutlays(),loadCategoryUsage()]);
  });
  qs("#new-rule").addEventListener("click",()=>openRule({payee:"",description:"",amount:-1}).catch(error=>toast(error.message)));
  qs("#rule-form").addEventListener("submit",saveRule);
  qsa("[data-close-dialog]").forEach(button=>button.addEventListener("click",()=>qs("#rule-dialog").close()));
  qs("#rule-list").addEventListener("click",async e=>{const button=e.target.closest("[data-rule]");if(!button)return;if(!confirm("Diese Regel loeschen?"))return;await api(`/api/rules/${button.dataset.rule}`,{method:"DELETE"});toast("Regel geloescht");await Promise.all([loadRules(),loadTransactions(),loadDashboard()])});
  qs("#category-usage").addEventListener("click",async e=>{
    const button=e.target.closest("[data-category]");if(!button)return;
    const name=button.dataset.category;
    if(!confirm(`Kategorie „${name}“ entfernen? Zugeordnete Buchungen werden auf Sonstiges zurueckgesetzt.`))return;
    await api(`/api/categories/${encodeURIComponent(name)}`,{method:"DELETE"});
    toast("Kategorie entfernt");
    await loadCategories();
    await Promise.all([loadCategoryUsage(),loadTransactions(),loadDashboard(),loadInvestments(),loadOutlays(),loadRules()]);
  });
  qs("#csv-file").addEventListener("change",e=>{qs("#upload").disabled=!e.target.files.length;if(e.target.files[0])qs("#dropzone strong").textContent=e.target.files[0].name});
  qs("#upload").addEventListener("click",upload);
  const drop=qs("#dropzone");["dragenter","dragover"].forEach(name=>drop.addEventListener(name,e=>{e.preventDefault();drop.classList.add("drag")}));["dragleave","drop"].forEach(name=>drop.addEventListener(name,e=>{e.preventDefault();drop.classList.remove("drag")}));drop.addEventListener("drop",e=>{qs("#csv-file").files=e.dataTransfer.files;qs("#csv-file").dispatchEvent(new Event("change"))});
  qs("#reconcile").addEventListener("click",async()=>{const r=await api("/api/reconcile",{method:"POST"});toast(`${r.transfer_pairs} Transfer-Paare erkannt`);await Promise.all([loadDashboard(),loadTransactions()])});
  if("serviceWorker" in navigator)navigator.serviceWorker.register("service-worker.js");
}
init().catch(error=>toast(error.message));

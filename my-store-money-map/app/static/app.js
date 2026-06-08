const state={month:new Date().toISOString().slice(0,7),source:"",dashboardMode:"gross",categories:[],transactions:[],sankey:{data:null,graph:null,selected:null}};
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
function shortLabel(value,max=24){return value.length>max?`${value.slice(0,max-1)}…`:value}

function buildSankeyGraph(){
  const data=state.sankey.data;
  const showIncome=qs("#sankey-income-toggle").checked;
  const showExpenses=qs("#sankey-expense-toggle").checked;
  const showTransfers=qs("#sankey-transfer-toggle").checked;
  const nodes=new Map();
  const links=new Map();
  const accountBalances=new Map();
  const addNode=(definition,transactions=[])=>{
    if(!nodes.has(definition.id))nodes.set(definition.id,{...definition,transactions:new Set()});
    transactions.forEach(transaction=>nodes.get(definition.id).transactions.add(transaction.id));
    return nodes.get(definition.id);
  };
  const addPath=(path,transactions,value)=>{
    const items=(Array.isArray(transactions)?transactions:[transactions]).filter(Boolean);
    path.forEach(node=>addNode(node,items));
    for(let index=0;index<path.length-1;index++){
      const source=path[index],target=path[index+1],key=`${source.id}>${target.id}`;
      if(!links.has(key))links.set(key,{id:key,source:source.id,target:target.id,value:0,color:source.color||target.color,transactions:new Set()});
      const link=links.get(key);link.value+=value;items.forEach(transaction=>link.transactions.add(transaction.id));
    }
  };
  const accountNode=(source,label)=>{
    const primary=source==="sparkasse";
    return {id:`account:${source}`,label:label||sourceName(source),group:primary?"primary-account":"secondary-account",type:"account",color:primary?"#3448c5":"#101828",source};
  };
  const inflowNode=(transaction)=>{
    const primary=transaction.source==="sparkasse";
    return {id:`inflow:${transaction.source}:${transaction.category}`,label:`Eingang · ${transaction.category}`,group:primary?"primary-inflow":"secondary-inflow",type:"inflow",color:transaction.color,direction:"income"};
  };
  const categoryNode=(transaction)=>({id:`category:${transaction.category}`,label:transaction.category,group:"category",type:"category",color:transaction.color,direction:"expense"});
  const balanceFor=(source,label)=>{
    if(!accountBalances.has(source))accountBalances.set(source,{account:accountNode(source,label),income:0,expenses:0,transferIn:0,transferOut:0});
    return accountBalances.get(source);
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
    const account=accountNode(transaction.source,transaction.account_label);
    const balance=balanceFor(transaction.source,transaction.account_label);
    if(direction==="income"){
      balance.income+=value;
      addPath([inflowNode(transaction),account],transaction,value);
    }else{
      balance.expenses+=value;
      addPath([account,categoryNode(transaction)],transaction,value);
    }
  });
  transferGroups.forEach((group,groupId)=>{
    const outgoing=group.find(item=>item.amount<0);
    const incoming=group.find(item=>item.amount>0);
    if(!outgoing&&!incoming)return;
    const value=Math.abs((outgoing||incoming).amount);
    const fallbackSource=`external-${groupId}`;
    const fromSource=outgoing?.source||fallbackSource;
    const toSource=incoming?.source||fallbackSource;
    const from=accountNode(fromSource,outgoing?.account_label||"Anderes eigenes Konto");
    const to=accountNode(toSource,incoming?.account_label||"Anderes eigenes Konto");
    if(outgoing)balanceFor(outgoing.source,outgoing.account_label).transferOut+=value;
    if(incoming)balanceFor(incoming.source,incoming.account_label).transferIn+=value;
    addPath([from,to],group,value);
  });
  if(showIncome&&showExpenses){
    accountBalances.forEach(balance=>{
      const difference=balance.income+balance.transferIn-balance.expenses-balance.transferOut;
      if(Math.abs(difference)<.005)return;
      if(difference>0)addPath([
        balance.account,
        {id:`balance:${balance.account.id}:positive`,label:"Zeitraumueberschuss",group:"category",type:"balance",color:"#1f9d73"}
      ],[],difference);
      else addPath([
        {id:`balance:${balance.account.id}:negative`,label:"Aus Startbestand / Ruecklagen",group:balance.account.source==="sparkasse"?"primary-inflow":"secondary-inflow",type:"balance",color:"#f59e0b"},
        balance.account
      ],[],-difference);
    });
  }
  const transactionById=new Map(data.transactions.map(transaction=>[transaction.id,transaction]));
  return {
    nodes:[...nodes.values()].map(node=>({...node,transactions:[...node.transactions].map(id=>transactionById.get(id)).filter(Boolean)})),
    links:[...links.values()].map(link=>({...link,transactions:[...link.transactions].map(id=>transactionById.get(id)).filter(Boolean)}))
  };
}

function layoutSankey(graph){
  const groups=new Map();
  graph.nodes.forEach(node=>{if(!groups.has(node.group))groups.set(node.group,[]);groups.get(node.group).push(node)});
  graph.links.forEach(link=>{
    link.sourceNode=graph.nodes.find(node=>node.id===link.source);
    link.targetNode=graph.nodes.find(node=>node.id===link.target);
    link.sourceNode.outgoing=(link.sourceNode.outgoing||0)+link.value;
    link.targetNode.incoming=(link.targetNode.incoming||0)+link.value;
  });
  graph.nodes.forEach(node=>node.value=Math.max(node.incoming||0,node.outgoing||0));
  groups.forEach(nodes=>nodes.sort((a,b)=>b.value-a.value||a.label.localeCompare(b.label,"de")));
  const maxNodes=Math.max(...[...groups.values()].map(nodes=>nodes.length),1);
  const height=Math.max(640,maxNodes*24+105);
  const width=1200,nodeWidth=16,gap=10,top=55;
  const positions={"primary-inflow":25,"primary-account":245,"secondary-inflow":440,"secondary-account":650,"category":1170};
  let scale=Infinity;
  groups.forEach(nodes=>{
    const total=nodes.reduce((sum,node)=>sum+node.value,0);
    const available=height-top-30-gap*Math.max(0,nodes.length-1)-8*nodes.length;
    if(total)scale=Math.min(scale,Math.max(.02,available/total));
  });
  if(!Number.isFinite(scale))scale=1;
  groups.forEach((nodes,group)=>{
    const columnHeight=nodes.reduce((sum,node)=>sum+8+node.value*scale,0)+gap*Math.max(0,nodes.length-1);
    let y=Math.max(top,top+(height-top-30-columnHeight)/2);
    nodes.forEach(node=>{
      node.x=positions[group];
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
  return {width,height,groups};
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
  svg.setAttribute("viewBox",`0 0 ${layout.width} ${layout.height}`);
  svg.setAttribute("preserveAspectRatio","xMidYMid meet");
  const links=graph.links.map(link=>{
    const start=link.sourceNode.x+link.sourceNode.width,end=link.targetNode.x;
    const distance=end-start;
    const bend=Math.max(60,Math.abs(distance)*.48)*(distance>=0?1:-1);
    const path=`M ${start} ${link.sy} C ${start+bend} ${link.sy}, ${end-bend} ${link.ty}, ${end} ${link.ty}`;
    const selected=state.sankey.selected?.type==="link"&&state.sankey.selected.key===link.id;
    return `<path class="sankey-link ${selected?"selected":""}" data-link="${escapeHtml(link.id)}" d="${path}" stroke="${link.color}" stroke-width="${link.width}"/>`;
  }).join("");
  const titles=`<text class="sankey-column-title" x="25" y="25">EINGAENGE &amp; SPARKASSE</text><text class="sankey-column-title" x="570" y="25">N26 &amp; PAYPAL</text><text class="sankey-column-title" x="1170" y="25" text-anchor="end">KATEGORIEN &amp; SALDO</text>`;
  const nodes=graph.nodes.map(node=>{
    const rightSide=node.group==="category";
    const labelX=rightSide?node.x-8:node.x+node.width+8;
    const anchor=rightSide?"end":"start";
    const selected=state.sankey.selected?.type==="node"&&state.sankey.selected.key===node.id;
    return `<g class="sankey-node ${selected?"selected":""}" data-node="${escapeHtml(node.id)}">
      <rect x="${node.x}" y="${node.y}" width="${node.width}" height="${node.height}" rx="4" fill="${node.color}"/>
      <text x="${labelX}" y="${node.y+Math.min(13,node.height/2)}" text-anchor="${anchor}">${escapeHtml(shortLabel(node.label))}</text>
      <text class="node-value" x="${labelX}" y="${node.y+Math.min(27,node.height/2+14)}" text-anchor="${anchor}">${escapeHtml(money.format(node.value))}</text>
    </g>`;
  }).join("");
  svg.innerHTML=`${titles}${links}${nodes}`;
  qsa(".sankey-node").forEach(element=>{
    const node=graph.nodes.find(item=>item.id===element.dataset.node);
    element.addEventListener("click",event=>{
      event.stopPropagation();
      state.sankey.selected={type:"node",key:node.id};
      sankeyDetail(node);renderSankey();
    });
  });
  qsa(".sankey-link").forEach(element=>{
    const link=graph.links.find(item=>item.id===element.dataset.link);
    element.addEventListener("click",event=>{
      event.stopPropagation();
      state.sankey.selected={type:"link",key:link.id};
      sankeyDetail({...link,label:`${link.sourceNode.label} → ${link.targetNode.label}`});renderSankey();
    });
  });
  applySankeySearch();
  qs("#sankey-depth").textContent=state.sankey.selected?"Auswahl fixiert":"Konten und Kategorien";
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
  state.sankey.selected=null;
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
    state.sankey.selected=null;
    qs("#sankey-detail-title").textContent="Diagramm erkunden";
    qs("#sankey-detail").innerHTML='<p class="hint">Klicke einen Knoten oder Geldstrom an. Die Auswahl bleibt bestehen, bis du eine andere Stelle anklickst.</p>';
    renderSankey();
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

'use strict';
let research = null;
const $ = id => document.getElementById(id);
const fmtMoney = n => new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:2}).format(n);
const pct = n => `${n>0?'+':''}${n.toFixed(2)}%`;
const nice = n => n.toLocaleString('en-US',{maximumFractionDigits:2});
function setText(id,value){$(id).textContent=value;}
function setColor(id,val){$(id).classList.toggle('positive',val>0);$(id).classList.toggle('negative',val<0);}
function draw(id,rows,keys,colors,area=false){
 const canvas=$(id); if(!canvas||!rows.length)return;
 const cssWidth=canvas.getBoundingClientRect().width||700;
 const cssHeight=Number(canvas.getAttribute('height'));
 const dpr=Math.min(window.devicePixelRatio||1,2);
 canvas.width=Math.round(cssWidth*dpr);canvas.height=Math.round(cssHeight*dpr);
 const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);
 const p={l:62,r:15,t:18,b:33},w=cssWidth-p.l-p.r,h=cssHeight-p.t-p.b;
 const vals=rows.flatMap(r=>keys.map(k=>r[k]));let lo=Math.min(...vals),hi=Math.max(...vals);
 if(Math.abs(hi-lo)<1e-8){lo-=1;hi+=1}else{const space=(hi-lo)*.10;lo-=space;hi+=space;}
 const y=v=>p.t+(hi-v)/(hi-lo)*h,x=i=>p.l+(i/(rows.length-1))*w;
 ctx.font='10px system-ui';ctx.textBaseline='middle';ctx.strokeStyle='#26364c';ctx.fillStyle='#7b90aa';ctx.lineWidth=1;
 for(let i=0;i<5;i++){const v=lo+(hi-lo)*i;const yy=y(v);ctx.beginPath();ctx.moveTo(p.l,yy);ctx.lineTo(p.l+w,yy);ctx.stroke();ctx.textAlign='right';ctx.fillText(area?v.toFixed(1)+'%':v>=1000?(v/1000).toFixed(0)+'k':v.toFixed(0),p.l-12,yy);}
 [0,.25,.5,.75,1].forEach(t=>{const i=Math.floor(t*(rows.length-1));ctx.textAlign='center';ctx.fillText(rows[i].date.slice(0,7),x(i),cssHeight-10)});
 keys.forEach((key,idx)=>{ctx.strokeStyle=colors[idx];ctx.lineWidth=2;ctx.beginPath();rows.forEach((row,i)=>{if(i===0)ctx.moveTo(x(i),y(row[key]));else ctx.lineTo(x(i),y(row[key]))});ctx.stroke();});
}
function update(result){
 research=result;const m=result.metrics;
 setText('m-equity',fmtMoney(m.equity));setText('m-return',pct(m.total_return));setText('m-sharpe',nice(m.sharpe));setText('m-drawdown',pct(m.max_drawdown));
 setColor('m-return',m.total_return);setColor('m-drawdown',m.max_drawdown);
 setText('s-annual',pct(m.annual_return));setText('s-vol',m.volatility.toFixed(2)+'%');setText('s-trades',m.trades);
 setText('r-var',m.var95.toFixed(2)+'%');setText('r-es',m.expected_shortfall95.toFixed(2)+'%');setText('r-vol',m.volatility.toFixed(2)+'%');
 const s=result.current_signal;
 setText('signal-state',s.position===0?'FLAT / NO EXPOSURE':s.position>0?'LONG SPREAD':'SHORT SPREAD');
 setText('signal-z',s.z_score.toFixed(2));setText('signal-position',s.position===0?'FLAT':s.position>0?'+1 / LONG':'−1 / SHORT');
 const tbody=$('trades-table');tbody.replaceChildren();
 for(const t of result.recent_trades){const tr=document.createElement('tr');for(const [v,cl] of [[t.date,''],[t.action,'action'],[t.z.toFixed(2),''],[fmtMoney(t.cost),''],[String(t.position),'']]){const td=document.createElement('td');td.textContent=v;if(cl)td.className=cl;tr.append(td)}tbody.append(tr)}
 for(const id of ['equity-chart','strategy-chart'])draw(id,result.curve,['equity','benchmark'],['#58d5ad','#6c9cfa']);
 draw('drawdown-chart',result.curve,['drawdown'],['#f58c94'],true);
}
async function runBacktest(params=''){
 const req=await fetch('/api/backtest'+params);const json=await req.json();if(!req.ok)throw new Error(typeof json.detail==='string'?json.detail:'Invalid model parameters');update(json);
}
async function runOption(params=''){
 const req=await fetch('/api/options'+params);const json=await req.json();if(!req.ok)throw new Error(typeof json.detail==='string'?json.detail:'Invalid option parameters');
 setText('option-price',fmtMoney(json.price));for(const k of ['delta','gamma','vega','theta','rho'])setText('g-'+k,String(json[k]));
}
function formQuery(form){return '?'+new URLSearchParams(new FormData(form)).toString()}
document.querySelectorAll('.nav').forEach(btn=>btn.addEventListener('click',()=>{
 document.querySelectorAll('.nav').forEach(x=>x.classList.toggle('active',x===btn));
 document.querySelectorAll('.page').forEach(x=>x.classList.toggle('active',x.id==='page-'+btn.dataset.page));
 setText('crumb',btn.dataset.page.toUpperCase());history.replaceState(null,'','#'+btn.dataset.page);
 if(research)requestAnimationFrame(()=>update(research));
}));
$('backtest-form').addEventListener('submit',async e=>{e.preventDefault();const error=$('backtest-error');error.hidden=true;try{await runBacktest(formQuery(e.target));}catch(ex){error.textContent=ex.message;error.hidden=false}});
$('options-form').addEventListener('submit',async e=>{e.preventDefault();const error=$('options-error');error.hidden=true;try{await runOption(formQuery(e.target));}catch(ex){error.textContent=ex.message;error.hidden=false}});
window.addEventListener('resize',()=>{if(research)update(research)});
(async()=>{try{await Promise.all([runBacktest(),runOption()])}catch(ex){$('backtest-error').textContent=ex.message;$('backtest-error').hidden=false}const page=location.hash.slice(1);if(page){const nav=document.querySelector(`.nav[data-page="${CSS.escape(page)}"]`);if(nav)nav.click()}})();

// === Live paper trading mode ===
// Strictly read-only UI; paper orders are submitted by a separate private
// server-side worker only when explicitly enabled by a deployment operator.
const liveSymbols=['SPY','QQQ','IWM','USO'];
const liveNow = str => {
 if(!str)return '—';
 const date=new Date(str);
 return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('en-US',{dateStyle:'short',timeStyle:'short',timeZone:'America/New_York'})+' ET';
};
function liveTable(id,rows,keys){
 const tbody=$(id);tbody.replaceChildren();
 if(!rows.length){const tr=document.createElement('tr');const td=document.createElement('td');td.colSpan=keys.length;td.textContent='No broker records available.';tr.append(td);tbody.append(tr);return;}
 for(const row of rows){const tr=document.createElement('tr');for(const get of keys){const td=document.createElement('td');td.textContent=get(row);tr.append(td)}tbody.append(tr)}
}
function readNumber(v){const n=Number(v);return Number.isFinite(n)?n:null}
function renderLive(value){
 const connected=Boolean(value.connected);
 const marketOpen=Boolean(value.market?.is_open);
 const active=connected&&marketOpen;
 setText('live-top-status',active?'PAPER MARKET OPEN':connected?'PAPER MARKET CLOSED':'LIVE FEED NOT CONNECTED');
 setText('live-mode',value.mode||'NOT CONNECTED');
 setText('live-market-status',!connected?'Broker not connected':marketOpen?'US MARKET OPEN · LIVE PAPER':'US MARKET CLOSED · PAPER ACCOUNT');
 $('live-dot').classList.toggle('on',active);
 setText('live-asof',connected?'Refreshed '+liveNow(value.updated_at):'No live data received');
 const account=value.account;
 setText('live-equity',account?.equity!=null?fmtMoney(account.equity):'—');
 setText('live-cash',account?.cash!=null?fmtMoney(account.cash):'—');
 const positions=value.positions||[];
 const pnl=connected?positions.reduce((sum,pos)=>sum+(readNumber(pos.unrealized_pl)||0),0):null;
 setText('live-pnl',pnl!==null?fmtMoney(pnl):'—');
 if(pnl!==null)setColor('live-pnl',pnl);
 setText('live-auto',value.auto_trading?'ON':'OFF');
 $('live-auto').classList.toggle('positive',Boolean(value.auto_trading));
 $('live-auto').classList.toggle('negative',!value.auto_trading);
 for(const symbol of liveSymbols){
   const quote=(value.quotes||[]).find(q=>q.symbol===symbol);
   setText('quote-'+symbol,quote?.price!=null?fmtMoney(quote.price):'—');
   setText('quote-t-'+symbol,quote?.observed_at?(quote.fresh?'LIVE IEX · ':'LAST IEX TRADE · ')+liveNow(quote.observed_at):'No authenticated quote received');
 }
 const bot=value.bot||{};
 setText('live-signal',bot.signal||'WAITING');
 setText('live-scan',liveNow(bot.last_scan));
 setText('live-action',liveNow(bot.last_action));
 setText('live-bot-detail',bot.last_error?'ERROR: '+bot.last_error:(bot.detail||'Private paper strategy is disabled until explicitly enabled.'));
 setText('live-positions-count',positions.length+' POSITION'+(positions.length===1?'':'S'));
 liveTable('live-positions-table',positions,[p=>p.symbol||'—',p=>p.qty||'—',p=>p.current_price?fmtMoney(Number(p.current_price)):'—',p=>p.unrealized_pl?fmtMoney(Number(p.unrealized_pl)):'—']);
 liveTable('live-orders-table',value.orders||[],[o=>liveNow(o.filled_at||o.submitted_at),o=>o.symbol||'—',o=>(o.side||'—').toUpperCase(),o=>(o.status||'—').toUpperCase()]);
 const hist=value.equity_history||[];
 $('live-chart-placeholder').hidden=hist.length>=2;
 $('live-equity-chart').hidden=hist.length<2;
 if(hist.length>=2 && $('page-live').classList.contains('active'))draw('live-equity-chart',hist,['equity'],['#58d5ad']);
 if(hist.length<2)setText('live-chart-placeholder',connected?'Not enough broker equity observations yet to plot a curve.':'A real paper account must be connected to show its performance history.');
 setText('live-connection-title',connected?'Live paper account connected':'Alpaca connection '+(value.configured?'unavailable':'not configured'));
 setText('live-connection-message',value.message||'No status available');
 if(connected){
  $('live-global-notice').innerHTML='<span>◉</span> <strong>REAL MARKET DATA / PAPER EXECUTION</strong> — Live prices are sourced from the limited IEX feed. Account and orders reflect Alpaca PAPER simulation, not real-money executions. Backtests are separate.';
 }else{
  $('live-global-notice').innerHTML='<span>◉</span> <strong>NO LIVE BROKER CONNECTION</strong> — No market quotes or paper portfolio metrics are fabricated. Connect Alpaca Paper credentials to enable this panel.';
 }
}
async function updateLive(){
 try{
  const response=await fetch('/api/live',{cache:'no-store'});
  if(!response.ok)throw Error('Backend temporarily unavailable');
  renderLive(await response.json());
 }catch(ex){
  renderLive({mode:'OFFLINE',connected:false,configured:false,auto_trading:false,quotes:[],orders:[],positions:[],equity_history:[],message:'Live backend unavailable ('+ex.message+'). No fake data shown.'});
 }
}
updateLive();
window.setInterval(updateLive,15000);

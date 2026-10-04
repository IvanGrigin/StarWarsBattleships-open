(() => {
  "use strict";

  const canvas = document.getElementById("battlefield");
  const ctx = canvas.getContext("2d");
  const viewport = document.getElementById("viewport");
  const allianceImage = new Image();
  const imperialImage = new Image();
  allianceImage.src = "assets/alliance-fighter.png";
  imperialImage.src = "assets/imperial-interceptor.png";

  const DIRS = [[1,0],[1,-1],[0,-1],[-1,0],[-1,1],[0,1]];
  const BOARD_RADIUS = 4;
  const MAX_ROUNDS = 12;
  const cells = [];
  for (let q = -BOARD_RADIUS; q <= BOARD_RADIUS; q++) {
    const r1 = Math.max(-BOARD_RADIUS, -q - BOARD_RADIUS);
    const r2 = Math.min(BOARD_RADIUS, -q + BOARD_RADIUS);
    for (let r = r1; r <= r2; r++) cells.push({q, r, key: `${q},${r}`});
  }

  let ships, activeId, phase, energy, round, cameraStep, attackMode, particles, logItems, animating;

  function initialShips() {
    return [
      {id:"a1", team:"alliance", name:"ВЕДУЩИЙ «РОГ-1»", pilot:"Капитан Арден", className:"ШТУРМОВОЙ ИСТРЕБИТЕЛЬ", q:-2, r:4, dir:2, hull:5, maxHull:5, shields:2, maxShields:2, acted:false},
      {id:"a2", team:"alliance", name:"ЗВЕНО «ЭХО-3»", pilot:"Лейтенант Кес", className:"ТАКТИЧЕСКИЙ ИСТРЕБИТЕЛЬ", q:0, r:4, dir:2, hull:4, maxHull:4, shields:3, maxShields:3, acted:false},
      {id:"a3", team:"alliance", name:"РАЗВЕДЧИК «СЕЙБР»", pilot:"Офицер Тал", className:"РАЗВЕДЧИК", q:2, r:2, dir:2, hull:4, maxHull:4, shields:2, maxShields:2, acted:false},
      {id:"i1", team:"imperial", name:"ОХОТНИК «ЧЁРНЫЙ-1»", pilot:"ИИ: приоритет огня", className:"ПЕРЕХВАТЧИК", q:2, r:-4, dir:5, hull:4, maxHull:4, shields:1, maxShields:1, acted:false},
      {id:"i2", team:"imperial", name:"ЗВЕНО «ОНИКС-2»", pilot:"ИИ: перехват", className:"ЛИНЕЙНЫЙ ИСТРЕБИТЕЛЬ", q:0, r:-4, dir:5, hull:4, maxHull:4, shields:1, maxShields:1, acted:false},
      {id:"i3", team:"imperial", name:"ОХОТНИК «ВЕКТОР»", pilot:"ИИ: фланговый манёвр", className:"ПЕРЕХВАТЧИК", q:-2, r:-2, dir:5, hull:3, maxHull:3, shields:2, maxShields:2, acted:false}
    ];
  }

  function resetGame() {
    ships = initialShips(); activeId = null; phase = "player"; energy = 3; round = 1; cameraStep = 0;
    attackMode = false; particles = []; animating = false;
    logItems = [
      {text:"Тактическая сеть синхронизирована.", type:"system"},
      {text:"ИИ противника занял исходные позиции.", type:""},
      {text:"Выберите любой <b>голубой корабль</b>.", type:"system"}
    ];
    document.getElementById("resultModal").classList.add("hidden");
    updateUI(); draw();
  }

  function activeShip() { return ships.find(s => s.id === activeId && s.hull > 0); }
  function alive(team) { return ships.filter(s => s.team === team && s.hull > 0); }
  function at(q, r) { return ships.find(s => s.hull > 0 && s.q === q && s.r === r); }
  function distance(a, b) { return (Math.abs(a.q-b.q) + Math.abs(a.q+a.r-b.q-b.r) + Math.abs(a.r-b.r)) / 2; }

  function addLog(text, type="") {
    logItems.unshift({text, type});
    logItems = logItems.slice(0, 8);
    updateLog();
  }

  function toast(message) {
    const el = document.getElementById("toast"); el.textContent = message; el.classList.add("show");
    clearTimeout(toast.timer); toast.timer = setTimeout(() => el.classList.remove("show"), 1600);
  }

  function axialToWorld(q, r) {
    const angle = cameraStep * Math.PI / 3;
    const x0 = Math.sqrt(3) * (q + r / 2);
    const y0 = 1.5 * r;
    return {x: x0 * Math.cos(angle) - y0 * Math.sin(angle), y: (x0 * Math.sin(angle) + y0 * Math.cos(angle)) * 0.62};
  }

  function metrics() {
    const w = viewport.clientWidth, h = viewport.clientHeight;
    const size = Math.min(w / 15.7, h / 10.8) * (w < 600 ? 1.12 : 1);
    return {w, h, size, cx: w * (w < 900 ? .5 : .49), cy: h * .51};
  }

  function screenPos(q, r) {
    const m = metrics(), p = axialToWorld(q, r);
    return {x: m.cx + p.x * m.size, y: m.cy + p.y * m.size, scale: .88 + p.y * .012};
  }

  function hexPath(x, y, size, offsetY=0) {
    ctx.beginPath();
    for (let i=0; i<6; i++) {
      const a = Math.PI/180 * (60*i - 30);
      const px = x + size * Math.cos(a), py = y + offsetY + size * .62 * Math.sin(a);
      if (i===0) ctx.moveTo(px,py); else ctx.lineTo(px,py);
    }
    ctx.closePath();
  }

  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const rect = viewport.getBoundingClientRect();
    canvas.width = Math.round(rect.width * dpr); canvas.height = Math.round(rect.height * dpr);
    canvas.style.width = `${rect.width}px`; canvas.style.height = `${rect.height}px`;
    ctx.setTransform(dpr,0,0,dpr,0,0); draw();
  }

  function draw() {
    const m = metrics(); ctx.clearRect(0,0,m.w,m.h);
    const ordered = [...cells].sort((a,b) => axialToWorld(a.q,a.r).y - axialToWorld(b.q,b.r).y);
    const active = activeShip();
    for (const c of ordered) {
      const p = screenPos(c.q,c.r), s = m.size * .91;
      const occup = at(c.q,c.r);
      const isForward = active && phase==="player" && !attackMode && c.q===active.q+DIRS[active.dir][0] && c.r===active.r+DIRS[active.dir][1] && !occup && energy>=1;
      const isTarget = active && attackMode && occup && occup.team!==active.team && distance(active,occup)<=3;
      hexPath(p.x, p.y, s, 7);
      ctx.fillStyle = "rgba(0,3,8,.72)"; ctx.fill();
      hexPath(p.x,p.y,s,0);
      const grad = ctx.createLinearGradient(p.x,p.y-s*.6,p.x,p.y+s*.6);
      grad.addColorStop(0, isForward ? "rgba(48,174,215,.28)" : isTarget ? "rgba(255,68,58,.28)" : "rgba(17,45,66,.43)");
      grad.addColorStop(1, "rgba(4,15,25,.76)");
      ctx.fillStyle=grad; ctx.fill();
      ctx.strokeStyle = isForward ? "rgba(85,221,255,.9)" : isTarget ? "rgba(255,90,82,.95)" : "rgba(74,132,164,.31)";
      ctx.lineWidth = isForward || isTarget ? 1.8 : 1; ctx.stroke();
      if (isForward || isTarget) {
        hexPath(p.x,p.y,s*.78,0); ctx.strokeStyle = isTarget ? "rgba(255,90,82,.35)" : "rgba(85,221,255,.35)"; ctx.stroke();
      }
    }

    for (const ship of ships.filter(s=>s.hull>0).sort((a,b)=>screenPos(a.q,a.r).y-screenPos(b.q,b.r).y)) drawShip(ship, m);
    drawParticles();
  }

  function drawShip(ship, m) {
    const p=screenPos(ship.q,ship.r), selected=ship.id===activeId, hostile=ship.team==="imperial";
    const color=hostile?"#ff5a52":"#55ddff", img=hostile?imperialImage:allianceImage;
    ctx.save(); ctx.translate(p.x,p.y-7);
    ctx.beginPath(); ctx.ellipse(0,13,m.size*.43,m.size*.18,0,0,Math.PI*2); ctx.fillStyle="rgba(0,0,0,.64)"; ctx.fill();
    ctx.beginPath(); ctx.arc(0,0,m.size*(selected?.48:.38),0,Math.PI*2); ctx.strokeStyle=color; ctx.globalAlpha=selected?.9:.28; ctx.lineWidth=selected?2:1; ctx.stroke();
    if(selected){ ctx.shadowColor=color; ctx.shadowBlur=18; ctx.stroke(); ctx.shadowBlur=0; }
    ctx.globalAlpha=ship.acted?.46:1;
    ctx.rotate((ship.dir-cameraStep)*Math.PI/3 + Math.PI);
    const shipSize=m.size*(hostile?.98:1.08);
    if(img.complete) { ctx.shadowColor=color; ctx.shadowBlur=hostile?7:10; ctx.drawImage(img,-shipSize/2,-shipSize/2,shipSize,shipSize); }
    ctx.restore();
    const barW=m.size*.72, barX=p.x-barW/2, barY=p.y-m.size*.66;
    ctx.fillStyle="rgba(0,0,0,.78)"; ctx.fillRect(barX,barY,barW,4);
    ctx.fillStyle=ship.hull/ship.maxHull<.4?"#ff5a52":"#f7c948"; ctx.fillRect(barX,barY,barW*ship.hull/ship.maxHull,2);
    ctx.fillStyle="#55ddff"; ctx.fillRect(barX,barY+2,barW*ship.shields/Math.max(1,ship.maxShields),2);
  }

  function drawParticles() {
    for (const p of particles) {
      const from=screenPos(p.from.q,p.from.r), to=screenPos(p.to.q,p.to.r), t=Math.min(1,(performance.now()-p.started)/340);
      ctx.save(); ctx.globalAlpha=1-t*.75; ctx.strokeStyle=p.color; ctx.lineWidth=3; ctx.shadowColor=p.color; ctx.shadowBlur=14;
      ctx.beginPath(); ctx.moveTo(from.x,from.y); ctx.lineTo(from.x+(to.x-from.x)*t,from.y+(to.y-from.y)*t); ctx.stroke(); ctx.restore();
    }
    particles=particles.filter(p=>performance.now()-p.started<420);
    if(particles.length) requestAnimationFrame(draw);
  }

  function pickCell(x,y) {
    const m=metrics(); let best=null, bestD=Infinity;
    for(const c of cells){const p=screenPos(c.q,c.r), d=Math.hypot(x-p.x,(y-p.y)/.62); if(d<bestD){bestD=d;best=c;}}
    return bestD<m.size*.92?best:null;
  }

  function handleBoard(e) {
    if(phase!=="player"||animating) return;
    const rect=canvas.getBoundingClientRect(); const point=e.touches?e.touches[0]:e;
    const cell=pickCell(point.clientX-rect.left,point.clientY-rect.top); if(!cell)return;
    const target=at(cell.q,cell.r), active=activeShip();
    if(target?.team==="alliance"&&!target.acted){ selectShip(target); return; }
    if(!active){ toast("СНАЧАЛА ВЫБЕРИТЕ КОРАБЛЬ"); return; }
    if(attackMode){
      if(target?.team==="imperial"&&distance(active,target)<=3) playerAttack(target);
      else toast("ЦЕЛЬ ВНЕ СЕКТОРА ОГНЯ");
      return;
    }
    const f=DIRS[active.dir]; if(cell.q===active.q+f[0]&&cell.r===active.r+f[1]&&!target) performAction("forward");
  }

  function selectShip(ship) {
    activeId=ship.id; energy=3; attackMode=false; addLog(`<b>${ship.name}</b> выходит на канал.`,"system"); updateUI(); draw();
  }

  function performAction(action) {
    const ship=activeShip(); if(!ship||phase!=="player"||animating){ if(!ship)toast("ВЫБЕРИТЕ КОРАБЛЬ"); return; }
    const cost=action==="attack"?2:action==="end"?0:1;
    if(energy<cost){toast("НЕДОСТАТОЧНО ЭНЕРГИИ");return;}
    if(action==="left"||action==="right"){
      ship.dir=(ship.dir+(action==="left"?5:1))%6; energy--; attackMode=false; addLog(`${ship.name}: разворот на 60°.`); draw();
    } else if(action==="forward"){
      const d=DIRS[ship.dir], nq=ship.q+d[0], nr=ship.r+d[1];
      if(!cells.some(c=>c.q===nq&&c.r===nr)){toast("ГРАНИЦА ОПЕРАЦИОННОЙ ЗОНЫ");return;}
      if(at(nq,nr)){toast("МАРШРУТ ЗАБЛОКИРОВАН");return;}
      ship.q=nq; ship.r=nr; energy--; attackMode=false; addLog(`${ship.name}: полный вперёд.`); draw();
    } else if(action==="attack"){
      attackMode=!attackMode; if(attackMode)toast("ВЫБЕРИТЕ КРАСНУЮ ЦЕЛЬ"); draw();
    } else if(action==="end") endPlayerActivation();
    updateUI();
  }

  function playerAttack(target){
    const ship=activeShip(); energy-=2; attackMode=false; resolveHit(ship,target); updateUI();
    if(!checkEnd()&&energy===0) setTimeout(endPlayerActivation,420);
  }

  function resolveHit(attacker,target){
    const range=distance(attacker,target), damage=range===1?2:1;
    particles.push({from:{q:attacker.q,r:attacker.r},to:{q:target.q,r:target.r},color:attacker.team==="alliance"?"#55ddff":"#ff5a52",started:performance.now()});
    let left=damage, absorbed=Math.min(target.shields,left); target.shields-=absorbed; left-=absorbed; target.hull=Math.max(0,target.hull-left);
    addLog(`<b>${attacker.name}</b> → ${target.name}: ${damage} урон.`,"hit");
    if(target.hull===0)addLog(`<b>${target.name}</b> уничтожен.`,"hit");
    draw(); updateUI(); setTimeout(draw,360);
  }

  function endPlayerActivation(){
    const ship=activeShip(); if(!ship||phase!=="player"||animating)return;
    ship.acted=true; activeId=null; attackMode=false; phase="ai"; animating=true; updateUI();
    setTimeout(aiTurn,600);
  }

  function aiTurn(){
    const candidates=alive("imperial").filter(s=>!s.acted); const targets=alive("alliance");
    if(!candidates.length){finishRound();return;}
    const bot=candidates.sort((a,b)=>Math.min(...targets.map(t=>distance(a,t)))-Math.min(...targets.map(t=>distance(b,t))))[0];
    activeId=bot.id; let budget=3; const target=targets.sort((a,b)=>distance(bot,a)-distance(bot,b))[0];
    phase="ai"; updateUI(); addLog(`<b>${bot.name}</b>: вычисляет траекторию.`);
    const step=()=>{
      if(checkEnd())return;
      const range=distance(bot,target);
      if(range<=3&&budget>=2){ budget-=2; energy=budget; resolveHit(bot,target); setTimeout(()=>{bot.acted=true; activeId=null; animating=false; returnToPlayer();},520); return; }
      if(budget<=0){bot.acted=true;activeId=null;animating=false;returnToPlayer();return;}
      const choices=DIRS.map((d,i)=>({i,q:bot.q+d[0],r:bot.r+d[1]})).filter(c=>cells.some(x=>x.q===c.q&&x.r===c.r)&&!at(c.q,c.r));
      const best=choices.sort((a,b)=>distance(a,target)-distance(b,target))[0];
      if(best){ bot.dir=best.i; bot.q=best.q; bot.r=best.r; budget--; energy=budget; addLog(`${bot.name}: сближение.`); draw(); updateUI(); setTimeout(step,360); }
      else {bot.acted=true;activeId=null;animating=false;returnToPlayer();}
    }; setTimeout(step,420);
  }

  function returnToPlayer(){
    if(checkEnd())return;
    if(alive("alliance").some(s=>!s.acted)){phase="player";energy=3;updateUI();toast("ВАШ ХОД · ВЫБЕРИТЕ ЗВЕНО");draw();}
    else if(alive("imperial").some(s=>!s.acted)){animating=true;setTimeout(aiTurn,400);}
    else finishRound();
  }

  function finishRound(){
    round++; if(round>MAX_ROUNDS){showResult(false,"Время операции истекло. Сектор удерживает Империя.");return;}
    ships.filter(s=>s.hull>0).forEach(s=>{s.acted=false;s.shields=Math.min(s.maxShields,s.shields+1);});
    phase="player";activeId=null;energy=3;animating=false;addLog(`<b>Раунд ${String(round).padStart(2,"0")}</b>: щиты восстановлены.`,"system");updateUI();draw();
  }

  function checkEnd(){
    if(!alive("imperial").length){showResult(true,"Имперское соединение разгромлено. Гиперкоридор свободен.");return true;}
    if(!alive("alliance").length){showResult(false,"Эскадрилья Альянса потеряна. Перестройте тактику и повторите операцию.");return true;}
    return false;
  }

  function showResult(win,text){phase="done";animating=false;document.getElementById("resultTitle").textContent=win?"ПОБЕДА":"ПОРАЖЕНИЕ";document.getElementById("resultText").textContent=text;document.getElementById("resultModal").classList.remove("hidden");}

  function updateUI(){
    const ship=activeShip(); const player=phase==="player";
    document.getElementById("roundValue").textContent=String(round).padStart(2,"0");
    document.getElementById("turnTitle").textContent=player?"ВАШ ХОД":phase==="ai"?"ХОД ПРОТИВНИКА":"ОПЕРАЦИЯ ЗАВЕРШЕНА";
    document.getElementById("turnSubtitle").textContent=player?(ship?"Командуйте выбранным звеном":"Выберите корабль Альянса"):"Тактический ИИ выполняет манёвр";
    const mark=document.getElementById("turnMark"); mark.textContent=player?"A":"I";mark.className=`faction-mark ${player?"alliance":"imperial"}`;
    document.getElementById("shipName").textContent=ship?ship.name:"Выберите звено";
    document.getElementById("pilotName").textContent=ship?ship.pilot:"Тактический канал ожидает";
    document.getElementById("shipClass").textContent=ship?ship.className:"НЕТ СИГНАЛА";
    const portrait=document.getElementById("shipPortrait");portrait.src=ship?.team==="imperial"?"assets/imperial-interceptor.png":"assets/alliance-fighter.png";
    document.getElementById("hullMeter").style.width=ship?`${ship.hull/ship.maxHull*100}%`:"0";
    document.getElementById("shieldMeter").style.width=ship?`${ship.shields/Math.max(1,ship.maxShields)*100}%`:"0";
    document.getElementById("hullValue").textContent=ship?`${ship.hull}/${ship.maxHull}`:"—";
    document.getElementById("shieldValue").textContent=ship?`${ship.shields}/${ship.maxShields}`:"—";
    [...document.querySelectorAll("#energyPips i")].forEach((p,i)=>p.classList.toggle("off",!ship||i>=energy));
    document.querySelectorAll(".action-button").forEach(b=>{const a=b.dataset.action,cost=a==="attack"?2:a==="end"?0:1;b.disabled=!player||!ship||energy<cost;b.classList.toggle("active",a==="attack"&&attackMode);});
    updateLog();
  }

  function updateLog(){document.getElementById("combatLog").innerHTML=logItems.map(x=>`<div class="log-item ${x.type}">${x.text}</div>`).join("");}
  function rotateCamera(delta){cameraStep=(cameraStep+delta+6)%6;document.getElementById("cameraValue").textContent=String(30+cameraStep*60).padStart(3,"0")+"°";draw();}

  canvas.addEventListener("click",handleBoard);
  document.querySelectorAll(".action-button").forEach(b=>b.addEventListener("click",()=>performAction(b.dataset.action)));
  document.getElementById("cameraLeft").addEventListener("click",()=>rotateCamera(-1));
  document.getElementById("cameraRight").addEventListener("click",()=>rotateCamera(1));
  document.getElementById("resetButton").addEventListener("click",resetGame);
  document.getElementById("playAgain").addEventListener("click",resetGame);
  window.addEventListener("keydown",e=>{
    if(e.key.toLowerCase()==="q")rotateCamera(-1);else if(e.key.toLowerCase()==="e")rotateCamera(1);
    else if(["1","2","3","4","5"].includes(e.key))performAction(["left","forward","right","attack","end"][+e.key-1]);
  });
  window.addEventListener("resize",resize);
  allianceImage.onload=draw;imperialImage.onload=draw;
  resetGame(); resize();
})();

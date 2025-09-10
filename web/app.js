function showTab(id){ document.querySelectorAll(".tab").forEach(t=>t.style.display="none"); document.getElementById("tab-"+id).style.display="block"; }

/* ---------- AI ---------- */
function loadAI(){
  fetch("/api/ai/clusters").then(r=>r.json()).then(d=>{
    let div=document.getElementById("ai-clusters"); div.innerHTML="";
    (d.clusters||[]).forEach(cl=>{
      let b=document.createElement("button"); b.innerText=cl.label||cl.name||cl.key;
      b.onclick=()=>fetch("/api/ai/select",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({cluster:cl.key})});
      div.appendChild(b);
    });
  });
}
function aiSetColor(){
  let hex=document.getElementById("ai_color").value;
  fetch("/api/ai/color",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({enabled:true,hex})});
}

/* ---------- Band ---------- */
function loadBand(){
  fetch("/api/band/clusters").then(r=>r.json()).then(d=>{
    let div=document.getElementById("band-clusters"); div.innerHTML="";
    (d.clusters||[]).forEach(cl=>{
      let b=document.createElement("button"); b.innerText=cl.label||cl.name||cl.key;
      b.onclick=()=>fetch("/api/band/select",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({cluster:cl.key})});
      div.appendChild(b);
    });
    // palette dropdown (vullen vanuit COLORS via state)
    fetch("/api/state").then(r=>r.json()).then(st=>{
      const pal=document.getElementById("band_palette"); pal.innerHTML="";
      Object.keys(st && st.colors || {}).forEach(k=>{ let o=document.createElement("option"); o.value=k; o.text=k; pal.appendChild(o); });
    });
  });
}
function bandSetColor(){
  let hex=document.getElementById("band_color").value;
  fetch("/api/band/color",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({enabled:true,hex})});
}
function bandSetAccent(){
  let hex=document.getElementById("band_accent").value;
  let pct=parseInt(document.getElementById("band_accent_pct").value||"10",10);
  fetch("/api/band/color",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({accent:{enabled:true,hex,pct}})});
}
function bandPresetSave(){
  let target = document.getElementById('band-target').value;
  fetch('/api/band/preset/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target})});
}
function bandPresetLoad(){
  let target = document.getElementById('band-target').value;
  fetch('/api/band/preset/load',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target})});
}

/* ---------- Manual (groups) ---------- */
function setMode(m){ fetch('/api/mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:m})}); }
function setLevel(control,val){ fetch('/api/levels',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({control,value:parseInt(val,10)})}); }
function setParam(control,val){ fetch('/api/params',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({control,value:parseInt(val,10)})}); }
function effect(target,fx){ fetch('/api/effects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target,fx})}); }
function tubeSet(key,val){
  if(key==='pattern'){ effect('tube_dmx',val); }
  else { /* snelheid/strobe lopen mee met engine; optioneel extra endpoint maken */ }
}
function wledColor(target,hex){
  // transport via ai color lock (snelle visuele update)
  fetch('/api/ai/color',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:true,hex})})
  .then(()=> effect(target, document.getElementById(target==='wled_tubes'?'wled_tubes_fx':'guir_fx').value || 'Solid'));
}
let stroboHeld=false; function stroboMomentary(){ stroboHeld=true; fetch('/api/strobo_dmx',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({momentary:true})}); }
function stroboRelease(){ stroboHeld=false; }

/* ---------- Manual (group presets) ---------- */
function loadGroupPresets(){ updatePresetNames(); document.getElementById('gp-group').onchange=updatePresetNames; }
function updatePresetNames(){
  const gp={
    "moving_head":["MH_Narrow_White","MH_Warm_Soft","MH_Red_Beam","MH_Blue_Cone"],
    "scanner":["Scan_Beam_Red","Scan_Dot_Magenta"],
    "moving_par":["MPAR_Warm_Key","MPAR_White_Key"],
    "pars_big":["PAR_Warm_Wash","PAR_Gold_Wash"],
    "pars_small":["PAR_Cool_Wash"],
    "wash_fx":["Wash_Strobe_60","Wash_Soft"]
  };
  const g=document.getElementById('gp-group').value;
  const sel=document.getElementById('gp-name'); sel.innerHTML="";
  (gp[g]||[]).forEach(n=>{ let o=document.createElement('option'); o.value=n; o.text=n; sel.appendChild(o); });
}
function applyGroupPreset(){
  const group=document.getElementById('gp-group').value;
  const name=document.getElementById('gp-name').value;
  fetch('/api/preset/apply_group',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({group,name})});
}

/* ---------- Manual (per fixture) ---------- */
let FIX_CACHE=[];
function manualInit(){
  fetch('/api/fixtures').then(r=>r.json()).then(j=>{
    FIX_CACHE=j.fixtures||[];
    let sel=document.getElementById('man-fixture'); sel.innerHTML="";
    FIX_CACHE.forEach(f=>{ let o=document.createElement('option'); o.value=f.name; o.text=f.name; sel.appendChild(o); });
    sel.onchange=onFixtureChange; onFixtureChange();
    // ook de Fixtures-tab dropdown vullen
    const fxsel=document.getElementById('fixture-select'); if(fxsel){ fxsel.innerHTML=""; FIX_CACHE.forEach(f=>{ let o=document.createElement('option'); o.value=f.name; o.text=f.name; fxsel.appendChild(o); });}
  });
}
function onFixtureChange(){
  let name=document.getElementById('man-fixture').value;
  let fx=FIX_CACHE.find(x=>x.name===name); if(!fx) return; let c=fx.caps;
  document.getElementById('ctl-pan').style.display   = c.pan  ? '' : 'none';
  document.getElementById('ctl-tilt').style.display  = c.tilt ? '' : 'none';
  document.getElementById('ctl-dim').style.display   = c.dim  ? '' : 'none';
  document.getElementById('ctl-stb').style.display   = c.strobe ? '' : 'none';
  document.getElementById('ctl-rgb').style.display   = (c.rgb||c.w) ? '' : 'none';
  document.getElementById('ctl-w').style.display     = c.w ? '' : 'none';
  document.getElementById('ctl-hex').style.display   = c.rgb ? '' : 'none';
  document.getElementById('ctl-gobo').style.display  = c.gobo ? '' : 'none';
  document.getElementById('man-caps').innerText =
    `pan:${c.pan} tilt:${c.tilt} dim:${c.dim} strobe:${c.strobe} color:${c.color} gobo:${c.gobo} rgb:${c.rgb} w:${c.w}`;
  let gsel=document.getElementById('fx-gobo'); gsel.innerHTML="";
  (fx.gobo_choices||[]).forEach(k=>{ let o=document.createElement('option'); o.value=lookupGoboValue(k); o.text=k; gsel.appendChild(o); });
}
function lookupGoboValue(name){ const t={"open":0,"dot":32,"beam":64,"star":96,"circle":64,"triangle":96}; return t[name]||0; }
function fxSet(key,val){
  let name=document.getElementById('man-fixture').value;
  if(['pan','tilt','dim','strobe','r','g','b','w','gobo'].includes(key)) val=parseInt(val,10);
  fetch('/api/fixture/set',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,values:{[key]:val}})});
}

/* ---------- Fixtures (offsets) ---------- */
function fixtureSave(){
  let fx=document.getElementById("fixture-select").value;
  let pan=parseInt(document.getElementById("fixture-pan").value||"0",10);
  let tilt=parseInt(document.getElementById("fixture-tilt").value||"0",10);
  let color=document.getElementById("fixture-color").value;
  let gobo=document.getElementById("fixture-gobo").value;
  fetch("/api/rehearsal",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({save:true,fixture:fx,pan_off:pan,tilt_off:tilt,color_fix:color,gobo_fix:gobo})});
}

/* ---------- Scenes ---------- */
function sceneSave(){ let nm=document.getElementById('scene-name').value||'Scene A';
  fetch('/api/scene/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:nm})}); }
function sceneLoad(){ let nm=document.getElementById('scene-load-name').value||'Scene A';
  fetch('/api/scene/load',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:nm})}); }

/* ---------- Force / Logs / Settings ---------- */
function forceSet(n){ fetch('/api/force',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({set:n})})
  .then(r=>r.json()).then(j=>{document.getElementById("force-status").innerText="Set "+n;}); }
function refreshLogs(){ fetch('/api/state').then(r=>r.json()).then(st=>{ document.getElementById('logbox').innerText=JSON.stringify(st,null,2); }); }
setInterval(refreshLogs, 2000);
function safeShutdown(){ fetch("/api/safe_shutdown",{method:"POST"}); }

/* ---------- MIDI learn toggles (placeholder) ---------- */
function midiLearnOn(){ fetch("/api/midi/log",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({learn:true})}); }
function midiLearnOff(){ fetch("/api/midi/log",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({learn:false})}); }

/* ---------- Init ---------- */
showTab('ai'); loadAI(); loadBand(); manualInit(); loadGroupPresets();
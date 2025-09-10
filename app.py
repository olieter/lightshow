#!/usr/bin/env python3
import os, json, time, random, threading
from flask import Flask, request, jsonify, send_from_directory
import requests

BASE = os.path.dirname(__file__)

# ---------- JSON helpers ----------
def jload(path, default):
    try:
        with open(path) as f: return json.load(f)
    except: return default
def jsave(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f: json.dump(obj, f, indent=2)

# ---------- Configs ----------
CFG            = jload(f"{BASE}/config/settings.json", {})
AI_CLUSTERS    = jload(f"{BASE}/config/ai_clusters.json", {"clusters":[]})
BAND_CLUSTERS  = jload(f"{BASE}/config/band_clusters.json", {"clusters":[], "solo_targets":[]})
COLORS         = jload(f"{BASE}/config/custom_colors.json", {})
WLED_FX        = jload(f"{BASE}/config/custom_wled_fx.json", {})
PIXEL_FX       = jload(f"{BASE}/config/custom_pixel_fx.json", {})
FIXTURES       = jload(f"{BASE}/config/fixtures_full.json", {"color_palettes":{},"groups":{}, "fixtures":{}})
PRESETS        = jload(f"{BASE}/config/custom_presets.json", {"group_presets":{}, "band_targets":[], "apply_order":[]})

STATE          = jload(f"{BASE}/data/state.json", {})
REHEARSAL      = jload(f"{BASE}/data/rehearsal_positions.json", {})
SCENES_PATH    = f"{BASE}/data/scenes.json"
SCENES         = jload(SCENES_PATH, {})
BAND_PRESETS_PATH = f"{BASE}/data/band_presets.json"
BAND_PRESETS   = jload(BAND_PRESETS_PATH, {})  # { target: { fixture: {ch-values...} } }

def sdef(key, val):
    if key not in STATE: STATE[key] = val
    return STATE[key]
def save_state(): jsave(f"{BASE}/data/state.json", STATE)

# --- Normalize tube DMX 'mode' to active channel map ---
_TUBE = FIXTURES.get("fixtures", {}).get("tube_dmx")
if _TUBE and "modes" in _TUBE:
    active = _TUBE.get("mode", "simple")
    _TUBE["ch"] = _TUBE["modes"].get(active, _TUBE["modes"]["simple"])

# ---------- Init state ----------
sdef("mode", "ai")                                  # ai | band | manual
sdef("ai_enabled", True)
sdef("ai_full", False)
sdef("ai_cluster", "tech_house")
sdef("ai_sub", None)
sdef("ai_color_lock", {"enabled": False, "hex": "#FFFFFF"})
sdef("ai_include", {
    "pars_big": True, "pars_small": True, "moving_par": True,
    "wash_fx": True, "moving_head": True, "scanner": True,
    "dual_scan": True, "wled_tubes": True, "tube_dmx": True, "guirlande": True
})

sdef("band_cluster", "intro")
sdef("band_sub", None)
sdef("band_running", False)
sdef("band_paused", False)
sdef("band_color_lock", {"enabled": True, "hex": "#FFE6CC"})
sdef("band_palette", "WarmWhite")
sdef("band_accent", {"enabled": True, "hex": "#FFB000", "pct": 10})
sdef("band_include", {
    "pars_big": True, "pars_small": True, "moving_par": True,
    "wash_fx": True, "moving_head": True, "scanner": True,
    "dual_scan": True, "wled_tubes": True, "tube_dmx": True, "guirlande": True
})

# device states
sdef("guirlande", {"on": True, "fx": "Breathe", "speed": 120, "intensity": 180})
sdef("wled_tubes", {"on": True, "fx": "Solid", "speed": 120, "intensity": 255})
sdef("tube_dmx", {"pattern": "fade_up", "speed": 64, "strobe": 0, "dim": 160})
sdef("strobo_dmx", {"rate": 0, "dim": 255})

# ---------- DMX via OLA ----------
DMX_BUF = bytearray(512)
UNIV = CFG.get("dmx_universe", 0)
try:
    from ola.ClientWrapper import ClientWrapper
    WR = ClientWrapper()
    OLA = WR.Client()
    def dmx_send():
        OLA.SendDmx(UNIV, DMX_BUF)
    def dmx_set(start, ch_map, values):
        for k, v in values.items():
            ch = ch_map.get(k)
            if ch is None: continue
            idx = start + ch - 2
            if 0 <= idx < 512: DMX_BUF[idx] = max(0, min(255, int(v)))
        dmx_send()
except Exception:
    def dmx_send(): pass
    def dmx_set(start, ch_map, values): pass

# ---------- WLED ----------
def wled_post(url, payload):
    try: requests.post(url, json=payload, timeout=0.25)
    except: pass

def wled_set(which, on=True, fx="Solid", speed=120, intensity=160, color_hex="#FFFFFF"):
    url = (CFG.get("wled") or {}).get(which)
    if not url: return
    fxid = WLED_FX.get(fx, 0)
    r=int(color_hex[1:3],16); g=int(color_hex[3:5],16); b=int(color_hex[5:7],16)
    data={"on":bool(on), "bri":max(1,intensity), "seg":[{"fx":fxid,"sx":speed,"ix":intensity,"col":[[r,g,b]],"pal":0}]}
    wled_post(url, data)

# ---------- Fixture helpers ----------
def fixture_caps(name):
    fx = FIXTURES["fixtures"].get(name, {})
    ch = fx.get("ch", {})
    caps = {
        "pan": "pan" in ch, "tilt": "tilt" in ch, "dim": "dim" in ch, "strobe": "strobe" in ch,
        "color": "color" in ch, "gobo": "gobo" in ch, "rgb": all(k in ch for k in ("r","g","b")), "w": "w" in ch
    }
    gobomap = []
    if "gobo" in ch:
        gobomap = list((FIXTURES.get("gobo_maps", {}).get("mh_gobo", {}) |
                        FIXTURES.get("gobo_maps", {}).get("scanner_gobo", {})).keys())
    return {"name": name, "start": fx.get("start"), "caps": caps, "gobo_choices": gobomap}

def _hex_to_rgb(hexv):
    return int(hexv[1:3],16), int(hexv[3:5],16), int(hexv[5:7],16)

def _hex_dist(a, b):
    ar,ag,ab=_hex_to_rgb(a); br,bg,bb=_hex_to_rgb(b)
    return (ar-br)**2+(ag-bg)**2+(ab-bb)**2

def dmx_apply_fixture(name, values):
    fx = FIXTURES["fixtures"].get(name)
    if not fx: return
    start, ch = fx["start"], fx["ch"]
    write = {}

    # 1) HEX kleur → RGB of → color wheel
    if "hex" in values:
        hexv = values["hex"]
        mc = fx.get("match_color", {})
        if mc.get("rgb") and all(k in ch for k in ("r","g","b")):
            r,g,b = _hex_to_rgb(hexv); write.update({"r":r,"g":g,"b":b})
            if mc.get("white_channel") and "w" in ch:
                # optioneel: eenvoudige warm/cool mix; hier 0
                write["w"] = 0
        elif "wheel" in mc and "color" in ch:
            wheel = mc["wheel"]["map"]
            # kies dichtstbijzijnde wheel-kleur
            pal = FIXTURES.get("color_palettes", {})
            best_val = 0; best_d = 10**9
            for cname, cval in wheel.items():
                hex_ref = pal.get(cname, "#FFFFFF")
                d = _hex_dist(hexv, hex_ref)
                if d < best_d: best_d, best_val = d, cval
            write["color"] = best_val
        elif "wheel_combo" in mc and "gobo_color1" in ch:
            # dual scan: zet beide color/gobo-slots naar dichtstbijzijnde naam (simple)
            wheel = mc["wheel_combo"]["map"]
            pal = FIXTURES.get("color_palettes", {})
            def nearest_val():
                best = list(wheel.items())[0]
                best_d = 10**9
                for cname, cval in wheel.items():
                    hex_ref = pal.get(cname.split("+")[0], "#FFFFFF")
                    d = _hex_dist(values["hex"], hex_ref)
                    if d < best_d: best_d, best = d, (cname, cval)
                return best[1]
            v = nearest_val()
            write["gobo_color1"] = v
            if "gobo_color2" in ch: write["gobo_color2"] = v

    # 2) Directe waarden (pan/tilt/dim/strobe/gobo/rgbw/etc.)
    for k in ("pan","tilt","dim","strobe","color","gobo","r","g","b","w","pattern","speed","macro","segment","rate","mode","rotation","zoom"):
        if k in values and k in ch:
            write[k] = values[k]

    dmx_set(start, ch, write)

# ---------- Color selection ----------
def main_color_ai():
    if STATE["ai_color_lock"]["enabled"]:
        return STATE["ai_color_lock"]["hex"]
    return {
        "tech_house":"#00FFFF", "rock_pop":"#FFE6CC", "goa_psy":"#FF00FF", "dnb_dub":"#7FDBFF",
        "retro_7090":"#FFB000", "party":"#FFFFFF", "electro_swing":"#FFE6CC", "slow":"#FFE6CC"
    }.get(STATE["ai_cluster"], "#FFFFFF")

def main_color_band():
    if STATE["band_color_lock"]["enabled"]:
        return STATE["band_color_lock"]["hex"]
    return COLORS.get(STATE.get("band_palette"), "#FFE6CC")

# ---------- Engines ----------
def ai_choose_sub():
    cl = next((c for c in AI_CLUSTERS["clusters"] if c["key"]==STATE["ai_cluster"]), None)
    if not cl or not cl.get("subs"): return None
    i = (int(time.time())//16) % len(cl["subs"])
    return cl["subs"][i]

def band_next_cluster():
    order = [c["key"] for c in BAND_CLUSTERS["clusters"]]
    if STATE["band_cluster"] not in order: return "intro"
    idx = (order.index(STATE["band_cluster"]) + 1) % len(order)
    return order[idx]

def tube_dmx_apply(on=True, pattern="fade_up", speed=64, strobe=0, dim=160):
    fx = FIXTURES.get("fixtures",{}).get("tube_dmx")
    if not fx: return
    start, ch = fx["start"], fx["ch"]
    pat = {"fade_up":10,"wave":30,"pulse":50,"chaos":70,"rainbow":90}.get(pattern,10)
    dmx_set(start, ch, {"pattern":pat, "speed":speed, "strobe":strobe, "dim":dim})

def strobo_dmx_apply(rate, dim):
    fx = FIXTURES.get("fixtures",{}).get("strobe_dmx")
    if not fx: return
    start, ch = fx["start"], fx["ch"]
    dmx_set(start, ch, {"rate":rate, "dim":dim})

def apply_blinders(top_val=None, bottom_val=None):
    fxt = FIXTURES["fixtures"]
    if "bl_top" in fxt and top_val is not None:
        dmx_set(fxt["bl_top"]["start"], fxt["bl_top"]["ch"], {"dim": top_val})
    if "bl_bottom" in fxt and bottom_val is not None:
        dmx_set(fxt["bl_bottom"]["start"], fxt["bl_bottom"]["ch"], {"dim": bottom_val})

def ai_tick():
    if not STATE["ai_enabled"]: return
    if STATE["ai_full"] and (STATE["ai_sub"] is None or int(time.time())%16==0):
        STATE["ai_sub"] = ai_choose_sub()

    col = main_color_ai()
    inc = STATE["ai_include"]

    if inc.get("guirlande"):
        wled_set("guirlande", True, STATE["guirlande"]["fx"], STATE["guirlande"]["speed"], STATE["guirlande"]["intensity"], col)
    if inc.get("wled_tubes"):
        t = STATE["wled_tubes"]
        for seg in ("tube_L","tube_R"):
            wled_set(seg, t["on"], t["fx"], t["speed"], t["intensity"], col)
    if inc.get("tube_dmx"):
        td = STATE["tube_dmx"]
        tube_dmx_apply(True, td["pattern"], td["speed"], td["strobe"], td["dim"])

def band_tick():
    col = main_color_band()
    inc = STATE["band_include"]

    if inc.get("guirlande"):
        wled_set("guirlande", True, "Breathe", 96, 120, col)
    if inc.get("wled_tubes"):
        for seg in ("tube_L","tube_R"):
            wled_set(seg, True, "Solid", 0, 255, col)
    if inc.get("tube_dmx"):
        tube_dmx_apply(True, "fade_up", 64, 0, 180)

    if STATE["band_running"] and not STATE["band_paused"] and STATE.get("ai_full"):
        if int(time.time()) % 32 == 0:
            STATE["band_cluster"] = band_next_cluster()

def engine_loop():
    while True:
        try:
            if STATE["mode"] == "ai":
                ai_tick()
            elif STATE["mode"] == "band":
                band_tick()
            time.sleep(0.02)
        except Exception:
            time.sleep(0.1)

threading.Thread(target=engine_loop, daemon=True).start()

# ---------- Flask ----------
app = Flask(__name__, static_folder="web", static_url_path="")

@app.get("/")
def root():
    return send_from_directory("web", "index.html")

@app.get("/api/state")
def api_state():
    return jsonify(STATE)

@app.post("/api/mode")
def api_mode():
    b = request.json or {}
    mode = b.get("mode")
    if mode in ("ai","band","manual"):
        STATE["mode"] = mode
    if "ai_cluster" in b: STATE["ai_cluster"] = b["ai_cluster"]
    if "ai_sub" in b:     STATE["ai_sub"]     = b["ai_sub"]
    if "band_cluster" in b: STATE["band_cluster"] = b["band_cluster"]
    save_state()
    return jsonify(ok=True, state=STATE)

# -------- AI ----------
@app.get("/api/ai/clusters")
def api_ai_clusters():
    return jsonify(AI_CLUSTERS)

@app.post("/api/ai/select")
def api_ai_select():
    b = request.json or {}
    STATE["mode"] = "ai"
    if "cluster" in b: STATE["ai_cluster"] = b["cluster"]
    if "sub" in b:     STATE["ai_sub"]     = b["sub"]
    save_state()
    return jsonify(ok=True, state=STATE)

@app.post("/api/ai/color")
def api_ai_color():
    b = request.json or {}
    if "enabled" in b: STATE["ai_color_lock"]["enabled"] = bool(b["enabled"])
    if "hex" in b:     STATE["ai_color_lock"]["hex"]     = str(b["hex"])
    save_state()
    return jsonify(ok=True, ai_color_lock=STATE["ai_color_lock"])

@app.post("/api/ai/include")
def api_ai_include():
    b = request.json or {}
    for k in list(STATE["ai_include"].keys()):
        if k in b: STATE["ai_include"][k] = bool(b[k])
    save_state()
    return jsonify(ok=True, ai_include=STATE["ai_include"])

# -------- Band ----------
@app.get("/api/band/clusters")
def api_band_clusters():
    return jsonify(BAND_CLUSTERS)

@app.post("/api/band/select")
def api_band_select():
    b = request.json or {}
    STATE["mode"] = "band"
    if "cluster" in b: STATE["band_cluster"] = b["cluster"]
    if "sub" in b:     STATE["band_sub"]     = b["sub"]
    save_state()
    return jsonify(ok=True, state=STATE)

@app.post("/api/band/color")
def api_band_color():
    b = request.json or {}
    if "enabled" in b: STATE["band_color_lock"]["enabled"] = bool(b["enabled"])
    if "hex" in b:     STATE["band_color_lock"]["hex"]     = str(b["hex"])
    if "palette" in b: STATE["band_palette"] = str(b["palette"])
    if "accent" in b:
        a = b["accent"]; ac = STATE["band_accent"]
        ac["enabled"] = bool(a.get("enabled", ac["enabled"]))
        if "hex" in a: ac["hex"] = str(a["hex"])
        if "pct" in a: ac["pct"] = int(a["pct"])
    if "include" in b:
        inc = b["include"]
        for k in list(STATE["band_include"].keys()):
            if k in inc: STATE["band_include"][k] = bool(inc[k])
    save_state()
    return jsonify(ok=True, state=STATE)

# ---- Show control (Band Pause/Stop, AI toggles) ----
@app.post("/api/show/control")
def api_show_control():
    b = request.json or {}
    cmd = b.get("cmd")
    if cmd == "band_pause_toggle":
        if not STATE["band_running"]:
            STATE["band_running"] = True; STATE["band_paused"] = False
        else:
            STATE["band_paused"] = not STATE["band_paused"]
    elif cmd == "band_stop":
        STATE["band_running"] = False; STATE["band_paused"] = False; STATE["band_cluster"] = "intro"
    elif cmd == "ai_toggle":
        STATE["ai_enabled"] = not STATE["ai_enabled"]
    elif cmd == "ai_full_toggle":
        STATE["ai_full"] = not STATE["ai_full"]; STATE["ai_enabled"] = True
    else:
        return jsonify(ok=False, err="unknown cmd"), 400
    save_state()
    return jsonify(ok=True, state=STATE)

# -------- Levels (faders) --------
@app.post("/api/levels")
def api_levels():
    b = request.json or {}
    ctrl = b.get("control"); val = int(b.get("value", 0))
    dval = int(val * 2.01)

    if ctrl == "blinder_top":      apply_blinders(top_val=dval)
    elif ctrl == "blinder_bottom": apply_blinders(bottom_val=dval)
    elif ctrl == "tube_dmx":
        STATE["tube_dmx"]["dim"] = dval; tube_dmx_apply(True, **STATE["tube_dmx"])
    elif ctrl == "wled_tubes_lr":
        STATE["wled_tubes"]["intensity"] = dval
    elif ctrl == "guirlande":
        STATE["guirlande"]["intensity"] = dval
    elif ctrl == "par_big_all":
        for name in FIXTURES["groups"].get("pars_big", []):
            fx = FIXTURES["fixtures"][name]
            dmx_set(fx["start"], fx["ch"], {"dim": dval})
    elif ctrl == "par_small_all":
        for name in FIXTURES["groups"].get("pars_small", []):
            fx = FIXTURES["fixtures"][name]
            dmx_set(fx["start"], fx["ch"], {"dim": dval})
    elif ctrl == "moving_par_lr":
        for name in FIXTURES["groups"].get("moving_par", []):
            fx = FIXTURES["fixtures"][name]
            dmx_set(fx["start"], fx["ch"], {"dim": dval})
    save_state()
    return jsonify(ok=True)

# -------- Params (knobs) --------
@app.post("/api/params")
def api_params():
    b = request.json or {}
    ctrl = b.get("control"); val = int(b.get("value", 0))
    dval = int(val * 2.01)
    if ctrl == "strobe_rate":
        STATE["strobo_dmx"]["rate"] = dval;  strobo_dmx_apply(STATE["strobo_dmx"]["rate"], STATE["strobo_dmx"]["dim"])
    elif ctrl == "strobe_dim":
        STATE["strobo_dmx"]["dim"]  = dval;  strobo_dmx_apply(STATE["strobo_dmx"]["rate"], STATE["strobo_dmx"]["dim"])
    elif ctrl == "washfx_dim":
        for name in FIXTURES["groups"].get("wash_fx", []):
            fx = FIXTURES["fixtures"][name]; dmx_set(fx["start"], fx["ch"], {"dim": dval})
    elif ctrl == "washfx_speed":
        for name in FIXTURES["groups"].get("wash_fx", []):
            fx = FIXTURES["fixtures"][name]; dmx_set(fx["start"], fx["ch"], {"macro": min(255, dval)})
    elif ctrl == "mh_pan":
        for name in FIXTURES["groups"].get("moving_head", []):
            fx = FIXTURES["fixtures"][name]; dmx_set(fx["start"], fx["ch"], {"pan": dval})
    elif ctrl == "mh_tilt":
        for name in FIXTURES["groups"].get("moving_head", []):
            fx = FIXTURES["fixtures"][name]; dmx_set(fx["start"], fx["ch"], {"tilt": dval})
    elif ctrl == "scanner_pan":
        for name in FIXTURES["groups"].get("scanner", []):
            fx = FIXTURES["fixtures"][name]; dmx_set(fx["start"], fx["ch"], {"pan": dval})
    elif ctrl == "scanner_tilt":
        for name in FIXTURES["groups"].get("scanner", []):
            fx = FIXTURES["fixtures"][name]; dmx_set(fx["start"], fx["ch"], {"tilt": dval})
    elif ctrl == "dualscan_speed":
        for name in FIXTURES["groups"].get("dual_scan", []):
            fx = FIXTURES["fixtures"][name]; dmx_set(fx["start"], fx["ch"], {"strobe": dval})
    elif ctrl == "ai_variation":
        STATE["ai_variation"] = (val >= 64)
    elif ctrl == "ai_smooth":
        STATE["ai_smooth"]    = (val >= 64)
    elif ctrl == "ai_colormix":
        STATE["ai_colormix"]  = (val >= 64)
    elif ctrl == "band_fill":
        STATE["band_fill"] = dval
    elif ctrl == "master_dim":
        STATE["guirlande"]["intensity"]  = max(10, dval)
        STATE["wled_tubes"]["intensity"] = max(10, dval)
    save_state()
    return jsonify(ok=True)

# -------- Effects (strobo/tubes/wled/guirlande/laser) --------
@app.post("/api/effects")
def api_effects():
    b = request.json or {}
    target = b.get("target")
    fx     = b.get("fx")
    if target == "tube_dmx":
        if fx == "on_off":
            STATE["tube_dmx"]["dim"] = 0 if STATE["tube_dmx"]["dim"]>0 else 180
        elif fx in ("wave","pulse","chaos","rainbow","fade_up"):
            STATE["tube_dmx"]["pattern"] = fx
        tube_dmx_apply(True, **STATE["tube_dmx"])
    elif target == "wled_tubes":
        if fx == "on_off":
            STATE["wled_tubes"]["on"] = not STATE["wled_tubes"]["on"]
        elif fx in WLED_FX: STATE["wled_tubes"]["fx"] = fx
    elif target == "guirlande":
        if fx == "on_off":
            STATE["guirlande"]["on"] = not STATE["guirlande"]["on"]
        elif fx in WLED_FX: STATE["guirlande"]["fx"] = fx
    elif target == "strobo":
        if fx == "ai_wave":   STATE["strobo_dmx"]["rate"] = 128
        if fx == "ai_pulse":  STATE["strobo_dmx"]["rate"] = 160
        if fx == "ai_lr":     STATE["strobo_dmx"]["rate"] = 190
        if fx == "ai_chaos":  STATE["strobo_dmx"]["rate"] = 220
        strobo_dmx_apply(STATE["strobo_dmx"]["rate"], STATE["strobo_dmx"]["dim"])
    elif target == "laser":
        fxr = FIXTURES["fixtures"].get("laser")
        if not fxr: return jsonify(ok=True)
        if   fx == "laser_on":  dmx_set(fxr["start"], fxr["ch"], {"on":255})
        elif fx == "laser_off": dmx_set(fxr["start"], fxr["ch"], {"on":0})
    save_state()
    return jsonify(ok=True, state=STATE)

# -------- Blinders presets (momentary/override) --------
@app.post("/api/blinders")
def api_blinders():
    b = request.json or {}
    preset = b.get("preset")
    momentary = bool(b.get("momentary", True))
    if preset in ("top","bottom"):
        apply_blinders(255 if preset=="top" else None, 255 if preset=="bottom" else None)
    elif preset in ("25","50","75","100"):
        val = {"25":64,"50":128,"75":192,"100":255}[preset]; apply_blinders(val, val)
    elif preset == "blackout_all":
        apply_blinders(0,0); STATE["wled_tubes"]["on"]=False; STATE["guirlande"]["on"]=False
    elif preset == "blackout_keep_guir":
        apply_blinders(0,0); STATE["guirlande"]["on"]=True
    elif preset == "full_on":
        apply_blinders(255,255)
    elif preset == "full_toggle":
        top_now = DMX_BUF[FIXTURES["fixtures"]["bl_top"]["start"]-1] if "bl_top" in FIXTURES["fixtures"] else 0
        new = 0 if top_now>0 else 255; apply_blinders(new,new)
    if momentary and preset not in ("blackout_all","blackout_keep_guir","full_toggle"):
        time.sleep(0.15); apply_blinders(0,0)
    save_state()
    return jsonify(ok=True)

# -------- Strobo DMX (momentary) --------
@app.post("/api/strobo_dmx")
def api_strobo_dmx():
    b = request.json or {}
    momentary = bool(b.get("momentary", True))
    strobo_dmx_apply(STATE["strobo_dmx"]["rate"], STATE["strobo_dmx"]["dim"])
    if momentary:
        time.sleep(0.1); strobo_dmx_apply(0, STATE["strobo_dmx"]["dim"])
    return jsonify(ok=True)

# -------- Fixtures list & per-fixture control --------
@app.get("/api/fixtures")
def api_fixtures_list():
    out = [fixture_caps(n) for n in FIXTURES.get("fixtures", {}).keys()]
    return jsonify({"fixtures": out, "colors": COLORS})

@app.post("/api/fixture/set")
def api_fixture_set():
    b = request.json or {}
    name = b.get("name"); vals = b.get("values", {})
    if not name: return jsonify(ok=False, err="name"), 400
    dmx_apply_fixture(name, vals)
    return jsonify(ok=True)

# -------- Scenes save/load --------
@app.post("/api/scene/save")
def api_scene_save():
    b = request.json or {}; nm = b.get("name")
    if not nm: return jsonify(ok=False, err="name"), 400
    snap = {}
    for name, fx in FIXTURES.get("fixtures", {}).items():
        ch = fx.get("ch",{})
        keys = [k for k in ("pan","tilt","dim","strobe","color","gobo","r","g","b","w") if k in ch]
        if not keys: continue
        obj = {}
        for k in keys:
            idx = fx["start"] + ch[k] - 2
            if 0 <= idx < 512: obj[k] = DMX_BUF[idx]
        if obj: snap[name] = obj
    SCENES[nm] = snap; jsave(SCENES_PATH, SCENES)
    return jsonify(ok=True, scenes=list(SCENES.keys()))

@app.post("/api/scene/load")
def api_scene_load():
    b = request.json or {}; nm = b.get("name")
    if not nm or nm not in SCENES: return jsonify(ok=False, err="unknown scene"), 400
    for name, vals in SCENES[nm].items(): dmx_apply_fixture(name, vals)
    return jsonify(ok=True)

# -------- Rehearsal / Aim & Store (offsets) --------
@app.post("/api/rehearsal")
def api_rehearsal():
    b = request.json or {}
    if "save" in b and b["save"]:
        name = b.get("fixture")
        if not name: return jsonify(ok=False, err="fixture"), 400
        rec = REHEARSAL.get(name, {})
        for k in ("pan_off","tilt_off","color_fix","gobo_fix"):
            if k in b: rec[k] = b[k]
        REHEARSAL[name] = rec
        jsave(f"{BASE}/data/rehearsal_positions.json", REHEARSAL)
        return jsonify(ok=True, stored={name: rec})
    if "target" in b:
        STATE["band_target"] = b["target"]
    save_state(); return jsonify(ok=True)

# -------- Group presets (Manual) --------
@app.post("/api/preset/apply_group")
def api_preset_apply_group():
    b = request.json or {}
    group = b.get("group"); name  = b.get("name")
    if not group or not name: return jsonify(ok=False, err="group/name"), 400
    p = (PRESETS.get("group_presets", {}).get(group, {}) or {}).get(name)
    if not p: return jsonify(ok=False, err="unknown preset"), 404
    for fxn in FIXTURES["groups"].get(group, []):
        dmx_apply_fixture(fxn, p)
    return jsonify(ok=True)

# -------- Band outlight presets (Aim & Store per target) --------
def snapshot_all_relevant():
    snap = {}
    for name, fx in FIXTURES.get("fixtures", {}).items():
        ch = fx.get("ch",{})
        keys = [k for k in ("pan","tilt","dim","strobe","color","gobo","r","g","b","w") if k in ch]
        if not keys: continue
        obj = {}
        for k in keys:
            idx = fx["start"] + ch[k] - 2
            if 0 <= idx < 512: obj[k] = DMX_BUF[idx]
        if obj: snap[name] = obj
    return snap

@app.post("/api/band/preset/save")
def api_band_preset_save():
    b = request.json or {}
    target = b.get("target")
    if target not in PRESETS.get("band_targets", []):
        return jsonify(ok=False, err="unknown target"), 400
    BAND_PRESETS[target] = snapshot_all_relevant()
    jsave(BAND_PRESETS_PATH, BAND_PRESETS)
    return jsonify(ok=True, saved_target=target)

@app.post("/api/band/preset/load")
def api_band_preset_load():
    b = request.json or {}
    target = b.get("target")
    if target not in BAND_PRESETS: return jsonify(ok=False, err="no data"), 404
    for fxn, vals in BAND_PRESETS[target].items():
        dmx_apply_fixture(fxn, vals)
    return jsonify(ok=True, loaded_target=target)

# -------- Force bridge (AUTO / A / B / C) --------
@app.post("/api/force")
def api_force():
    b = request.json or {}
    setv = int(b.get("set", 0))
    base = CFG.get("force_bridge", "http://192.168.4.200")
    try:
        requests.get(f"{base}/mode?set={setv}&key=LETMEIN", timeout=0.4)
    except Exception:
        pass
    return jsonify(ok=True, forwarded=setv)

# -------- MIDI logging / learn hook --------
@app.post("/api/midi/log")
def api_midi_log():
    b = request.json or {}
    return jsonify(ok=True, seen=b)

# -------- Safe shutdown --------
@app.post("/api/safe_shutdown")
def api_safe_shutdown():
    os.system(f"bash {BASE}/scripts/safe_shutdown.sh &")
    return jsonify(ok=True)

# -------- Static (web assets) --------
@app.get("/assets/<path:p>")
def assets(p):
    return send_from_directory("web/assets", p)

# -------- Run --------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
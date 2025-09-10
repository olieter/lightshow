#!/usr/bin/env python3
import json, os, time, requests, threading

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CFG_MIDI = os.path.join(BASE, "config", "midi_layout.json")
CFG_REMAP= os.path.join(BASE, "config", "midi_remap.json")
CFG_LED  = os.path.join(BASE, "config", "midi_led_map.json")

API = "http://127.0.0.1:5000"

def jload(p, default):
    try:
        with open(p) as f: return json.load(f)
    except: return default

def post(path, payload, to=0.25):
    try: requests.post(API+path, json=payload, timeout=to)
    except: pass

def get(path, to=0.25):
    try: return requests.get(API+path, timeout=to).json()
    except: return {}

def state(): return get("/api/state") or {}

def midi_cfg():
    return jload(CFG_MIDI, {"launchpad":{}, "midimix":{}})

def midi_remap():
    return jload(CFG_REMAP, {"learn_mode": False, "map":{"midimix":{"cc":{},"note":{}},"launchpad":{"cc":{},"note":{}}}})

def midi_led_map():
    return jload(CFG_LED, {"on":3, "off":0, "warn":1})

# --- routing helpers (abstract actions → API) ---
def route_action(action, value=None):
    """Map een abstracte actie naar de juiste API-call."""
    if action in ("ai_toggle","ai_full_toggle","band_pause_toggle","band_stop"):
        post("/api/show/control", {"cmd": action})
        return
    if action in ("force_auto","force_a","force_b","force_c"):
        m = {"force_auto":0,"force_a":1,"force_b":2,"force_c":3}[action]
        post("/api/force", {"set": m}); return
    if action in ("ai_mode","band_mode","manual_mode"):
        mode = {"ai_mode":"ai","band_mode":"band","manual_mode":"manual"}[action]
        post("/api/mode", {"mode": mode}); return
    if action.startswith("ai_cluster:"):
        cl = action.split(":",1)[1]
        post("/api/ai/select", {"cluster": cl}); return
    if action.startswith("band_cluster:"):
        cl = action.split(":",1)[1]
        post("/api/band/select", {"cluster": cl}); return
    if action.startswith("band_pos:"):
        pos = action.split(":",1)[1]
        post("/api/rehearsal", {"active": False, "target": pos}); return
    # levels & params (faders/knobs)
    if action.startswith("level:"):
        ctrl = action.split(":",1)[1]
        post("/api/levels", {"control": ctrl, "value": value}); return
    if action.startswith("param:"):
        ctrl = action.split(":",1)[1]
        post("/api/params", {"control": ctrl, "value": value}); return
    # strobo DMX momentary
    if action == "strobe_dmx_momentary":
        post("/api/strobo_dmx", {"momentary": True}); return
    # blinders presets
    if action.startswith("blinder:"):
        what = action.split(":",1)[1]
        post("/api/blinders", {"preset": what, "momentary": True}); return
    # tubes/guirlande/effects (AI-gestuurd of static)
    if action.startswith("effect:"):
        # effect:tubes:ai_wave  / effect:guirlande:breathe / effect:tube_dmx:rainbow
        _, target, fx = action.split(":",2)
        post("/api/effects", {"target": target, "fx": fx}); return
    # fallback: log alleen
    post("/api/midi/log", {"action": action, "value": value})

# --- Launchpad LED API (abstract; per apparaat kan dit verschillen) ---
def lp_light(out_port, note, on=True, vel=None):
    """Zet Launchpad-pad LED aan/uit (vel = kleur/helderheid indien ondersteund)."""
    try:
        import mido
        if vel is None: vel = midi_led_map().get("on" if on else "off", 3 if on else 0)
        out_port.send(mido.Message("note_on", note=note, velocity=vel))
    except Exception:
        pass
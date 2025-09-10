#!/usr/bin/env python3
import time, mido, json, os
from midi_utils import midi_cfg, midi_remap, route_action, lp_light, state

# --- Poorten zoeken ---
def open_ports():
    ins  = [n for n in mido.get_input_names()  if "Launchpad" in n]
    outs = [n for n in mido.get_output_names() if "Launchpad" in n]
    return (mido.open_input(ins[0]) if ins else None,
            mido.open_output(outs[0]) if outs else None)

# --- Mapping helpers ---
def build_default_map():
    """Bouw standaard acties voor bovenrij/rechterkolom en rijen op basis van config."""
    cfg = midi_cfg().get("launchpad", {})
    m = {}
    # BOVENSTE RIJ (8 knoppen) – blackouts & blinders
    top = cfg.get("top_buttons", [])
    for i, name in enumerate(top):
        # map naar concrete actie
        if name == "blackout_all":     m[f"top:{i}"] = "blinder:blackout_all"
        elif name == "blackout_keep_guir": m[f"top:{i}"] = "blinder:blackout_keep_guir"
        elif name == "full_on":        m[f"top:{i}"] = "blinder:full_on"
        elif name == "full_toggle":    m[f"top:{i}"] = "blinder:full_toggle"
        elif name.startswith("blinder_"):
            pct = name.split("_",1)[1]
            m[f"top:{i}"] = f"blinder:{pct}"
    # RECHTER KOLOM (8) – modes/force
    right = cfg.get("right_column", [])
    for i, name in enumerate(right):
        if name == "ai_toggle":        m[f"right:{i}"] = "ai_toggle"
        elif name == "band_toggle":    m[f"right:{i}"] = "band_mode"
        elif name == "manual_toggle":  m[f"right:{i}"] = "manual_mode"
        elif name == "force_auto":     m[f"right:{i}"] = "force_auto"
        elif name == "force_a":        m[f"right:{i}"] = "force_a"
        elif name == "force_b":        m[f"right:{i}"] = "force_b"
        elif name == "force_c":        m[f"right:{i}"] = "force_c"
    # RIJ 1 – AI clusters
    r1 = cfg.get("row1_ai_clusters", [])
    for i, cl in enumerate(r1):
        m[f"r1:{i}"] = f"ai_cluster:{cl}"
    # RIJ 2 – Blinders/AI-strobo FX
    r2 = cfg.get("row2_blinders", [])
    for i, key in enumerate(r2):
        if key in ("top","bottom"):
            m[f"r2:{i}"] = f"blinder:{key}"
        else:
            m[f"r2:{i}"] = f"effect:strobo:{key}"
    # RIJ 3 – Strobo FX combinaties
    r3 = cfg.get("row3_strobo_fx", [])
    for i, key in enumerate(r3):
        m[f"r3:{i}"] = f"effect:strobo:{key}"
    # RIJ 4 – Tube DMX
    r4 = cfg.get("row4_tube_dmx", [])
    for i, key in enumerate(r4):
        if key == "on_off": m[f"r4:{i}"] = "effect:tube_dmx:on_off"
        else:               m[f"r4:{i}"] = f"effect:tube_dmx:{key}"
    # RIJ 5 – WLED Tubes
    r5 = cfg.get("row5_wled_tubes", [])
    for i, key in enumerate(r5):
        m[f"r5:{i}"] = f"effect:wled_tubes:{key}"
    # RIJ 6 – Guirlande
    r6 = cfg.get("row6_guirlande", [])
    for i, key in enumerate(r6):
        m[f"r6:{i}"] = f"effect:guirlande:{key}"
    # RIJ 7 – Laser/relay/audio
    r7 = cfg.get("row7_laser", [])
    for i, key in enumerate(r7):
        m[f"r7:{i}"] = f"effect:laser:{key}"
    # RIJ 8 – Misc (strobe DMX momentary)
    r8 = cfg.get("row8_misc", [])
    for i, key in enumerate(r8):
        if key == "strobe_dmx_momentary":
            m[f"r8:{i}"] = "strobe_dmx_momentary"
        else:
            m[f"r8:{i}"] = f"effect:misc:{key}"
    return m

def build_note_index_map():
    """
    Launchpad Mini (generic): we nemen een 8x8 grid van noten aan, en
    mappen noten oplopend per rij (linksboven -> r1:c1). 
    Pas dit indien jouw apparaat andere note nummers gebruikt.
    """
    # Maak een 8x8 virtuele matrix 36..99 (veilige range); pas desnoods aan.
    idx = {}
    base = 36
    for r in range(1,9):       # r1..r8
        for c in range(8):     # c0..c7
            note = base + (r-1)*8 + c
            idx[note] = (r,c)
    # Bovenste rij-knoppen (8 stuks) → noten 8..15
    top = {8+i:("top",i) for i in range(8)}
    # Rechter kolom (8 stuks) → noten 16..23
    right = {16+i:("right",i) for i in range(8)}
    return idx, top, right

def main():
    inp, outp = open_ports()
    if not inp or not outp:
        while True: time.sleep(1)

    default_map = build_default_map()
    grid_map, top_map, right_map = build_note_index_map()

    remap = midi_remap()
    learn = remap.get("learn_mode", False)
    l_map = remap["map"]["launchpad"]["note"]  # {note: action}

    # LED init: zet AI actief pad aan (optioneel)
    while True:
        for msg in inp.iter_pending():
            if msg.type == "note_on" and msg.velocity > 0:
                note = msg.note
                action = l_map.get(str(note))
                if action is None:
                    # Bepaal positie → actie uit default_map
                    if note in top_map:
                        key = f"top:{top_map[note][1]}"
                        action = default_map.get(key)
                    elif note in right_map:
                        key = f"right:{right_map[note][1]}"
                        action = default_map.get(key)
                    else:
                        rc = grid_map.get(note)
                        if rc:
                            r, c = rc
                            key = f"r{r}:{c}"
                            action = default_map.get(key)

                if learn:
                    # laat backend weten voor remap UI
                    from midi_utils import post
                    post("/api/midi/log", {"device":"launchpad","note":note,"suggested":action})
                if action:
                    route_action(action)
                    lp_light(outp, note, on=True)
            elif msg.type == "note_off" or (msg.type=="note_on" and msg.velocity==0):
                # momentary release
                lp_light(outp, msg.note, on=False)

        time.sleep(0.005)

if __name__ == "__main__":
    main()
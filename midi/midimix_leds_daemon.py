#!/usr/bin/env python3
import time, mido
from midi_utils import midi_cfg, midi_remap, midi_led_map, route_action, post

# Aanname: MIDImix exposeert 8 faders + 24 knoppen (A/B/C rows) + 8 top/8 second/4 right buttons.
# CC/Note nummers verschillen soms per OS/driver; remap voorziet dit.

def open_ports():
    ins  = [n for n in mido.get_input_names()  if "MIDImix" in n or "MIDI" in n]
    outs = [n for n in mido.get_output_names() if "MIDImix" in n or "MIDI" in n]
    return (mido.open_input(ins[0]) if ins else None,
            mido.open_output(outs[0]) if outs else None)

def build_controls():
    """Bouw abstracte acties per controller-element t.o.v. config/midi_layout.json."""
    cfg = midi_cfg().get("midimix", {})
    K = {}   # control_number → action (we laten echte CC mapping aan remap over)
    # Faders (we geven alleen logische namen terug; de CC → control gebeurt via remap)
    for i, name in enumerate(cfg.get("faders", []), start=0):
        K[f"fader:{i}"] = f"level:{name}"
    # Knobs A/B/C (8 per rij)
    for i, name in enumerate(cfg.get("knobsA", []), start=0):
        K[f"knobA:{i}"] = f"param:{name}"
    for i, name in enumerate(cfg.get("knobsB", []), start=0):
        K[f"knobB:{i}"] = f"param:{name}"
    for i, name in enumerate(cfg.get("knobsC", []), start=0):
        K[f"knobC:{i}"] = f"param:{name}"
    # Top buttons = Band clusters
    for i, name in enumerate(cfg.get("top_buttons", []), start=0):
        K[f"topbtn:{i}"] = f"band_cluster:{name.replace('band_','')}"
    # Second row = Quick positions
    for i, name in enumerate(cfg.get("second_row", []), start=0):
        # 'pos_vox' → 'vox'
        tag = name.replace("pos_","")
        K[f"second:{i}"] = f"band_pos:{tag}"
    # Right buttons (4) = band/ai control
    right = cfg.get("right_buttons", [])
    RB = {}
    for i, name in enumerate(right, start=0):
        RB[i] = name   # "band_pause_toggle" | "band_stop" | "ai_toggle" | "ai_full_toggle"
    return K, RB

def main():
    inp, outp = open_ports()
    if not inp: 
        while True: time.sleep(1)

    logical, right_btns = build_controls()
    remap = midi_remap()
    learn = remap.get("learn_mode", False)
    mp_cc = remap["map"]["midimix"]["cc"]
    mp_nt = remap["map"]["midimix"]["note"]

    # Voorbeeld default CC-ordening (kan afwijken; remap gebruiken!)
    # Faders CC 0..7, Knobs A 16..23, Knobs B 24..31, Knobs C 32..39, TopBtns notes 40..47, Second 48..55, Right 56..59
    default_map_cc = {
        **{str(0+i): logical.get(f"fader:{i}") for i in range(8)},
        **{str(16+i): logical.get(f"knobA:{i}") for i in range(8)},
        **{str(24+i): logical.get(f"knobB:{i}") for i in range(8)},
        **{str(32+i): logical.get(f"knobC:{i}") for i in range(8)},
    }
    default_map_note = {
        **{str(40+i): logical.get(f"topbtn:{i}") for i in range(8)},
        **{str(48+i): logical.get(f"second:{i}") for i in range(8)},
        **{str(60+i): right_btns.get(i)          for i in range(4)},  # 60..63 = 4 rechterknoppen
    }

    LED = midi_led_map()

    while True:
        for msg in inp.iter_pending():
            try:
                if msg.type == "control_change":
                    cc, val = msg.control, msg.value
                    action = mp_cc.get(str(cc)) or default_map_cc.get(str(cc))
                    if learn:
                        post("/api/midi/log", {"device":"midimix","cc":cc,"suggested":action})
                    if action:
                        # faders/knobs → 0..127 raw; backend schaalt naar DMX/WLED
                        route_action(action, val)
                elif msg.type == "note_on" and msg.velocity > 0:
                    note = msg.note
                    action = mp_nt.get(str(note)) or default_map_note.get(str(note))
                    if learn:
                        post("/api/midi/log", {"device":"midimix","note":note,"suggested":action})
                    if action:
                        route_action(action, 127)
                elif msg.type == "note_off":
                    # momentary release (b.v. strobo), stuur 0 indien nodig
                    pass
            except Exception:
                pass
        time.sleep(0.004)

if __name__ == "__main__":
    main()
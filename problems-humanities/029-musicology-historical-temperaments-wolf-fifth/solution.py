import sys
import json
import math

# Ensure UTF-8 IO
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
NOTE_TO_IDX = {name: i for i, name in enumerate(NOTE_NAMES)}

TET_CENTS = [float(i * 100) for i in range(12)]

PYTHAGOREAN_CENTS = [
    0.0, 113.685, 203.910, 294.135, 407.820, 498.045,
    611.730, 701.955, 815.640, 905.865, 996.090, 1109.775
]

MEANTONE_CENTS = [
    0.0, 76.049, 193.157, 310.265, 386.314, 503.422,
    579.471, 696.578, 772.627, 889.735, 1006.843, 1082.892
]

WERCKMEISTER_III_CENTS = [
    0.0, 90.225, 192.180, 294.135, 390.225, 498.045,
    588.270, 696.090, 792.180, 888.270, 996.090, 1092.180
]

JUST_INTONATION_CENTS = [
    0.0, 111.731, 203.910, 315.641, 386.314, 498.045,
    590.224, 701.955, 813.686, 884.359, 1017.596, 1088.269
]

TEMPERAMENTS = {
    "equal_temperament": TET_CENTS,
    "pythagorean": PYTHAGOREAN_CENTS,
    "quarter_comma_meantone": MEANTONE_CENTS,
    "werckmeister_iii": WERCKMEISTER_III_CENTS,
    "just_intonation": JUST_INTONATION_CENTS
}

def get_c4_freq(temperament_name, a4_freq=440.0):
    cents_table = TEMPERAMENTS[temperament_name]
    a_cents = cents_table[9]
    c4_freq = a4_freq / (2.0 ** (a_cents / 1200.0))
    return round(c4_freq, 4)

def get_note_freq(temperament_name, note_name, octave, a4_freq=440.0):
    idx = NOTE_TO_IDX[note_name]
    cents_table = TEMPERAMENTS[temperament_name]
    c4_freq = get_c4_freq(temperament_name, a4_freq)
    cents_from_c4 = cents_table[idx] + (octave - 4) * 1200.0
    freq = c4_freq * (2.0 ** (cents_from_c4 / 1200.0))
    return round(freq, 3)

def analyze_temperament(req):
    tname = req["temperament"]
    a4_freq = req.get("base_a4_frequency", 440.0)
    cents_table = TEMPERAMENTS[tname]
    c4_freq = get_c4_freq(tname, a4_freq)
    
    notes_list = []
    for i, name in enumerate(NOTE_NAMES):
        c = cents_table[i]
        freq = round(c4_freq * (2.0 ** (c / 1200.0)), 3)
        dev = round(c - TET_CENTS[i], 2)
        notes_list.append({
            "note": name,
            "cents_from_c": round(c, 2),
            "frequency_hz": freq,
            "deviation_from_12tet_cents": dev
        })
        
    fifths = []
    wolf_intervals = []
    pure_fifths = 0
    tempered_fifths = 0
    wolf_fifths = 0
    
    for i in range(12):
        root = NOTE_NAMES[i]
        f_idx = (i + 7) % 12
        fifth = NOTE_NAMES[f_idx]
        interval = (cents_table[f_idx] - cents_table[i]) % 1200.0
        interval = round(interval, 3)
        
        dev = interval - 701.955
        if abs(dev) > 15.0:
            is_wolf = True
            wolf_fifths += 1
            wolf_intervals.append({
                "interval": f"{root}-{fifth}",
                "cents": round(interval, 2),
                "deviation_from_pure_cents": round(dev, 2)
            })
        elif abs(dev) < 1.0:
            is_wolf = False
            pure_fifths += 1
        else:
            is_wolf = False
            tempered_fifths += 1
            
        fifths.append({
            "root": root,
            "fifth": fifth,
            "cents": round(interval, 2),
            "is_wolf": is_wolf
        })
        
    pure_thirds = 0
    for i in range(12):
        t_idx = (i + 4) % 12
        interval = (cents_table[t_idx] - cents_table[i]) % 1200.0
        if abs(interval - 386.314) < 1.0:
            pure_thirds += 1

    return {
        "mode": "analyze_temperament",
        "temperament": tname,
        "base_a4_frequency": a4_freq,
        "base_c4_frequency": round(c4_freq, 3),
        "scale_notes": notes_list,
        "wolf_intervals": wolf_intervals,
        "summary": {
            "pure_fifths_count": pure_fifths,
            "tempered_fifths_count": tempered_fifths,
            "wolf_fifths_count": wolf_fifths,
            "pure_major_thirds_count": pure_thirds
        }
    }

def evaluate_triad(req):
    tname = req["temperament"]
    a4_freq = req.get("base_a4_frequency", 440.0)
    root_name = req["root_note"]
    octave = req.get("octave", 4)
    
    root_idx = NOTE_TO_IDX[root_name]
    third_idx = (root_idx + 4) % 12
    fifth_idx = (root_idx + 7) % 12
    
    third_name = NOTE_NAMES[third_idx]
    fifth_name = NOTE_NAMES[fifth_idx]
    
    third_octave = octave + 1 if third_idx < root_idx else octave
    fifth_octave = octave + 1 if fifth_idx < root_idx else octave
    
    f_root = get_note_freq(tname, root_name, octave, a4_freq)
    f_third = get_note_freq(tname, third_name, third_octave, a4_freq)
    f_fifth = get_note_freq(tname, fifth_name, fifth_octave, a4_freq)
    
    cents_table = TEMPERAMENTS[tname]
    c_root = cents_table[root_idx]
    c_third = cents_table[third_idx]
    c_fifth = cents_table[fifth_idx]
    
    third_cents = round((c_third - c_root) % 1200.0, 2)
    fifth_cents = round((c_fifth - c_root) % 1200.0, 2)
    
    third_dev = round(third_cents - 386.31, 2)
    fifth_dev = round(fifth_cents - 701.96, 2)
    
    third_beats = round(abs(4.0 * f_third - 5.0 * f_root), 2)
    fifth_beats = round(abs(2.0 * f_fifth - 3.0 * f_root), 2)
    
    is_wolf_chord = (abs(fifth_dev) > 15.0 or abs(third_dev) > 30.0)
    if is_wolf_chord:
        classification = "DISCORDANT_WOLF"
    elif third_beats < 1.0 and fifth_beats < 1.0:
        classification = "PURE_CONSONANT"
    elif third_beats <= 12.0 and fifth_beats <= 4.0:
        classification = "TEMPERED_CONSONANT"
    else:
        classification = "HARSH_BEATING"
        
    return {
        "mode": "evaluate_triad",
        "temperament": tname,
        "chord_symbol": f"{root_name} Major",
        "frequencies": {
            "root": {"note": f"{root_name}{octave}", "freq_hz": f_root},
            "third": {"note": f"{third_name}{third_octave}", "freq_hz": f_third},
            "fifth": {"note": f"{fifth_name}{fifth_octave}", "freq_hz": f_fifth}
        },
        "intervals": {
            "major_third_cents": third_cents,
            "major_third_deviation_cents": third_dev,
            "fifth_cents": fifth_cents,
            "fifth_deviation_cents": fifth_dev
        },
        "acoustics": {
            "major_third_beat_hz": third_beats,
            "fifth_beat_hz": fifth_beats
        },
        "classification": classification
    }

def compare_key_colors(req):
    tname = req["temperament"]
    a4_freq = req.get("base_a4_frequency", 440.0)
    keys_to_test = req.get("keys", ["C", "G", "D", "F#", "G#"])
    
    results = []
    for k in keys_to_test:
        sub_req = {
            "temperament": tname,
            "base_a4_frequency": a4_freq,
            "root_note": k,
            "octave": 4
        }
        res = evaluate_triad(sub_req)
        results.append({
            "key": f"{k} Major",
            "major_third_cents": res["intervals"]["major_third_cents"],
            "third_beat_hz": res["acoustics"]["major_third_beat_hz"],
            "classification": res["classification"]
        })
        
    return {
        "mode": "compare_key_colors",
        "temperament": tname,
        "key_comparisons": results
    }

def solve():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    req = json.loads(raw)
    mode = req.get("mode")
    
    if mode == "analyze_temperament":
        res = analyze_temperament(req)
    elif mode == "evaluate_triad":
        res = evaluate_triad(req)
    elif mode == "compare_key_colors":
        res = compare_key_colors(req)
    else:
        res = {"error": f"Unknown mode: {mode}"}
        
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    solve()

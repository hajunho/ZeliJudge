import sys
import json
import math

if sys.platform == 'win32':
    try:
        sys.stdin.reconfigure(encoding='utf-8')
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

PYTHAGOREAN_RATIOS = {
    0: 1.0,
    1: 2187 / 2048,
    2: 9 / 8,
    3: 32 / 27,
    4: 81 / 64,
    5: 4 / 3,
    6: 729 / 512,
    7: 3 / 2,
    8: 128 / 81,
    9: 27 / 16,
    10: 16 / 9,
    11: 243 / 128
}

JUST_RATIOS = {
    0: 1.0,
    1: 16 / 15,
    2: 9 / 8,
    3: 6 / 5,
    4: 5 / 4,
    5: 4 / 3,
    6: 45 / 32,
    7: 3 / 2,
    8: 8 / 5,
    9: 5 / 3,
    10: 9 / 5,
    11: 15 / 8
}

def ratio_to_cents(ratio):
    if ratio <= 0:
        return 0.0
    return 1200.0 * math.log2(ratio)

def get_note_semitone(note_str):
    # e.g. C4 -> name 'C', octave 4
    # e.g. F#4 -> name 'F#', octave 4
    # e.g. Bb4 -> name 'A#', octave 4
    name = note_str[:-1]
    octave = int(note_str[-1])
    if name == 'Db': name = 'C#'
    elif name == 'Eb': name = 'D#'
    elif name == 'Gb': name = 'F#'
    elif name == 'Ab': name = 'G#'
    elif name == 'Bb': name = 'A#'
    semitone_in_octave = NOTE_NAMES.index(name)
    return semitone_in_octave, octave

def get_frequency(note_str, tuning_system, base_c4=261.625565):
    semitone, octave = get_note_semitone(note_str)
    octave_mult = 2.0 ** (octave - 4)
    if tuning_system == '12-TET':
        ratio = 2.0 ** (semitone / 12.0)
    elif tuning_system == 'PYTHAGOREAN':
        ratio = PYTHAGOREAN_RATIOS[semitone]
    elif tuning_system == 'JUST_INTONATION':
        ratio = JUST_RATIOS[semitone]
    else:
        ratio = 2.0 ** (semitone / 12.0)
    return base_c4 * ratio * octave_mult

def plomp_levelt(f1, f2, a1=1.0, a2=1.0):
    if f1 > f2:
        f1, f2 = f2, f1
    df = f2 - f1
    if df < 1e-6:
        return 0.0
    f_mean = 0.5 * (f1 + f2)
    s = 0.24 / (0.021 * f_mean + 19.0)
    x = s * df
    d = math.exp(-3.5 * x) - math.exp(-5.75 * x)
    return (a1 * a2) * max(0.0, d)

def compute_chord_dissonance(frequencies, num_harmonics=6):
    partials = []
    for f in frequencies:
        for k in range(1, num_harmonics + 1):
            partials.append((f * k, 1.0 / k))
    total_d = 0.0
    for i in range(len(partials)):
        for j in range(i + 1, len(partials)):
            total_d += plomp_levelt(partials[i][0], partials[j][0], partials[i][1], partials[j][1])
    return round(total_d, 4)

def run_musicology_engine(data):
    base_c4 = float(data.get('base_c4_hz', 261.625565))
    num_harmonics = int(data.get('num_harmonics', 6))
    queries = data.get('queries', [])

    # Standard commas calculation
    pyth_comma_ratio = (1.5 ** 12) / (2.0 ** 7)
    pyth_comma_cents = round(ratio_to_cents(pyth_comma_ratio), 2)
    syntonic_comma_ratio = 81.0 / 80.0
    syntonic_comma_cents = round(ratio_to_cents(syntonic_comma_ratio), 2)

    commas_info = {
        'pythagorean_comma': {
            'ratio': round(pyth_comma_ratio, 6),
            'cents': pyth_comma_cents,
            'description': '12 perfect fifths vs 7 octaves shortfall'
        },
        'syntonic_comma': {
            'ratio': round(syntonic_comma_ratio, 6),
            'cents': syntonic_comma_cents,
            'description': 'Pythagorean ditone (81/64) vs pure major third (5/4)'
        }
    }

    query_results = []
    for q in queries:
        qid = q.get('query_id', '')
        q_type = q.get('type', 'CHORD_DISSONANCE')
        tuning = q.get('tuning_system', '12-TET')

        if q_type == 'SCALE_TABLE':
            scale_data = []
            for s in range(12):
                name = NOTE_NAMES[s]
                note_label = f'{name}4'
                freq = get_frequency(note_label, tuning, base_c4)
                if tuning == '12-TET':
                    ratio = 2.0 ** (s / 12.0)
                elif tuning == 'PYTHAGOREAN':
                    ratio = PYTHAGOREAN_RATIOS[s]
                elif tuning == 'JUST_INTONATION':
                    ratio = JUST_RATIOS[s]
                cents = ratio_to_cents(ratio)
                tet_cents = s * 100.0
                deviation_cents = cents - tet_cents
                scale_data.append({
                    'semitone': s,
                    'note': note_label,
                    'freq_hz': round(freq, 2),
                    'ratio': round(ratio, 6),
                    'cents': round(cents, 2),
                    'cents_deviation_from_12tet': round(deviation_cents, 2)
                })
            query_results.append({
                'query_id': qid,
                'type': q_type,
                'tuning_system': tuning,
                'scale': scale_data
            })

        elif q_type == 'CHORD_DISSONANCE':
            chords = q.get('chords', [])
            chord_evals = []
            for ch in chords:
                ch_name = ch.get('name', '')
                notes = ch.get('notes', [])
                ch_tuning = ch.get('tuning_system', tuning)
                freqs = [get_frequency(n, ch_tuning, base_c4) for n in notes]
                diss = compute_chord_dissonance(freqs, num_harmonics)
                chord_evals.append({
                    'name': ch_name,
                    'notes': notes,
                    'tuning_system': ch_tuning,
                    'frequencies_hz': [round(f, 2) for f in freqs],
                    'dissonance_score': diss
                })
            # Rank chords by dissonance score ascending (least dissonant first)
            chord_evals = sorted(chord_evals, key=lambda x: (x['dissonance_score'], x['name']))
            for idx, item in enumerate(chord_evals):
                item['consonance_rank'] = idx + 1
            query_results.append({
                'query_id': qid,
                'type': q_type,
                'evaluations': chord_evals
            })

        elif q_type == 'WOLF_FIFTH_COMPARISON':
            # Compare pure fifth G4/C4 with wolf fifth G#4/Eb4 or G#4/D#5
            pure_f1 = get_frequency('C4', 'PYTHAGOREAN', base_c4)
            pure_f2 = get_frequency('G4', 'PYTHAGOREAN', base_c4)
            wolf_f1 = get_frequency('G#4', 'PYTHAGOREAN', base_c4)
            # Eb5 in pythagorean: semitone 3, octave 5
            wolf_f2 = get_frequency('D#5', 'PYTHAGOREAN', base_c4)
            pure_diss = compute_chord_dissonance([pure_f1, pure_f2], num_harmonics)
            wolf_diss = compute_chord_dissonance([wolf_f1, wolf_f2], num_harmonics)
            query_results.append({
                'query_id': qid,
                'type': q_type,
                'pure_fifth': {'notes': ['C4', 'G4'], 'ratio': 1.5, 'cents': 701.96, 'dissonance': pure_diss},
                'wolf_fifth': {'notes': ['G#4', 'D#5'], 'ratio': round(wolf_f2/wolf_f1, 6), 'cents': round(ratio_to_cents(wolf_f2/wolf_f1), 2), 'dissonance': wolf_diss},
                'wolf_penalty': round(wolf_diss - pure_diss, 4)
            })

    return {
        'commas': commas_info,
        'results': query_results
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    res = run_musicology_engine(data)
    print(json.dumps(res, ensure_ascii=False))

if __name__ == '__main__':
    main()

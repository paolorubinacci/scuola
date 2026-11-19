"""Trascrizione automatica di un brano di piano: audio -> MIDI (e, se chiesto, MusicXML per la partitura).

  python tools/trascrivi.py AUDIO.wav OUT.mid [OUT.musicxml] [--titolo "Titolo"]

1. Note: Transkun (Yan & Duan, trascrizione piano allo stato dell'arte; pacchetto "transkun").
2. Tempo, battute e metro: Beat This! (CPJKU, 2024; beat e primi tempi di battuta) -> 3/4, 4/4 ...
   Le note vengono riportate sui battiti reali del brano (segue il rubato) e quantizzate
   a 1/4 o 1/3 di battito (sceglie la griglia che sbaglia meno).
3. MIDI: tempo costante (mediana del brano), due tracce: mano destra / mano sinistra, indicazione di tempo.
4. MusicXML: un solo pianoforte su due pentagrammi (violino + basso con graffa), tonalita' stimata.
   Accordi semplificati: in ogni pentagramma ogni attacco diventa un accordo che dura fino al successivo
   (piu' leggibile delle voci sovrapposte di una trascrizione automatica).
Stampa una riga JSON con metro, bpm, griglia, note."""
import sys, os, json, subprocess, tempfile, math
import numpy as np
import mido

A = sys.argv[1:]
TITOLO = ''
if '--titolo' in A:
    i = A.index('--titolo'); TITOLO = A[i + 1]; del A[i:i + 2]
WAV, OUT_MID = A[0], A[1]
OUT_XML = A[2] if len(A) > 2 else None


def note_transkun(wav):
    raw = os.path.join(tempfile.mkdtemp(), 'raw.mid')
    exe = os.path.join(os.path.dirname(sys.executable), 'transkun')
    subprocess.run([exe if os.path.exists(exe) else 'transkun', wav, raw, '--device', 'cpu'], check=True)
    m = mido.MidiFile(raw)
    notes, t, on = [], 0.0, {}
    for msg in m:  # iterare MidiFile da' i delta in secondi
        t += msg.time
        if msg.type == 'note_on' and msg.velocity > 0:
            on.setdefault(msg.note, []).append((t, msg.velocity))
        elif msg.type in ('note_off', 'note_on'):
            if on.get(msg.note):
                s, v = on[msg.note].pop(0)
                notes.append((s, max(t, s + 0.03), msg.note, v))
    return sorted(notes)


def battiti(wav):
    try:
        from beat_this.inference import File2Beats
        b, d = File2Beats(checkpoint_path='final0', device='cpu', dbn=False)(wav)
        b, d = np.asarray(b, float), np.asarray(d, float)
        if len(b) >= 8:
            return b, d, 'beat_this'
    except Exception as e:
        print('beat_this non disponibile:', e, file=sys.stderr)
    import librosa
    y, sr = librosa.load(wav, sr=22050, mono=True)
    _, fr = librosa.beat.beat_track(y=y, sr=sr)
    return librosa.frames_to_time(fr, sr=sr), np.array([]), 'librosa'


def metro(b, d):
    if len(d) < 3:
        return 4
    idx = np.array([int(np.argmin(np.abs(b - x))) for x in d])
    gaps = np.diff(idx)
    gaps = gaps[(gaps >= 2) & (gaps <= 6)]
    if not len(gaps):
        return 4
    vals, cnt = np.unique(gaps, return_counts=True)
    return int(vals[np.argmax(cnt)])


def metro_note(pos, pitch, vel):
    """metro e primo tempo dal basso: in quale periodo (2, 3, 4 battiti) tornano le note gravi?
    Valzer: basso ogni 3; 4/4: basso su 1 e 3. Restituisce il contrasto per ogni metro e la fase migliore."""
    n = int(np.ceil(pos.max())) + 2
    low = np.full(n, np.nan)
    k = np.round(pos).astype(int)
    for kk, pp, ok in zip(k, pitch, np.abs(pos - k) < 0.25):
        if ok and 0 <= kk < n:
            low[kk] = pp if np.isnan(low[kk]) else min(low[kk], pp)
    # quanto e' grave la nota piu' bassa di ogni battito rispetto al solito: il basso del primo tempo spicca
    ref = np.nanpercentile(low, 75) if np.any(~np.isnan(low)) else 60
    s = np.nan_to_num(np.clip(ref - low, 0, None)) + 1.0
    s = s[:max(8, n)]
    res = {}
    for m in (2, 3, 4):
        means = [s[f::m].mean() for f in range(m)]
        f = int(np.argmax(means))
        res[m] = (means[f] / (s.mean() + 1e-9), f)
    return res


def t2beat(t, b):
    """tempo (s) -> posizione in battiti, seguendo i battiti reali; prolunga con l'intervallo ai bordi."""
    t = np.asarray(t, float)
    pos = np.interp(t, b, np.arange(len(b)))
    a0, a1 = b[1] - b[0], b[-1] - b[-2]
    pos = np.where(t < b[0], (t - b[0]) / a0, pos)
    pos = np.where(t > b[-1], len(b) - 1 + (t - b[-1]) / a1, pos)
    return pos


def main():
    notes = [n for n in note_transkun(WAV) if n[3] >= 12]
    if not notes:
        raise SystemExit('nessuna nota trovata')
    b, d, src = battiti(WAV)
    on = t2beat([n[0] for n in notes], b)
    off = t2beat([n[1] for n in notes], b)
    # metro: voto dei primi tempi di Beat This! e del basso; vince il basso se e' molto piu' chiaro
    res = metro_note(on, [n[2] for n in notes], [n[3] for n in notes])
    m_bt = metro(b, d) if len(d) >= 3 else None
    best = max(res, key=lambda m: res[m][0])
    if best == 2 and res[4][0] >= 0.9 * res[2][0]:
        best = 4
    met = m_bt if (m_bt in res and res[m_bt][0] >= 0.95 * res[best][0]) else best
    if met == 2 and res[4][0] >= 0.9 * res[2][0]:  # 2/4 e 4/4 si assomigliano: meglio battute da 4
        met = 4
    fase = res[met][1]
    # allinea le battute: la fase del basso diventa il primo tempo
    shift = -fase + met * math.ceil(max(0.0, fase - math.floor(on.min())) / met)
    on, off = on + shift, off + shift
    err = {q: float(np.mean(np.abs(on * q - np.round(on * q))) / q) for q in (4, 3)}
    q = 3 if err[3] < 0.8 * err[4] else 4
    qs = [(round(a * q) / q, max(round(e * q) / q, round(a * q) / q + 1 / q), n[2], n[3]) for a, e, n in zip(on, off, notes)]
    seen, ev = set(), []
    for a, e, p, v in sorted(qs):
        if (a, p) in seen:
            continue
        seen.add((a, p))
        ev.append((max(0.0, a), min(e, a + 2 * met), p, v))
    bpm = round(60 / float(np.median(np.diff(b))))
    # mani: sopra/sotto il Do centrale
    rh = [x for x in ev if x[2] >= 60]
    lh = [x for x in ev if x[2] < 60]

    # ---- MIDI (tempo costante, due tracce) ----
    TPB = 480
    mf = mido.MidiFile(ticks_per_beat=TPB)
    for name, part, first in (('Mano destra', rh, True), ('Mano sinistra', lh, False)):
        tr = mido.MidiTrack()
        mf.tracks.append(tr)
        tr.append(mido.MetaMessage('track_name', name=name, time=0))
        if first:
            tr.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(bpm), time=0))
            tr.append(mido.MetaMessage('time_signature', numerator=met, denominator=4, time=0))
        msgs = []
        for a, e, p, v in part:
            msgs.append((round(a * TPB), 1, mido.Message('note_on', note=p, velocity=int(v), time=0)))
            msgs.append((round(e * TPB), 0, mido.Message('note_off', note=p, velocity=0, time=0)))
        last = 0
        for tick, _, m in sorted(msgs, key=lambda x: (x[0], x[1])):
            m.time = tick - last
            last = tick
            tr.append(m)
    mf.save(OUT_MID)

    info = {'contrasto': {f'{m}/4': round(res[m][0], 2) for m in res}, 'metro': f'{met}/4', 'bpm': bpm, 'griglia': '1/%d' % q, 'note': len(ev), 'battiti': src}
    if OUT_XML:
        from music21 import stream, note, chord, meter, clef, key, layout, metadata, duration
        def staff(part, cl):
            s = stream.PartStaff()
            s.append(cl)
            s.append(meter.TimeSignature(f'{met}/4'))
            groups = {}
            for a, e, p, v in part:
                groups.setdefault(a, []).append((e, p))
            starts = sorted(groups)
            for i, a in enumerate(starts):
                e = max(x[0] for x in groups[a])
                if i + 1 < len(starts):
                    nx = starts[i + 1]
                    # legato: se manca poco al prossimo attacco, la nota arriva fin li' (niente pause minuscole)
                    e = nx if (e >= nx or nx - e <= 0.5) else math.ceil(e * 2) / 2
                else:
                    e = math.ceil(e)
                ql = max(1 / q, e - a)
                ps = sorted({p for _, p in groups[a]})
                el = note.Note(ps[0]) if len(ps) == 1 else chord.Chord(ps)
                el.duration = duration.Duration(ql)
                s.insert(a, el)
            return s
        sc = stream.Score()
        sc.metadata = metadata.Metadata(title=TITOLO or 'Trascrizione', composer='Trascrizione automatica (bozza)')
        r, l = staff(rh, clef.TrebleClef()), staff(lh, clef.BassClef())
        sharps = 0
        try:
            k = stream.Stream([note.Note(p, quarterLength=e - a) for a, e, p, v in ev]).analyze('key')
            sharps = k.sharps
            r.insert(0, key.KeySignature(sharps)); l.insert(0, key.KeySignature(sharps))
            info['tonalita'] = k.tonic.name + (' maggiore' if k.mode == 'major' else ' minore')
        except Exception:
            pass
        for st_ in (r, l):
            for p_ in st_.pitches:
                if p_.accidental is not None and p_.accidental.name == 'natural':
                    p_.accidental = None
                elif sharps < 0 and p_.accidental is not None and p_.accidental.name == 'sharp':
                    p_.getEnharmonic(inPlace=True)
        for s in (r, l):
            sc.insert(0, s)
        sc.insert(0, layout.StaffGroup([r, l], symbol='brace', barTogether=True))
        sc = sc.makeNotation()
        sc.write('musicxml', fp=OUT_XML)
    print(json.dumps(info, ensure_ascii=False))


if __name__ == '__main__':
    main()

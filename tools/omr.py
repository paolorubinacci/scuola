"""Partitura -> MIDI (lettura ottica con Audiveris, poi music21). Gira su GitHub Actions dentro tools/elabora.py.

  python3 tools/omr.py OUT.mid PAGINA1 [PAGINA2 ...]      (immagini PNG/JPG oppure un PDF)

Stampa sull'ultima riga un JSON: {"note": .., "misure": .., "pagine": .., "metro": .., "bpm": ..}
Variabili: AUDIVERIS (percorso del programma, default "audiveris"), OMR_BPM (tempo di riferimento, default 80)."""
import sys, os, json, glob, shutil, subprocess, tempfile

AUD = os.environ.get('AUDIVERIS', 'audiveris')
BPM = int(os.environ.get('OMR_BPM', '80'))


def pagine_pdf(files, tmp):
    """immagini -> un solo PDF (un libro per Audiveris), ingrandite se piccole: Audiveris vuole righe ben distanziate"""
    from PIL import Image
    ims = []
    for f in files:
        im = Image.open(f)
        im = im.convert('RGBA') if im.mode in ('P', 'LA') else im
        if im.mode == 'RGBA':
            bg = Image.new('RGB', im.size, 'white'); bg.paste(im, mask=im.split()[3]); im = bg
        im = im.convert('L')
        if im.width < 2400:
            k = 2400 / im.width
            im = im.resize((2400, round(im.height * k)), Image.LANCZOS)
        ims.append(im)
    pdf = os.path.join(tmp, 'partitura.pdf')
    ims[0].save(pdf, save_all=True, append_images=ims[1:], resolution=300)
    return pdf


def leggi(pdf, tmp):
    out = os.path.join(tmp, 'omr')
    os.makedirs(out, exist_ok=True)
    cmd = [AUD, '-batch', '-transcribe', '-export', '-output', out, '--', pdf]
    print('$', ' '.join(cmd), file=sys.stderr, flush=True)
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=2400)
    sys.stderr.write((p.stdout + p.stderr)[-4000:])
    mx = sorted(glob.glob(os.path.join(out, '**', '*.mxl'), recursive=True) + glob.glob(os.path.join(out, '**', '*.xml'), recursive=True))
    mx = [m for m in mx if not m.endswith('.opus.mxl')]
    if not mx:
        raise RuntimeError('Audiveris non ha riconosciuto la partitura')
    return mx


def unisci(files):
    from music21 import converter, stream
    scores = [converter.parse(f) for f in files]
    s = scores[0]
    for e in scores[1:]:  # piu' movimenti / pagine separate: in coda, parte per parte
        for i, p in enumerate(e.parts):
            if i < len(s.parts):
                tgt = s.parts[i]
                for m in p.getElementsByClass(stream.Measure):
                    tgt.append(m)
    return s


def main():
    out_mid, ins = sys.argv[1], sys.argv[2:]
    tmp = tempfile.mkdtemp(prefix='omr-')
    try:
        pdf = ins[0] if len(ins) == 1 and ins[0].lower().endswith('.pdf') else pagine_pdf(ins, tmp)
        from music21 import tempo, stream, meter
        s = unisci(leggi(pdf, tmp))
        try:  # ritornelli e segni (D.S., Coda) suonati come sono scritti nella partitura, se Audiveris li ha letti
            s2 = s.expandRepeats()
            if len(list(s2.recurse().notes)) >= len(list(s.recurse().notes)):
                s = s2
        except Exception as e:
            print('ritornelli non espansi:', e, file=sys.stderr)
        if not list(s.recurse().getElementsByClass(tempo.MetronomeMark)):
            s.parts[0].measure(s.parts[0].getElementsByClass(stream.Measure)[0].number).insert(0, tempo.MetronomeMark(number=BPM))
        notes = sum(len(n.pitches) for n in s.recurse().notes)
        if notes < 8:
            raise RuntimeError('Nella partitura ho riconosciuto troppo poche note')
        s.write('midi', fp=out_mid)
        ts = next(iter(s.recurse().getElementsByClass(meter.TimeSignature)), None)
        mm = next(iter(s.recurse().getElementsByClass(tempo.MetronomeMark)), None)
        print(json.dumps({'note': notes, 'misure': len(s.parts[0].getElementsByClass(stream.Measure)),
                          'pagine': len(ins) if not ins[0].lower().endswith('.pdf') else None,
                          'metro': ts.ratioString if ts else None, 'bpm': round(mm.number) if mm and mm.number else BPM,
                          'parti': len(s.parts)}))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    main()

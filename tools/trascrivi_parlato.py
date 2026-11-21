"""Trascrive (in inglese, con i tempi) gli audio cifrati in lavori/*.audio.enc -> lavori/<nome>.trascr.json.enc, poi cancella l'audio.
Serve per le lezioni dei videocorsi: Claude cifra l'audio della registrazione, GitHub Actions (che puo' scaricare il modello) trascrive.
  SCUOLA_PW=... python3 tools/trascrivi_parlato.py"""
import os, glob, json, tempfile
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scuola.py')).read().split("cmd=sys.argv[1]")[0])
fs = sorted(glob.glob(R + '/lavori/*.audio.enc'))
if not fs: print('niente da fare'); raise SystemExit
from faster_whisper import WhisperModel
m = WhisperModel(os.environ.get('WHISPER_MODEL', 'medium.en'), device='cpu', compute_type='int8')
for f in fs:
    nome = os.path.basename(f)[:-len('.audio.enc')]
    lingua = 'it' if nome.endswith('-it') else 'en'
    tmp = tempfile.mkdtemp(); a = os.path.join(tmp, 'a.m4a'); open(a, 'wb').write(dec(open(f, 'rb').read()))
    segs, info = m.transcribe(a, language=lingua, vad_filter=True, beam_size=5, word_timestamps=True)
    out = [{'s': round(s.start, 2), 'e': round(s.end, 2), 't': s.text.strip(), 'p': round(s.no_speech_prob, 3),
            'w': [[round(w.start, 2), round(w.end, 2), w.word, round(w.probability, 2)] for w in (s.words or [])]} for s in segs]
    open(R + '/lavori/%s.trascr.json.enc' % nome, 'wb').write(enc(json.dumps(out, ensure_ascii=False).encode()))
    os.remove(f); print(nome, len(out), 'segmenti', flush=True)

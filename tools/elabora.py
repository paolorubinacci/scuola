"""Ascolti consigliati: elabora i brani caricati dal sito (gira da solo su GitHub Actions).

  SCUOLA_PW=... python3 tools/elabora.py [CARTELLA_SITO]

Per ogni brano di ascolti/catalog.json con stato "elaborazione" e il file ascolti/<id>/originale.mp3.enc:
  1. decifra l'MP3 caricato dal sito
  2. tipo "band": separa le tracce con Demucs (htdemucs_6s: batteria, basso, piano, voce, chitarra+altro -> "altro")
     tipo "solo": niente separazione (e' gia' tutto piano)
  3. codifica: originale mp3 160k, tracce mp3 128k
  4. se richiesto ("trascrivi") e se non c'e' gia' un MIDI caricato da Paolo: trascrizione automatica del piano
     (Basic Pitch, Spotify) -> auto.mid; poi MuseScore -> auto.pdf (bozza) se non c'e' gia' una partitura caricata
  5. cifra tutto con la password della Scuola, aggiorna il catalogo (stato "pronto"), cancella originale.mp3.enc
In caso di errore il brano passa a stato "errore" con il messaggio, e l'MP3 caricato resta li'.
Comandi esterni: ffmpeg, python con demucs (variabile DEMUCS_PY), python con basic-pitch (BP_PY), mscore3 (MSCORE).
I file audio in chiaro non vengono MAI scritti nel repository (e' pubblico)."""
import sys, os, json, shutil, subprocess, tempfile, traceback, datetime
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PW = os.environ['SCUOLA_PW']
SALT = bytes.fromhex(open(os.path.join(ROOT, 'tools', 'salt.hex')).read().strip())
KEY = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=SALT, iterations=200000).derive(PW.encode())
DEMUCS_PY = os.environ.get('DEMUCS_PY', sys.executable)
BP_PY = os.environ.get('BP_PY', sys.executable)
MSCORE = os.environ.get('MSCORE', 'mscore3')
CAT = os.path.join(ROOT, 'ascolti', 'catalog.json')


def dec(b):
    return AESGCM(KEY if b[:16] == SALT else PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=b[:16], iterations=200000).derive(PW.encode())).decrypt(b[16:28], b[28:], None)


def enc_file(src, dst):
    iv = os.urandom(12)
    open(dst, 'wb').write(SALT + iv + AESGCM(KEY).encrypt(iv, open(src, 'rb').read(), None))


def sh(*a, **k):
    print('$', ' '.join(map(str, a)), flush=True)
    subprocess.run(a, check=True, **k)


def dur(f):
    o = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', f],
                       capture_output=True, text=True, check=True).stdout
    return round(float(o), 2)


def separa(wav, out):
    sh(DEMUCS_PY, '-m', 'demucs', '-n', 'htdemucs_6s', '-o', out, wav)
    d = os.path.join(out, 'htdemucs_6s', os.path.splitext(os.path.basename(wav))[0])
    other = os.path.join(d, 'other_all.wav')
    sh('ffmpeg', '-loglevel', 'error', '-y', '-i', os.path.join(d, 'other.wav'), '-i', os.path.join(d, 'guitar.wav'),
       '-filter_complex', 'amix=inputs=2:normalize=0', other)
    return {'drums': f'{d}/drums.wav', 'bass': f'{d}/bass.wav', 'piano': f'{d}/piano.wav',
            'vocals': f'{d}/vocals.wav', 'other': other}


TRASCRIVI = r'''
import sys, numpy as np, librosa, pretty_midi
from basic_pitch.inference import predict
wav, out = sys.argv[1], sys.argv[2]
_, pm, _ = predict(wav, onset_threshold=0.5, frame_threshold=0.3, minimum_note_length=80)
y, sr = librosa.load(wav, sr=22050, mono=True)
bpm = float(np.atleast_1d(librosa.beat.beat_track(y=y, sr=sr)[0])[0]) or 100.0
while bpm < 60: bpm *= 2
while bpm > 180: bpm /= 2
m = pretty_midi.PrettyMIDI(initial_tempo=round(bpm))
rh, lh = pretty_midi.Instrument(0, name='Mano destra'), pretty_midi.Instrument(0, name='Mano sinistra')
for ins in pm.instruments:
    for n in ins.notes:
        (rh if n.pitch >= 60 else lh).notes.append(pretty_midi.Note(velocity=n.velocity, pitch=n.pitch, start=n.start, end=n.end))
m.instruments = [rh, lh]
m.write(out)
print('trascrizione', len(rh.notes) + len(lh.notes), 'note', round(bpm), 'bpm')
'''


def trascrivi(wav, mid):
    f = os.path.join(os.path.dirname(mid), 'trascrivi.py')
    open(f, 'w').write(TRASCRIVI)
    sh(BP_PY, f, wav, mid)


def pdf_da_midi(mid, pdf):
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', XDG_RUNTIME_DIR=tempfile.mkdtemp())
    sh(MSCORE, '-o', pdf, mid, env=env, timeout=600)
    if not os.path.exists(pdf) or os.path.getsize(pdf) < 500:
        raise RuntimeError('MuseScore non ha prodotto il PDF')


def elabora(tid, x, tmp):
    d = os.path.join(ROOT, 'ascolti', tid)
    src = os.path.join(d, 'originale.mp3.enc')
    mp3 = os.path.join(tmp, 'originale.mp3')
    open(mp3, 'wb').write(dec(open(src, 'rb').read()))
    wav = os.path.join(tmp, 'brano.wav')
    sh('ffmpeg', '-loglevel', 'error', '-y', '-i', mp3, '-ar', '44100', '-ac', '2', wav)
    stems = separa(wav, os.path.join(tmp, 'sep')) if x.get('tipo') == 'band' else {}
    files = {'mix': (wav, '160k')}
    files.update({k: (v, '128k') for k, v in stems.items()})
    for k, (w, br) in files.items():
        p = os.path.join(tmp, k + '.mp3')
        sh('ffmpeg', '-loglevel', 'error', '-y', '-i', w, '-c:a', 'libmp3lame', '-b:a', br, p)
        enc_file(p, os.path.join(d, k + '.mp3.enc'))
    x['stems'] = [k for k in ('drums', 'bass', 'piano', 'vocals', 'other') if k in stems]
    x['dur'] = dur(wav)
    x['avvisi'] = []
    if x.get('trascrivi') and not (x.get('midi') and not x['midi'].get('auto')):
        try:
            mid = os.path.join(tmp, 'auto.mid')
            trascrivi(stems.get('piano', wav), mid)
            enc_file(mid, os.path.join(d, 'auto.mid.enc'))
            x['midi'] = {'f': 'auto.mid.enc', 'auto': True}
            if not (x.get('pdf') and not x['pdf'].get('auto')):
                try:
                    pdf = os.path.join(tmp, 'auto.pdf')
                    pdf_da_midi(mid, pdf)
                    enc_file(pdf, os.path.join(d, 'auto.pdf.enc'))
                    x['pdf'] = {'f': 'auto.pdf.enc', 'auto': True}
                except Exception as e:
                    traceback.print_exc()
                    x['avvisi'].append('Partitura automatica non riuscita: c\'è solo il MIDI.')
        except Exception as e:
            traceback.print_exc()
            x['avvisi'].append('Trascrizione automatica non riuscita.')
    if not x['avvisi']:
        del x['avvisi']
    os.remove(src)
    x['stato'] = 'pronto'
    x.pop('errore', None)
    x['agg'] = datetime.date.today().isoformat()


def main():
    cat = json.load(open(CAT))
    todo = [t for t, x in cat.items() if x.get('stato') == 'elaborazione'
            and os.path.exists(os.path.join(ROOT, 'ascolti', t, 'originale.mp3.enc'))]
    print('da elaborare:', todo or 'nessuno', flush=True)
    for tid in todo:
        tmp = tempfile.mkdtemp(prefix='asc-')
        x = cat[tid]
        try:
            elabora(tid, x, tmp)
            print('ok', tid, {k: x.get(k) for k in ('stems', 'dur', 'midi', 'pdf', 'avvisi')}, flush=True)
        except Exception as e:
            traceback.print_exc()
            x['stato'] = 'errore'
            x['errore'] = str(e)[-300:]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        json.dump(cat, open(CAT, 'w'), ensure_ascii=False, indent=1)
    return todo


if __name__ == '__main__':
    main()

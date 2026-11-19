"""Ascolti consigliati: elabora i brani caricati dal sito (gira da solo su GitHub Actions).

  SCUOLA_PW=... python3 tools/elabora.py [CARTELLA_SITO]

Per ogni brano di ascolti/catalog.json con stato "elaborazione" e il file ascolti/<id>/originale.mp3.enc:
  1. decifra l'MP3 caricato dal sito
  2. tipo "band": separa le tracce con Demucs (htdemucs_6s: batteria, basso, piano, voce, chitarra+altro -> "altro")
     tipo "solo": niente separazione (e' gia' tutto piano)
  3. codifica: originale mp3 160k, tracce mp3 128k
  4. solo se Paolo l'ha chiesto e non ha gia' caricato i suoi file: trascrizione automatica del piano
     (tools/trascrivi.py: Transkun + Beat This!) -> auto.mid ("midi_auto") e/o partitura MuseScore -> auto.pdf ("pdf_auto")
Con "rifai": nessun MP3 nuovo, rifa' solo la trascrizione partendo dall'audio gia' pubblicato.
  5. cifra tutto con la password della Scuola, aggiorna il catalogo (stato "pronto"), cancella originale.mp3.enc
In caso di errore il brano passa a stato "errore" con il messaggio, e l'MP3 caricato resta li'.
Comandi esterni: ffmpeg, python con demucs (variabile DEMUCS_PY), python con transkun e beat_this (TR_PY), mscore3 (MSCORE).
I file audio in chiaro non vengono MAI scritti nel repository (e' pubblico)."""
import sys, os, json, shutil, subprocess, tempfile, traceback, datetime
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PW = os.environ['SCUOLA_PW']
SALT = bytes.fromhex(open(os.path.join(ROOT, 'tools', 'salt.hex')).read().strip())
KEY = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=SALT, iterations=200000).derive(PW.encode())
DEMUCS_PY = os.environ.get('DEMUCS_PY', sys.executable)
TR_PY = os.environ.get('TR_PY', sys.executable)
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


def trascrivi(wav, mid, xml, titolo):
    cmd = [TR_PY, os.path.join(ROOT, 'tools', 'trascrivi.py'), wav, mid] + ([xml] if xml else []) + ['--titolo', titolo or '']
    print('$', ' '.join(cmd), flush=True)
    out = subprocess.run(cmd, check=True, capture_output=True, text=True)
    sys.stderr.write(out.stderr[-3000:])
    return json.loads(out.stdout.strip().splitlines()[-1])


def pdf_da_xml(xml, pdf):
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', XDG_RUNTIME_DIR=tempfile.mkdtemp())
    sh(MSCORE, '-o', pdf, xml, env=env, timeout=600)
    if not os.path.exists(pdf) or os.path.getsize(pdf) < 500:
        raise RuntimeError('MuseScore non ha prodotto il PDF')


def opzioni(x):
    """midi_auto / pdf_auto (prima c'era un'unica opzione "trascrivi")"""
    if 'midi_auto' not in x and 'pdf_auto' not in x:
        x['midi_auto'] = x['pdf_auto'] = bool(x.get('trascrivi'))
    x.pop('trascrivi', None)
    return x.get('midi_auto'), x.get('pdf_auto')


def trascrizione(tid, x, src, tmp):
    """trascrizione automatica, solo per quello che Paolo ha chiesto e non ha gia' caricato lui"""
    d = os.path.join(ROOT, 'ascolti', tid)
    want_mid, want_pdf = opzioni(x)
    own_mid = x.get('midi') and not x['midi'].get('auto')
    own_pdf = x.get('pdf') and not x['pdf'].get('auto')
    do_mid, do_pdf = want_mid and not own_mid, want_pdf and not own_pdf
    for k, f, on in (('midi', 'auto.mid.enc', do_mid), ('pdf', 'auto.pdf.enc', do_pdf)):
        if not on and x.get(k) and x[k].get('auto'):
            x.pop(k)
            if os.path.exists(os.path.join(d, f)): os.remove(os.path.join(d, f))
    if not (do_mid or do_pdf):
        return
    try:
        mid, xml = os.path.join(tmp, 'auto.mid'), os.path.join(tmp, 'auto.musicxml') if do_pdf else None
        info = trascrivi(src, mid, xml, x.get('t'))
        x['trascr'] = info
        if do_mid:
            enc_file(mid, os.path.join(d, 'auto.mid.enc'))
            x['midi'] = {'f': 'auto.mid.enc', 'auto': True}
        if do_pdf:
            try:
                pdf = os.path.join(tmp, 'auto.pdf')
                pdf_da_xml(xml, pdf)
                enc_file(pdf, os.path.join(d, 'auto.pdf.enc'))
                x['pdf'] = {'f': 'auto.pdf.enc', 'auto': True}
            except Exception:
                traceback.print_exc()
                x['avvisi'].append('Partitura automatica non riuscita.')
    except Exception:
        traceback.print_exc()
        x['avvisi'].append('Trascrizione automatica non riuscita.')


def elabora(tid, x, tmp):
    d = os.path.join(ROOT, 'ascolti', tid)
    src = os.path.join(d, 'originale.mp3.enc')
    x['avvisi'] = []
    if os.path.exists(src):
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
        trascrizione(tid, x, stems.get('piano', wav), tmp)
        os.remove(src)
    else:  # "rifai la trascrizione": riparte dall'audio gia' pubblicato (traccia del piano se c'e')
        k = 'piano' if 'piano' in (x.get('stems') or []) else 'mix'
        mp3, wav = os.path.join(tmp, k + '.mp3'), os.path.join(tmp, 'brano.wav')
        open(mp3, 'wb').write(dec(open(os.path.join(d, k + '.mp3.enc'), 'rb').read()))
        sh('ffmpeg', '-loglevel', 'error', '-y', '-i', mp3, '-ar', '44100', '-ac', '2', wav)
        trascrizione(tid, x, wav, tmp)
    x.pop('rifai', None)
    if not x['avvisi']:
        del x['avvisi']
    x['stato'] = 'pronto'
    x.pop('errore', None)
    x['agg'] = datetime.date.today().isoformat()


def da_fare(cat):
    d = lambda t, f: os.path.exists(os.path.join(ROOT, 'ascolti', t, f))
    return [t for t, x in cat.items() if x.get('stato') == 'elaborazione'
            and (d(t, 'originale.mp3.enc') or (x.get('rifai') and d(t, 'mix.mp3.enc')))]


def main():
    cat = json.load(open(CAT))
    todo = da_fare(cat)
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
    if '--controlla' in sys.argv:  # per GitHub Actions: c'e' qualcosa da fare?
        print('si' if da_fare(json.load(open(CAT))) else 'no')
    else:
        main()

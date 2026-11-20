"""Ascolti consigliati: elabora i file caricati dal sito nei brani (gira da solo su GitHub Actions).

  SCUOLA_PW=... python3 tools/elabora.py [CARTELLA_SITO]      (--controlla: dice solo se c'e' qualcosa da fare)

Ogni brano di ascolti/catalog.json e' una «casella» con una lista di risorse "r":
  {id, k: audio|video|pdf|midi|yt, c: categoria, t: titolo, f: file (dentro ascolti/<brano>/), st: stato, ...}
Le risorse con st "elaborazione" vengono preparate qui; i file caricati sono in ascolti/<brano>/<risorsa>/originale.*.enc
  audio: tipo "band" -> tracce separate con Demucs (htdemucs_6s); mp3 160k (+ tracce 128k); poi, se chiesto
         (midi_auto / pdf_auto) e se non ci sono gia' file di Paolo: trascrizione (tools/trascrivi.py:
         Transkun + Beat This!) -> nuove risorse "Trascrizione automatica" (MIDI e/o partitura MuseScore).
         "rifai": rifa' solo la trascrizione dall'audio gia' pubblicato.
  video: H.264 720p con ffmpeg (avvio rapido in streaming) + immagine di copertina.
  pdf / img (partitura caricata da Paolo, PDF o pagine in foto/screenshot) con "omr": "attesa":
         lettura ottica (tools/omr.py: Audiveris + music21) -> risorsa MIDI "<id>-omr" da suonare sulla tastiera.
Tutto resta cifrato con la password della Scuola; i file in chiaro non vengono MAI scritti nel repository (e' pubblico).
Comandi esterni: Audiveris (AUDIVERIS) e python con music21 (OMR_PY) per le partiture, ffmpeg, python con demucs (DEMUCS_PY), python con transkun/beat_this (TR_PY), mscore3 (MSCORE)."""
import sys, os, re, json, shutil, subprocess, tempfile, traceback, datetime
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
OMR_PY = os.environ.get('OMR_PY', sys.executable)
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


def trascrizione(bid, x, r, src, tmp):
    """trascrizione automatica di una registrazione: crea/aggiorna le risorse derivate <id>-mid e <id>-pdf"""
    d = os.path.join(ROOT, 'ascolti', bid)
    want_mid, want_pdf = r.get('midi_auto'), r.get('pdf_auto')
    own = {k for q in x['r'] if not q.get('auto') for k in [q.get('k')]}
    jobs = {'midi': want_mid and 'midi' not in own, 'pdf': want_pdf and 'pdf' not in own}
    for k, on in jobs.items():
        rid = r['id'] + ('-mid' if k == 'midi' else '-pdf')
        old = next((q for q in x['r'] if q['id'] == rid), None)
        if not on and old:
            x['r'].remove(old)
            f = os.path.join(d, old['f'])
            if os.path.exists(f): os.remove(f)
    if not any(jobs.values()):
        return
    try:
        mid = os.path.join(tmp, 'auto.mid')
        xml = os.path.join(tmp, 'auto.musicxml') if jobs['pdf'] else None
        info = trascrivi(src, mid, xml, x.get('t'))
        made = []
        if jobs['midi']:
            enc_file(mid, os.path.join(d, r['id'], 'auto.mid.enc'))
            made.append(('midi', 'auto.mid.enc', 'MIDI'))
        if jobs['pdf']:
            try:
                pdf = os.path.join(tmp, 'auto.pdf')
                pdf_da_xml(xml, pdf)
                enc_file(pdf, os.path.join(d, r['id'], 'auto.pdf.enc'))
                made.append(('pdf', 'auto.pdf.enc', 'Partitura'))
            except Exception:
                traceback.print_exc()
                r.setdefault('avvisi', []).append('Partitura automatica non riuscita.')
        for k, f, nome in made:
            rid = r['id'] + ('-mid' if k == 'midi' else '-pdf')
            q = next((q for q in x['r'] if q['id'] == rid), None)
            if not q:
                q = {'id': rid}
                x['r'].append(q)
            q.update({'k': k, 'c': 'Trascrizione automatica', 't': nome + ' automatico da «' + r.get('t', 'registrazione') + '»' if k == 'midi'
                      else 'Partitura automatica da «' + r.get('t', 'registrazione') + '»', 'f': r['id'] + '/' + f,
                      'auto': True, 'da': r['id'], 'st': 'pronto', 'info': info})
    except Exception:
        traceback.print_exc()
        r.setdefault('avvisi', []).append('Trascrizione automatica non riuscita.')


def in_wav(src_enc, ext, tmp):
    raw = os.path.join(tmp, 'in.' + ext)
    open(raw, 'wb').write(dec(open(src_enc, 'rb').read()))
    wav = os.path.join(tmp, 'brano.wav')
    sh('ffmpeg', '-loglevel', 'error', '-y', '-i', raw, '-vn', '-ar', '44100', '-ac', '2', wav)
    return raw, wav


def originale(d, rid):
    fs = [f for f in os.listdir(os.path.join(d, rid)) if f.startswith('originale.')] if os.path.isdir(os.path.join(d, rid)) else []
    return os.path.join(d, rid, fs[0]) if fs else None


def audio(bid, x, r, tmp):
    d = os.path.join(ROOT, 'ascolti', bid)
    src = originale(d, r['id'])
    if src:
        raw, wav = in_wav(src, src.split('.')[-2], tmp)
        stems = separa(wav, os.path.join(tmp, 'sep')) if r.get('tipo') == 'band' else {}
        files = {'mix': (wav, '160k')}
        files.update({k: (v, '128k') for k, v in stems.items()})
        for k, (w, br) in files.items():
            p = os.path.join(tmp, k + '.mp3')
            sh('ffmpeg', '-loglevel', 'error', '-y', '-i', w, '-c:a', 'libmp3lame', '-b:a', br, p)
            enc_file(p, os.path.join(d, r['id'], k + '.mp3.enc'))
        r['stems'] = [k for k in ('drums', 'bass', 'piano', 'vocals', 'other') if k in stems]
        r['dur'] = dur(wav)
        r['f'] = r['id'] + '/mix.mp3.enc'
        trascrizione(bid, x, r, stems.get('piano', wav), tmp)
        os.remove(src)
    else:  # rifai: dall'audio gia' pubblicato (traccia del piano se c'e')
        k = 'piano' if 'piano' in (r.get('stems') or []) else 'mix'
        _, wav = in_wav(os.path.join(d, r['id'], k + '.mp3.enc'), 'mp3', tmp)
        trascrizione(bid, x, r, wav, tmp)


def video(bid, x, r, tmp):
    d = os.path.join(ROOT, 'ascolti', bid)
    src = originale(d, r['id'])
    raw = os.path.join(tmp, 'in.' + src.split('.')[-2])
    open(raw, 'wb').write(dec(open(src, 'rb').read()))
    out, jpg = os.path.join(tmp, 'video.mp4'), os.path.join(tmp, 'poster.jpg')
    sh('ffmpeg', '-loglevel', 'error', '-y', '-i', raw, '-vf', "scale='min(1280,iw)':-2", '-c:v', 'libx264', '-preset', 'veryfast',
       '-crf', '26', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', out)
    t = dur(out)
    sh('ffmpeg', '-loglevel', 'error', '-y', '-ss', str(round(min(t * 0.15, 20), 1)), '-i', out, '-frames:v', '1', '-vf', 'scale=640:-2', '-q:v', '5', jpg)
    enc_file(out, os.path.join(d, r['id'], 'video.mp4.enc'))
    enc_file(jpg, os.path.join(d, r['id'], 'poster.jpg.enc'))
    r.update({'f': r['id'] + '/video.mp4.enc', 'poster': r['id'] + '/poster.jpg.enc', 'dur': t})
    os.remove(src)


def partitura_midi(bid, x, r, tmp):
    """partitura caricata (PDF o immagini) -> MIDI per la tastiera, risorsa derivata <id>-omr"""
    d = os.path.join(ROOT, 'ascolti', bid)
    fs = r['f'] if isinstance(r['f'], list) else [r['f']]
    ins = []
    for i, f in enumerate(fs):
        ext = f[:-4].rsplit('.', 1)[-1]  # p1.jpg.enc -> jpg
        p = os.path.join(tmp, 'pagina%03d.%s' % (i + 1, ext))
        open(p, 'wb').write(dec(open(os.path.join(d, f), 'rb').read()))
        ins.append(p)
    mid = os.path.join(tmp, 'omr.mid')
    cmd = [OMR_PY, os.path.join(ROOT, 'tools', 'omr.py'), mid] + ins
    print('$', ' '.join(cmd), flush=True)
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=3000)
    sys.stderr.write(p.stderr[-4000:])
    if p.returncode:
        righe = [l for l in p.stderr.strip().splitlines() if l.strip()]
        raise RuntimeError(righe[-1] if righe else 'lettura della partitura non riuscita')
    info = json.loads(p.stdout.strip().splitlines()[-1])
    enc_file(mid, os.path.join(d, r['id'], 'omr.mid.enc'))
    rid = r['id'] + '-omr'
    q = next((q for q in x['r'] if q['id'] == rid), None)
    if not q:
        q = {'id': rid}
        x['r'].insert(x['r'].index(r) + 1, q)
    q.update({'k': 'midi', 'c': 'MIDI', 't': 'MIDI da «' + r.get('t', 'partitura') + '»', 'f': r['id'] + '/omr.mid.enc',
              'da': r['id'], 'omr': True, 'st': 'pronto', 'info': info})


def volume(f):
    o = subprocess.run(['ffmpeg', '-hide_banner', '-i', f, '-af', 'volumedetect', '-f', 'null', '-'], capture_output=True, text=True).stderr
    m = re.search(r'mean_volume:\s*(-?[\d.]+) dB', o)
    return float(m.group(1)) if m else None


def senza_categoria(cat):
    """brani con una registrazione pronta ma senza libreria (Piano New Orleans / Stile New Orleans) ne' suggerimento"""
    return [bid for bid, x in cat.items() if not x.get('cat') and not x.get('cat_sugg')
            and any(r.get('k') == 'audio' and r.get('st') == 'pronto' for r in x.get('r', []))]


def suggerisci_categorie(cat):
    """piano solo -> Piano New Orleans; con piu' strumenti: guarda quanto pesa la traccia del piano rispetto al brano intero"""
    for bid in senza_categoria(cat):
        x = cat[bid]
        r = next(r for r in x['r'] if r.get('k') == 'audio' and r.get('st') == 'pronto')
        if r.get('tipo') != 'band':
            x['cat_sugg'] = 'piano'
            continue
        if 'piano' not in (r.get('stems') or []):
            x['cat_sugg'] = 'stile'
            continue
        tmp = tempfile.mkdtemp(prefix='cat-')
        try:
            d = os.path.join(ROOT, 'ascolti', bid, r['id'])
            v = {}
            for k in ('mix', 'piano'):
                f = os.path.join(tmp, k + '.mp3')
                open(f, 'wb').write(dec(open(os.path.join(d, k + '.mp3.enc'), 'rb').read()))
                v[k] = volume(f)
            diff = v['piano'] - v['mix'] if None not in v.values() else -99
            x['cat_sugg'] = 'piano' if diff > -10 else 'stile'
            print('categoria', bid, x['cat_sugg'], 'piano/brano dB:', round(diff, 1), flush=True)
        except Exception:
            traceback.print_exc()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def da_fare(cat, quale=None):
    out = []
    for bid, x in cat.items():
        d = os.path.join(ROOT, 'ascolti', bid)
        for r in x.get('r', []):
            if quale != 'omr' and r.get('st') == 'elaborazione' and (originale(d, r['id']) or (r.get('rifai') and r.get('k') == 'audio')):
                out.append((bid, r['id']))
            elif quale != 'audio' and r.get('omr') == 'attesa' and r.get('k') in ('pdf', 'img') and r.get('f'):
                out.append((bid, r['id']))
    return out


def main():
    cat = json.load(open(CAT))
    todo = da_fare(cat)
    print('da elaborare:', todo or 'nessuno', flush=True)
    for bid, rid in todo:
        x = cat[bid]
        r = next(q for q in x['r'] if q['id'] == rid)
        tmp = tempfile.mkdtemp(prefix='asc-')
        if r.get('omr') == 'attesa' and r['k'] in ('pdf', 'img'):
            try:
                partitura_midi(bid, x, r, tmp)
                r['omr'] = 'fatto'
                r.pop('omr_err', None)
                print('ok', bid, rid, 'MIDI dalla partitura', flush=True)
            except Exception as e:
                traceback.print_exc()
                r['omr'] = 'errore'
                r['omr_err'] = str(e)[-300:]
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            x['agg'] = datetime.date.today().isoformat()
            json.dump(cat, open(CAT, 'w'), ensure_ascii=False, indent=1)
            continue
        try:
            r.pop('avvisi', None)
            (video if r['k'] == 'video' else audio)(bid, x, r, tmp)
            r['st'] = 'pronto'
            r.pop('err', None)
            r.pop('rifai', None)
            print('ok', bid, rid, {k: r.get(k) for k in ('stems', 'dur', 'avvisi')}, flush=True)
        except Exception as e:
            traceback.print_exc()
            r['st'] = 'errore'
            r['err'] = str(e)[-300:]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        x['agg'] = datetime.date.today().isoformat()
        json.dump(cat, open(CAT, 'w'), ensure_ascii=False, indent=1)
    if senza_categoria(cat):
        suggerisci_categorie(cat)
        json.dump(cat, open(CAT, 'w'), ensure_ascii=False, indent=1)
    return todo


if __name__ == '__main__':
    if '--controlla' in sys.argv:  # per GitHub Actions: c'e' qualcosa da fare?
        c = json.load(open(CAT))
        print('si' if da_fare(c) or senza_categoria(c) else 'no')
    elif '--controlla-audio' in sys.argv or '--controlla-omr' in sys.argv:  # quali strumenti installare
        print('si' if da_fare(json.load(open(CAT)), 'audio' if '--controlla-audio' in sys.argv else 'omr') else 'no')
    else:
        main()

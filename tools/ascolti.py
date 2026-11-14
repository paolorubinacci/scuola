"""Ascolti consigliati: aggiunge un brano al sito con le tracce separate.

  SCUOLA_PW=... python3 tools/ascolti.py BRANO.mp3 ID [--modello 6s|4s]

ID e' l'identificativo del brano in ASC (src/app.html), es. tipitina.
Cosa fa:
  1. separa le tracce con Demucs:
     - 6s (htdemucs_6s, Meta): batteria, basso, piano, voce, chitarra, altro -> chitarra va in "altro"
     - 4s (htdemucs, fallback): batteria, basso, voce, altro (il piano resta dentro "altro")
     Il 6s ha bisogno del file dei pesi (scaricato da dl.fbaipublicfiles.com); se non e' raggiungibile si usa il 4s
     (pacchetto npm "demucs", pesi inclusi: npm install --ignore-scripts demucs in ~/sep, o cartella DEMUCS_JS).
  2. codifica: originale (mix) mp3 160k, tracce mp3 128k, stessa durata
  3. cifra tutto con la password della Scuola -> ascolti/ID/*.mp3.enc
  4. aggiorna ascolti/index.json (pubblico: solo id, tracce, durata)
I file audio in chiaro non vanno MAI committati (il repository e' pubblico)."""
import sys, os, json, shutil, subprocess, tempfile, importlib.util

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location('sc', os.path.join(R, 'tools', 'scuola.py'))


def enc_file(src, dst):
    sys.argv = ['scuola.py', 'enc', src, dst]
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)


def sh(*a, **k):
    print('$', ' '.join(map(str, a)))
    subprocess.run(a, check=True, **k)


def dur(f):
    o = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', f],
                       capture_output=True, text=True, check=True).stdout
    return round(float(o), 2)


def sep6(wav, out):
    sh(sys.executable, '-m', 'demucs', '-n', 'htdemucs_6s', '-o', out, wav)
    d = os.path.join(out, 'htdemucs_6s', os.path.splitext(os.path.basename(wav))[0])
    other = os.path.join(d, 'other_all.wav')
    sh('ffmpeg', '-loglevel', 'error', '-y', '-i', os.path.join(d, 'other.wav'), '-i', os.path.join(d, 'guitar.wav'),
       '-filter_complex', 'amix=inputs=2:normalize=0', other)
    return {'drums': f'{d}/drums.wav', 'bass': f'{d}/bass.wav', 'piano': f'{d}/piano.wav',
            'vocals': f'{d}/vocals.wav', 'other': other}, 'htdemucs_6s'


def sep4(wav, out):
    cands = [os.environ.get('DEMUCS_JS', ''), os.path.expanduser('~/sep/node_modules/demucs'), '/home/claude/sep/node_modules/demucs']
    js = next((c for c in cands if c and os.path.exists(os.path.join(c, 'dist', 'cli.js'))), None)
    if not js:
        raise SystemExit('Manca il separatore a 4 tracce: mkdir ~/sep && cd ~/sep && npm install --ignore-scripts demucs')
    sh('node', os.path.join(js, 'dist', 'cli.js'), wav, '-o', out)
    d = os.path.join(out, os.path.splitext(os.path.basename(wav))[0])
    return {k: f'{d}/{k}.wav' for k in ('drums', 'bass', 'vocals', 'other')}, 'htdemucs'


def main():
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    src, tid = sys.argv[1], sys.argv[2]
    mode = sys.argv[sys.argv.index('--modello') + 1] if '--modello' in sys.argv else '6s'
    os.environ['SCUOLA_PW']  # fallisce subito se manca la password
    tmp = tempfile.mkdtemp(prefix='asc-')
    wav = os.path.join(tmp, 'brano.wav')
    sh('ffmpeg', '-loglevel', 'error', '-y', '-i', src, '-ar', '44100', '-ac', '2', wav)
    stems = None
    if mode == '6s':
        try:
            stems, model = sep6(wav, os.path.join(tmp, 'sep'))
        except Exception as e:
            print('!! htdemucs_6s non disponibile (%s): uso il modello a 4 tracce, il piano resta in "altro"' % e)
    if stems is None:
        stems, model = sep4(wav, os.path.join(tmp, 'sep'))
    outd = os.path.join(R, 'ascolti', tid)
    os.makedirs(outd, exist_ok=True)
    plain = os.path.join(tmp, 'mp3')
    os.makedirs(plain)
    files = {'mix': (wav, '160k')}
    files.update({k: (v, '128k') for k, v in stems.items()})
    for k, (w, br) in files.items():
        p = os.path.join(plain, k + '.mp3')
        sh('ffmpeg', '-loglevel', 'error', '-y', '-i', w, '-c:a', 'libmp3lame', '-b:a', br, p)
        enc_file(p, os.path.join(outd, k + '.mp3.enc'))
    idx_p = os.path.join(R, 'ascolti', 'index.json')
    idx = json.load(open(idx_p)) if os.path.exists(idx_p) else {}
    idx[tid] = {'stems': [k for k in ('drums', 'bass', 'piano', 'vocals', 'other') if k in stems],
                'dur': dur(wav), 'model': model}
    json.dump(idx, open(idx_p, 'w'), ensure_ascii=False, indent=1)
    shutil.rmtree(tmp)
    print('ok', tid, idx[tid])


if __name__ == '__main__':
    main()

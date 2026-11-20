"""Diario di pratica della Scuola (gira su GitHub Actions, workflow diario.yml).

Il sito salva ogni sessione in diario/voci/<id>.json.enc (cifrata) e, se c'e', il messaggio vocale in diario/voci/<id>.<ext>.enc;
diario/indice.json elenca solo id e data. Questo script:
  1. trascrive i messaggi vocali (faster-whisper, italiano)                      -> diario/elab/<id>.json.enc  {trascr}
  2. se c'e' ANTHROPIC_API_KEY: mette in ordine note + trascrizione              -> diario/elab/<id>.json.enc  {ordinato}
  3. se c'e' ANTHROPIC_API_KEY: scrive il diario di viaggio della settimana       -> diario/settimane/<AAAA-Wss>.json.enc
REGOLA FERMA: solo riassunti di cio' che Paolo ha scritto o detto. Niente consigli, esercizi, valutazioni o contenuti aggiunti.

  python3 tools/diario.py [RADICE]                 elabora
  python3 tools/diario.py [RADICE] --controlla      stampa si/no (c'e' qualcosa da fare?)
  python3 tools/diario.py [RADICE] --controlla-audio  stampa si/no (servono le trascrizioni?)
Variabili: SCUOLA_PW (obbligatoria), ANTHROPIC_API_KEY e ANTHROPIC_MODEL (facoltative), WHISPER_MODEL (default small)."""
import sys, os, json, datetime, tempfile, traceback, urllib.request, urllib.error
from zoneinfo import ZoneInfo
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PW = os.environ['SCUOLA_PW']
SALT = bytes.fromhex(open(os.path.join(ROOT, 'tools', 'salt.hex')).read().strip())
KEY = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=SALT, iterations=200000).derive(PW.encode())
API = os.environ.get('ANTHROPIC_API_KEY', '').strip()
MODELS = [m for m in [os.environ.get('ANTHROPIC_MODEL', '').strip(), 'claude-sonnet-5-5', 'claude-sonnet-4-5', 'claude-3-5-sonnet-latest'] if m]
DIR = os.path.join(ROOT, 'diario')
TZ = ZoneInfo('Europe/Paris')


def dec(b):
    k = KEY if b[:16] == SALT else PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=b[:16], iterations=200000).derive(PW.encode())
    return AESGCM(k).decrypt(b[16:28], b[28:], None)


def enc(data):
    iv = os.urandom(12)
    return SALT + iv + AESGCM(KEY).encrypt(iv, data, None)


def leggi(rel):
    p = os.path.join(DIR, rel)
    return json.loads(dec(open(p, 'rb').read())) if os.path.exists(p) else None


def scrivi(rel, obj):
    p = os.path.join(DIR, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, 'wb').write(enc(json.dumps(obj, ensure_ascii=False).encode()))


def settimana(at_ms):
    d = datetime.datetime.fromtimestamp(at_ms / 1000, TZ)
    y, w, _ = d.isocalendar()
    return '%d-W%02d' % (y, w)


def voci():
    idx = json.load(open(os.path.join(DIR, 'indice.json'))) if os.path.exists(os.path.join(DIR, 'indice.json')) else {'voci': []}
    out = []
    for v in idx.get('voci', []):
        x = leggi('voci/%s.json.enc' % v['id'])
        if x:
            x['id'] = v['id']
            out.append(x)
    return sorted(out, key=lambda x: x['at'])


def audio_di(v):
    return os.path.join(DIR, 'voci', '%s.%s.enc' % (v['id'], v['audio'])) if v.get('audio') else None


def lavoro(vs):
    """cosa manca: trascrizioni, note in ordine, settimane da riscrivere"""
    tr, ord_, sett = [], [], set()
    for v in vs:
        e = leggi('elab/%s.json.enc' % v['id']) or {}
        a = audio_di(v)
        if a and os.path.exists(a) and not e.get('trascr') and not e.get('err'):
            tr.append(v)
        if API and (v.get('note') or e.get('trascr') or (a and os.path.exists(a))) and e.get('fonte') != fonte(v, e):
            ord_.append(v)
    if API:
        per = {}
        for v in vs:
            per.setdefault(settimana(v['at']), []).append(v)
        for w, l in per.items():
            s = leggi('settimane/%s.json.enc' % w) or {}
            if s.get('firma') != firma(l):
                sett.add(w)
    return tr, ord_, sett


def fonte(v, e):
    return json.dumps([v.get('note', ''), e.get('trascr', ''), v.get('what', '')], ensure_ascii=False)


def firma(l):
    return json.dumps(sorted([v['id'] + ':' + str(v.get('agg', v['at'])) for v in l]))


def trascrivi(lista):
    from faster_whisper import WhisperModel
    m = WhisperModel(os.environ.get('WHISPER_MODEL', 'small'), device='cpu', compute_type='int8')
    for v in lista:
        e = leggi('elab/%s.json.enc' % v['id']) or {}
        tmp = tempfile.mkdtemp(prefix='voce-')
        try:
            f = os.path.join(tmp, 'voce.' + v['audio'])
            open(f, 'wb').write(dec(open(audio_di(v), 'rb').read()))
            segs, info = m.transcribe(f, language='it', vad_filter=True, beam_size=5)
            e['trascr'] = ' '.join(s.text.strip() for s in segs).strip() or '(nessuna parola riconosciuta)'
            e.pop('err', None)
            print('trascritto', v['id'], len(e['trascr']), 'caratteri', flush=True)
        except Exception as ex:
            traceback.print_exc()
            e['err'] = 'Trascrizione non riuscita: ' + str(ex)[-200:]
        scrivi('elab/%s.json.enc' % v['id'], e)


REGOLE = ("Regole ferme: usa SOLO le informazioni presenti nel testo che ricevi. Non aggiungere consigli, esercizi, suggerimenti, "
          "valutazioni, spiegazioni musicali o contenuti tuoi, e non dire cosa fare la prossima volta. Non inventare nomi, brani, "
          "numeri o fatti. Correggi solo gli errori evidenti della trascrizione automatica (nomi di musicisti e brani scritti male). "
          "Se un passaggio e' incomprensibile, lascialo fuori. Scrivi in italiano, testo semplice senza markdown tranne i trattini degli elenchi.")


def claude(system, user, max_tokens=1200):
    last = None
    for model in MODELS:
        body = json.dumps({'model': model, 'max_tokens': max_tokens, 'system': system, 'messages': [{'role': 'user', 'content': user}]}).encode()
        req = urllib.request.Request('https://api.anthropic.com/v1/messages', data=body, headers={
            'x-api-key': API, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'})
        try:
            r = json.load(urllib.request.urlopen(req, timeout=180))
            return ''.join(b.get('text', '') for b in r.get('content', []) if b.get('type') == 'text').strip()
        except urllib.error.HTTPError as ex:
            last = '%s %s' % (ex.code, ex.read()[:300])
            if ex.code in (400, 404) and 'model' in last.lower():
                continue
            raise RuntimeError(last)
    raise RuntimeError(last or 'nessun modello disponibile')


def descr(v, e):
    d = datetime.datetime.fromtimestamp(v['at'] / 1000, TZ)
    righe = ['Data: %s' % d.strftime('%d/%m/%Y'), 'Minuti di pratica: %d' % round(v.get('ms', 0) / 60000)]
    if v.get('what'): righe.append('Su cosa: ' + v['what'])
    if v.get('bpm'): righe.append('Tempo raggiunto: %s bpm' % v['bpm'])
    if v.get('note'): righe.append('Note scritte: ' + v['note'])
    if e.get('trascr'): righe.append('Messaggio vocale (trascrizione automatica): ' + e['trascr'])
    return '\n'.join(righe)


def ordina(lista):
    sys_ = ("Sei l'archivista del diario di pratica di Paolo, pianista. Ricevi una sessione di pratica: le sue note scritte e/o la "
            "trascrizione automatica di un suo messaggio vocale. Riscrivi il contenuto in un breve elenco puntato, chiaro e ordinato "
            "(cosa ha esercitato, cosa ha notato o imparato, difficolta' che ha nominato lui). " + REGOLE)
    for v in lista:
        e = leggi('elab/%s.json.enc' % v['id']) or {}
        try:
            e['ordinato'] = claude(sys_, descr(v, e), 700)
            e['fonte'] = fonte(v, e)
            e.pop('err_ord', None)
            print('in ordine', v['id'], flush=True)
        except Exception as ex:
            traceback.print_exc()
            e['err_ord'] = str(ex)[-200:]
        scrivi('elab/%s.json.enc' % v['id'], e)


def settimane(ws, vs):
    sys_ = ("Sei l'archivista del diario di pratica di Paolo, pianista. Ricevi tutte le sessioni di una settimana. Scrivi il suo "
            "«diario di viaggio» della settimana: un breve paragrafo che racconta cosa ha fatto (in seconda persona, «hai…»), poi "
            "«Cose nuove imparate:» con un elenco puntato, poi «Su cosa hai lavorato:» con un elenco puntato. Riporta il totale dei "
            "minuti che ricevi. Non scrivere nulla sulla settimana successiva. " + REGOLE)
    for w in sorted(ws):
        l = [v for v in vs if settimana(v['at']) == w]
        testo = '\n\n'.join(descr(v, leggi('elab/%s.json.enc' % v['id']) or {}) for v in l)
        tot = round(sum(v.get('ms', 0) for v in l) / 60000)
        try:
            out = claude(sys_, 'Settimana %s. Totale minuti di pratica: %d. Sessioni:\n\n%s' % (w, tot, testo), 1500)
            scrivi('settimane/%s.json.enc' % w, {'testo': out, 'firma': firma(l), 'agg': int(datetime.datetime.now().timestamp() * 1000)})
            print('settimana', w, flush=True)
        except Exception:
            traceback.print_exc()


def main():
    vs = voci()
    tr, ord_, sett = lavoro(vs)
    if '--controlla-audio' in sys.argv:
        print('si' if tr else 'no')
        return
    if '--controlla' in sys.argv:
        print('si' if (tr or ord_ or sett) else 'no')
        return
    print('da trascrivere:', len(tr), '· da ordinare:', len(ord_), '· settimane:', sorted(sett), '· riassunti:', 'si' if API else 'no (manca ANTHROPIC_API_KEY)', flush=True)
    if tr:
        trascrivi(tr)
    tr, ord_, sett = lavoro(vs)   # dopo le trascrizioni cambiano le fonti da riassumere
    if ord_:
        ordina(ord_)
    tr, ord_, sett = lavoro(vs)
    if sett:
        settimane(sett, vs)


if __name__ == '__main__':
    main()

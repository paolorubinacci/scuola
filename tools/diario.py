"""Diario di pratica della Scuola (gira su GitHub Actions, workflow diario.yml).

Il sito salva ogni sessione in diario/voci/<id>.json.enc (cifrata) e, se c'e', il messaggio vocale in diario/voci/<id>.<ext>.enc;
diario/indice.json elenca solo id e data. Questo script:
  1. trascrive i messaggi vocali (faster-whisper, italiano)                      -> diario/elab/<id>.json.enc  {trascr}
  2. se c'e' ANTHROPIC_API_KEY: mette in ordine note + trascrizione              -> diario/elab/<id>.json.enc  {ordinato}
  3. se c'e' ANTHROPIC_API_KEY: scrive il diario di viaggio della settimana       -> diario/settimane/<AAAA-Wss>.json.enc
  4. «Chiudi la giornata»: diario/giorni/<AAAA-MM-GG>.json.enc con stato 'richiesta' -> riassunto del giorno + compiti
     che Paolo ha detto di voler esercitare (stato 'proposta'); il sito lo fa approvare e poi cancella i vocali.
Riassunti: Claude (ANTHROPIC_API_KEY) se c'e'; senza chiave, per «Chiudi la giornata» un modello aperto (Qwen) che gira
sul server di GitHub Actions con Ollama (LOCAL_LLM=http://127.0.0.1:11434, avviato dal workflow: tools/llm.sh).
REGOLA FERMA: solo riassunti di cio' che Paolo ha scritto o detto. Niente consigli, esercizi, valutazioni o contenuti aggiunti.

  python3 tools/diario.py [RADICE]                 elabora
  python3 tools/diario.py [RADICE] --controlla      stampa si/no (c'e' qualcosa da fare?)
  python3 tools/diario.py [RADICE] --controlla-audio  stampa si/no (servono le trascrizioni?)
Variabili: SCUOLA_PW (obbligatoria), ANTHROPIC_API_KEY e ANTHROPIC_MODEL (facoltative), WHISPER_MODEL (default small)."""
import sys, os, re, json, datetime, tempfile, traceback, urllib.request, urllib.error, difflib, unicodedata
from zoneinfo import ZoneInfo
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PW = os.environ['SCUOLA_PW']
SALT = bytes.fromhex(open(os.path.join(ROOT, 'tools', 'salt.hex')).read().strip())
KEY = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=SALT, iterations=200000).derive(PW.encode())
ANT = os.environ.get('ANTHROPIC_API_KEY', '').strip()
LOCAL = os.environ.get('LOCAL_LLM', '').strip()
API = ANT   # note in ordine e settimane: solo con Claude
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


def giorni():
    idx = json.load(open(os.path.join(DIR, 'indice.json'))) if os.path.exists(os.path.join(DIR, 'indice.json')) else {}
    out = []
    for d in idx.get('giorni', []):
        g = leggi('giorni/%s.json.enc' % d)
        if g:
            g['d'] = d
            out.append(g)
    return out


def da_chiudere():
    return [g for g in giorni() if g.get('stato') == 'richiesta']


def fonte(v, e):
    return json.dumps([v.get('note', ''), e.get('trascr', ''), v.get('what', '')], ensure_ascii=False)


def firma(l):
    gs = sorted({v['giorno'] for v in l if v.get('giorno')})
    return json.dumps(sorted([v['id'] + ':' + str(v.get('agg', v['at'])) for v in l]) + gs)


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
    if ANT:
        return anthropic(system, user, max_tokens)
    if LOCAL:
        return locale(system, user, max_tokens)
    raise RuntimeError('nessun modello per i riassunti')


def locale(system, user, max_tokens):
    body = json.dumps({'model': os.environ.get('LOCAL_MODEL', 'qwen2.5:7b'), 'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
                       'max_tokens': max_tokens, 'temperature': 0.1, 'response_format': {'type': 'json_object'}}).encode()
    req = urllib.request.Request(LOCAL.rstrip('/') + '/v1/chat/completions', data=body, headers={'Content-Type': 'application/json'})
    r = json.load(urllib.request.urlopen(req, timeout=1500))
    return r['choices'][0]['message']['content'].strip()


def anthropic(system, user, max_tokens=1200):
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
    if v.get('tempi'):
        righe.append('Percorso del tempo (metronomo/ritmi): ' + ' -> '.join('%s %s bpm (%d min)' % (t.get('s', ''), t.get('bpm'), round(t.get('sec', 0) / 60)) for t in v['tempi']))
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


STOP = set(('hai sei ho lavorato esercitato esercitata esercitati provato provata suonato suonata detto dici vuoi voglio volere '
             'voler vorrei oggi sessione anche sulla sullo sugli sulle delle della dello degli nella nelle negli questo questa '
             'questi queste quello quella quelli quelle come molto ancora dopo prima tutto tutti tutte sempre fare fatto fatta '
             'parte cosa cose perche quando mentre altro altra altri altre ogni proprio essere stato stata sono era erano '
             'sarebbe meglio dove nello alla alle allo agli dalla dalle dallo dagli dentro sopra sotto verso senza contro '
             'invece ripassare esercitare esercitarti esercitarmi lavorare lavorarci provare suonare portare').split())


def _norm(t):
    t = unicodedata.normalize('NFKD', str(t).lower())
    t = ''.join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r'[^a-z0-9]+', ' ', t).strip()


def _fedele(testo, fonte_txt, src):
    """La riga e' accettata solo se la citazione esiste davvero nelle note/trascrizioni
    e ogni parola di contenuto della riga compare nelle fonti (nessuna frase inventata)."""
    f = _norm(fonte_txt)
    if len(f) < 8:
        return False
    if f not in src:
        fw = f.split()
        best = 0
        sw = src.split()
        for k in range(0, max(1, len(sw) - len(fw) + 1)):
            r = difflib.SequenceMatcher(None, ' '.join(sw[k:k + len(fw)]), f).ratio()
            best = max(best, r)
            if best >= 0.86:
                break
        if best < 0.86:
            return False
    radici = {w[:5] for w in src.split() if len(w) >= 4}
    for w in _norm(testo).split():
        if len(w) < 4 or w in STOP or w.isdigit():
            continue
        if w[:5] not in radici:
            return False
    return True


def fatti(l):
    """Minuti, lezioni e metronomo: li scrive il sistema dai dati delle sessioni, non il modello."""
    tot = round(sum(v.get('ms', 0) for v in l) / 60000)
    cosa = []
    for v in sorted(l, key=lambda v: v['at']):
        w = (v.get('what') or '').strip()
        if w and w not in cosa:
            cosa.append(w)
    bpm = [v['bpm'] for v in l if v.get('bpm')] + [t.get('bpm') for v in l for t in (v.get('tempi') or []) if t.get('bpm')]
    righe = ['Totale: %d min di pratica in %d %s' % (tot, len(l), 'sessione' if len(l) == 1 else 'sessioni')]
    if cosa:
        righe.append('- Su cosa: ' + ' · '.join(cosa))
    if bpm:
        lo, hi = min(bpm), max(bpm)
        righe.append('- Metronomo: ' + ('%s bpm' % lo if lo == hi else 'da %s a %s bpm' % (lo, hi)))
    return righe


def chiudi(gs, vs):
    sys_ = ("Ricevi le note scritte e le trascrizioni automatiche dei messaggi vocali di Paolo, pianista, dalle sue sessioni di "
            "pratica. Devi solo ESTRARRE quello che ha detto lui, senza aggiungere niente. Rispondi SOLO con un oggetto JSON:\n"
            "{\"punti\": [{\"testo\": \"...\", \"fonte\": \"...\"}], \"compiti\": [{\"testo\": \"...\", \"fonte\": \"...\"}]}\n"
            "\"punti\": le cose su cui dice di essersi esercitato e quello che dice di aver notato. \"testo\" e' la sua frase, "
            "accorciata, alla seconda persona («Hai lavorato su…»), usando SOLO parole che compaiono nella fonte. \"fonte\" e' la "
            "frase copiata ALLA LETTERA dal testo che ricevi, da cui viene il punto.\n"
            "\"compiti\": solo le cose che dice esplicitamente di voler fare, esercitare o ripassare in futuro, con la stessa forma "
            "(testo breve + fonte copiata alla lettera). Se non ne dice, lista vuota.\n"
            "Vietato: conclusioni, valutazioni, progressi («hai migliorato», «ti aiuta a…»), consigli, spiegazioni, cose che lui "
            "non ha detto. Non scrivere minuti o bpm: li aggiunge il sistema. Se una frase e' incomprensibile, saltala.")
    for g in gs:
        l = [v for v in vs if v['id'] in g.get('voci', [])]
        try:
            if not l:
                raise RuntimeError('nessuna sessione trovata per questa giornata')
            pezzi = []
            for v in sorted(l, key=lambda v: v['at']):
                e = leggi('elab/%s.json.enc' % v['id']) or {}
                if v.get('note'):
                    pezzi.append('Nota scritta: ' + v['note'])
                if e.get('trascr'):
                    pezzi.append('Messaggio vocale: ' + e['trascr'])
            if g.get('nota'):
                pezzi.append('Aggiunta di Paolo: ' + g['nota'])
            punti, compiti = [], []
            if pezzi:
                testo = '\n\n'.join(pezzi)
                src = _norm(testo)
                out = claude(sys_, testo, 1500)
                j = json.loads(out[out.index('{'):out.rindex('}') + 1])
                for k, dest in (('punti', punti), ('compiti', compiti)):
                    for it in j.get(k) or []:
                        if isinstance(it, dict) and it.get('testo') and _fedele(it['testo'], it.get('fonte', ''), src):
                            t = str(it['testo']).strip().rstrip('.')
                            if t not in dest:
                                dest.append(t)
                        else:
                            print('scartato (non fedele)', flush=True)
            g['riassunto'] = '\n'.join(fatti(l) + ['- ' + t for t in punti])
            g['compiti'] = compiti
            g['stato'] = 'proposta'
            g.pop('err', None)
            print('giornata', g['d'], len(punti), 'punti', len(compiti), 'compiti', flush=True)
        except Exception as ex:
            traceback.print_exc()
            g['err'] = 'Riassunto non riuscito: ' + str(ex)[-200:]
            g['stato'] = 'errore'
        g['agg'] = int(datetime.datetime.now().timestamp() * 1000)
        scrivi('giorni/%s.json.enc' % g['d'], g)


def settimane(ws, vs):
    sys_ = ("Sei l'archivista del diario di pratica di Paolo, pianista. Ricevi tutte le sessioni di una settimana. Scrivi il suo "
            "«diario di viaggio» della settimana: un breve paragrafo che racconta cosa ha fatto (in seconda persona, «hai…»), poi "
            "«Cose nuove imparate:» con un elenco puntato, poi «Su cosa hai lavorato:» con un elenco puntato. Riporta il totale dei "
            "minuti che ricevi. Non scrivere nulla sulla settimana successiva. " + REGOLE)
    for w in sorted(ws):
        l = [v for v in vs if settimana(v['at']) == w]
        chiusi = {g['d']: g for g in giorni() if g.get('stato') == 'approvata'}
        testo = '\n\n'.join(descr(v, leggi('elab/%s.json.enc' % v['id']) or {}) for v in l if not v.get('giorno'))
        testo += ''.join('\n\nRiassunto approvato della giornata %s:\n%s' % (d, chiusi[d].get('riassunto', '')) for d in sorted({v['giorno'] for v in l if v.get('giorno') in chiusi}))
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
    if '--controlla-locale' in sys.argv:
        print('si' if (da_chiudere() and not ANT) else 'no')
        return
    if '--controlla' in sys.argv:
        print('si' if (tr or ord_ or sett or da_chiudere()) else 'no')
        return
    print('da trascrivere:', len(tr), '· da ordinare:', len(ord_), '· settimane:', sorted(sett), '· riassunti:', 'Claude' if ANT else 'modello locale' if LOCAL else 'no', flush=True)
    if tr:
        trascrivi(tr)
    tr, ord_, sett = lavoro(vs)   # dopo le trascrizioni cambiano le fonti da riassumere
    gs = da_chiudere()
    if gs:
        chiudi(gs, vs)
    if ord_:
        ordina(ord_)
    tr, ord_, sett = lavoro(vs)
    if sett:
        settimane(sett, vs)


if __name__ == '__main__':
    main()

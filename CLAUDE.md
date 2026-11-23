# Scuola · istruzioni per Claude

Sito-scuola personale di Paolo: https://scuola.paolorubinacci.com (repository pubblico: tutti i contenuti sono cifrati).
Prima di toccare qualcosa: `git pull --rebase`. Più chat lavorano sullo stesso repository.

## Regola ferma sui contenuti
Il corso è l'unica fonte. Niente brani, esempi, contesti o spiegazioni che non vengano dal video o dal PDF della lezione,
a meno che Paolo non lo chieda. Il testo del PDF si cita alla lettera; il parlato si trascrive con i minuti del player del corso.

## Come costruire una lezione (video + PDF)
Prima di scrivere, confronta video e PDF e scegli una delle due forme. **Nel dubbio, sempre la forma B.**

**A · Intrecciata** (solo se video e PDF vanno nello stesso ordine e parlano degli stessi esempi):
trascrizione del video con i passaggi suonati (`clip`), e la parte del PDF inserita nel punto giusto.
Si usa solo se OGNI esempio del PDF corrisponde con certezza a un momento del video (stesse note, o il tutor lo nomina).

**B · Video integrale + PDF nel suo ordine** (quando l'ordine non coincide, o gli esempi del video sono diversi da quelli del PDF):
1. `{"t":"parte","id":"video","kick":"Parte 1","text":"Il video"}`, poi un blocco `film` con il video INTERO (niente tagli, niente rimontaggio):
   `{"t":"film","src":"clips/lN-film.mp4.enc","dur":"11:48","sezioni":[{"da":"0:05","a":"0:55","titolo":"…","testo":"lN-s1","pdf":["lN-pdf2"]}],"suonati":[{"da":"0:17","a":"0:31","label":"…"}]}`
   - `sezioni`: solo dove il cambio di argomento è chiaro da quello che dice il tutor. Titoli brevi, descrittivi, senza interpretazioni.
   - `suonati`: tutti i momenti in cui suona (sulla barra diventano segni dorati; toccandoli si ripetono in loop).
   - `pdf`: SOLO se l'associazione è certa (il tutor nomina quell'esempio, o suona esattamente le note scritte). Altrimenti niente link.
   - Il lettore mostra solo la sezione in corso (titolo, ‹ ›, i momenti suonati di quella sezione, che si ripetono in loop): niente liste lunghe.
   - Le partiture del PDF NON le abbina Claude: le abbina Paolo dal sito («🔗 Abbina partitura», per ogni momento suonato).
     Si salvano in `abbinamenti/abbinamenti.json.enc` ({"nola-7":{"1:26":["img/….png.enc"]}}); durante quel momento
     «♫ Partitura» le mostra sopra il video, in alto (lontano dalle mani). Sotto ogni partitura del PDF compare «▶ Nel video».
   - Sotto il video c'è l'indice delle sezioni (numerate come sulla barra). La trascrizione resta chiusa dietro «Accedi alla trascrizione»;
     il PDF resta intero, con titoli sobri numerati («PDF · 1») e un indice iniziale: il font Nola solo per i titoli delle Parti.
   - «Concetti chiave»: un riquadro quadrato per CATEGORIA (ritmo, armonia, musicisti…), con dentro l’elenco dei suoi concetti; mai due riquadri con la stessa categoria (il rendering raggruppa da solo per `g`).
2. Sotto, la trascrizione divisa con le stesse sezioni: `{"t":"h","id":"lN-s1","text":"…"}` + paragrafi `p` con `time` (i minuti diventano link al punto del video).
3. `{"t":"parte","id":"pdf","kick":"Parte 2","text":"Il PDF, nell'ordine in cui è scritto"}`, poi il PDF dall'inizio alla fine, nel SUO ordine:
   titoli `{"t":"h","id":"lN-pdf1","text":"…"}`, testo alla lettera (`quote`), partiture (`img`) con la loro tastiera (`kb`).
   OGNI partitura con note ha la sua tastiera (`kb`) subito dopo l'`img` (anche più di una). Dalla lezione 7 in poi
   (o con `"kbHide":true` sulla lezione) le tastiere sono nascoste: sulla partitura c'è un cerchietto in basso a destra,
   in una fascia sotto le note (non copre mai la partitura), che le mostra/nasconde. Il rendering lo fa da solo.
4. Mai la stessa cosa in due posti; mai un argomento del PDF spezzato in sezioni diverse; mai un esempio del video
   presentato come se fosse quello del PDF (o viceversa) se non è certo.
5. «In breve» e «Concetti chiave»: riassumono il video e il PDF tenendoli distinti («nel video…», «nel PDF…»).

Il video integrale: H.264 720p circa 1 Mbps, `-movflags +faststart`, tastiera di Soundslice compresa; sotto i 95 MB; cifrato con `tools/scuola.py enc`.

## Strumenti
- `SCUOLA_PW=… python3 tools/scuola.py decrypt|build|enc` (password: la dà Paolo; mai scriverla nel repository).
  `src/app.html` è il sorgente; `index.html` si rigenera con `build` dopo `decrypt` (prende i dati delle lezioni da `data.json`, che non si committa).
- Dopo ogni modifica: `python3 tools/pwa.py` (app offline).
- Trascrizione del parlato: dal sandbox i modelli non si scaricano. Cifra l'audio in `lavori/<nome>.audio.enc` e fai push:
  GitHub Actions (`parlato.yml`) scrive `lavori/<nome>.trascr.json.enc` con i tempi parola per parola.
- Se `git pull --rebase` va in conflitto su `index.html`/`sw.js`: prendi la versione del remoto, `decrypt`, riapplica la tua modifica a `data.json` o `src/app.html`, `build`, `pwa.py`.
- Prima di pubblicare: controlla la pagina su iPad in orizzontale e su iPhone (niente sovrapposizioni, pulsanti grandi abbastanza).

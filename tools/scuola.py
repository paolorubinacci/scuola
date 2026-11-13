"""Strumenti del sito Scuola. Password: variabile d'ambiente SCUOLA_PW.
  python3 tools/scuola.py decrypt          -> index.html => data.json (locale, NON committare)
  python3 tools/scuola.py build            -> src/app.html + data.json => index.html (cifrato)
  python3 tools/scuola.py enc IN OUT.enc   -> cifra un file (clip mp4, immagini partiture)
Cifratura: AES-256-GCM, chiave PBKDF2-SHA256 200000 iterazioni; formato salt(16)|iv(12)|ciphertext, base64 per i dati in pagina, binario per i file .enc"""
import sys,os,re,json,base64
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
R=os.path.dirname(os.path.dirname(os.path.abspath(__file__)));PW=os.environ['SCUOLA_PW']
def key(s):return PBKDF2HMAC(algorithm=hashes.SHA256(),length=32,salt=s,iterations=200000).derive(PW.encode())
def enc(b):s=os.urandom(16);iv=os.urandom(12);return s+iv+AESGCM(key(s)).encrypt(iv,b,None)
def dec(b):return AESGCM(key(b[:16])).decrypt(b[16:28],b[28:],None)
cmd=sys.argv[1]
if cmd=='decrypt':
    t=open(R+'/index.html').read();e=re.search(r'id="enc">([^<]*)</script>',t).group(1)
    json.dump(json.loads(dec(base64.b64decode(e))),open(R+'/data.json','w'),ensure_ascii=False,indent=1);print('data.json')
elif cmd=='build':
    t=open(R+'/src/app.html').read();d=json.load(open(R+'/data.json'))
    e=base64.b64encode(enc(json.dumps(d,ensure_ascii=False).encode())).decode()
    open(R+'/index.html','w').write(t.replace('id="enc">__ENC__</script>','id="enc">'+e+'</script>'));print('index.html')
elif cmd=='enc':
    open(sys.argv[3],'wb').write(enc(open(sys.argv[2],'rb').read()));print(sys.argv[3])

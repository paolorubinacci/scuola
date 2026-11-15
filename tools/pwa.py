"""Rigenera sw.js (app offline) con l'elenco di tutti i file del sito e una versione nuova.
Da lanciare dopo ogni modifica:  python3 tools/pwa.py"""
import os,json,hashlib
R=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
skip={'src','tools','.git'};files=['./']
for d,ds,fs in os.walk(R):
    ds[:]=[x for x in ds if x not in skip and not x.startswith('.')]
    for f in fs:
        p=os.path.relpath(os.path.join(d,f),R)
        if p in ('sw.js','CNAME','robots.txt','data.json') or f.startswith('.') or f.endswith(('.txt','.py')):continue
        files.append(p.replace(os.sep,'/'))
files.sort()
h=hashlib.sha256()
for f in files[1:]:h.update(f.encode());h.update(open(os.path.join(R,f),'rb').read())
v=h.hexdigest()[:10]
tpl=open(os.path.join(R,'tools','sw.tpl.js')).read()
open(os.path.join(R,'sw.js'),'w').write(tpl.replace('__VERSION__',v).replace('__FILES__',json.dumps(files)))
print('sw.js',v,len(files),'file')

/* Scuola offline — generato da tools/pwa.py, non modificare a mano */
const V='scuola-__VERSION__',FILES=__FILES__,FONTS='scuola-fonts';
const NET_FIRST=u=>u.endsWith('/')||u.endsWith('index.html')||u.endsWith('ascolti/catalog.json');
self.addEventListener('install',e=>{self.skipWaiting();e.waitUntil(caches.open(V).then(async c=>{
  let ok=0;for(const f of FILES){try{await c.add(new Request(f,{cache:'reload'}));ok++}catch(err){}}
  await c.put('__complete',new Response(JSON.stringify({ok,total:FILES.length})))}))});
self.addEventListener('activate',e=>e.waitUntil((async()=>{for(const k of await caches.keys())if(k!==V&&k!==FONTS)await caches.delete(k);await self.clients.claim()})()));
self.addEventListener('fetch',e=>{const r=e.request;if(r.method!=='GET')return;const u=new URL(r.url);
 if(/fonts\.(googleapis|gstatic)\.com$/.test(u.hostname)){e.respondWith(caches.open(FONTS).then(async c=>{const hit=await c.match(r);const net=fetch(r).then(x=>{if(x.ok||x.type==='opaque')c.put(r,x.clone());return x}).catch(()=>hit);return hit||net}));return}
 if(u.origin!==location.origin)return;
 const key=u.pathname.replace(/^\//,'')||'./';
 if(NET_FIRST(u.pathname)){e.respondWith(fetch(r).then(x=>{if(x.ok){const y=x.clone();caches.open(V).then(c=>c.put(key===''?'./':key,y))}return x}).catch(async()=>(await caches.match(key,{ignoreSearch:true}))||(await caches.match('./'))||Response.error()));return}
 e.respondWith(caches.match(key,{ignoreSearch:true}).then(hit=>hit||fetch(r)))});
self.addEventListener('message',e=>{if(e.data==='status')caches.open(V).then(c=>c.match('__complete')).then(x=>x?x.json():null).then(s=>e.source.postMessage({offline:s}))});

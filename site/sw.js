const C='utro-v1';
self.addEventListener('install',e=>{e.waitUntil(caches.open(C).then(c=>c.addAll(['/'])))});
self.addEventListener('activate',e=>{e.waitUntil(clients.claim())});
self.addEventListener('fetch',e=>{
  if(e.request.method!=='GET')return;
  e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request).then(f=>{
    if(f.ok&&e.request.url.startsWith(self.location.origin)){const cl=f.clone();caches.open(C).then(c=>c.put(e.request,cl));}
    return f;
  }).catch(()=>caches.match('/'))));
});

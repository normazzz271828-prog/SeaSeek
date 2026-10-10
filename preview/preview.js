const body=document.body;
if(matchMedia('(pointer:fine)').matches&&!matchMedia('(prefers-reduced-motion:reduce)').matches){
  let scheduled=false,x=0,y=0;
  addEventListener('pointermove',event=>{
    x=event.clientX;y=event.clientY;
    const panel=event.target.closest('.glass');
    if(panel){const rect=panel.getBoundingClientRect();panel.style.setProperty('--gx',`${100*(x-rect.left)/rect.width}%`);panel.style.setProperty('--gy',`${100*(y-rect.top)/rect.height}%`);}
    if(scheduled)return;
    scheduled=true;
    requestAnimationFrame(()=>{
      body.classList.add('pointer-active');
      document.documentElement.style.setProperty('--mx',`${x}px`);
      document.documentElement.style.setProperty('--my',`${y}px`);
      const sx=innerWidth*.92,sy=innerHeight*.78;
      document.documentElement.style.setProperty('--sx',`${sx}px`);
      document.documentElement.style.setProperty('--sy',`${sy}px`);
      document.documentElement.style.setProperty('--beam-angle',`${Math.atan2(y-sy,x-sx)*180/Math.PI}deg`);
      document.documentElement.style.setProperty('--beam-length',`${Math.hypot(x-sx,y-sy)}px`);
      scheduled=false;
    });
  },{passive:true});
  document.documentElement.addEventListener('pointerleave',()=>body.classList.remove('pointer-active'));
}

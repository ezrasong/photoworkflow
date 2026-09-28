import { createSignal, onMount, onCleanup } from 'solid-js'
import { Button } from '../upstream/button'
export function BrowserPanel(){
  const [url,setURL]=createSignal('https://en.wikipedia.org/wiki/Photography'),[error,setError]=createSignal('')
  const [state,setState]=createSignal<any>({})
  let host!:HTMLDivElement
  const action=async(name:string,args?:any)=>{try{setError('');await window.photo.browser(name,args)}catch(e){setError(String(e))}}
  onMount(()=>{
    // Position can change without size changing (scrolling, pane switches, zoom).
    let frame=0
    const bounds=()=>{
      cancelAnimationFrame(frame)
      frame=requestAnimationFrame(()=>{
        const r=host.getBoundingClientRect()
        let top=Math.max(0,r.top),left=Math.max(0,r.left),right=Math.min(innerWidth,r.right),bottom=Math.min(innerHeight,r.bottom)
        for(let parent=host.parentElement;parent;parent=parent.parentElement){
          const style=getComputedStyle(parent),clip=parent.getBoundingClientRect()
          if(style.overflowX!=='visible'){left=Math.max(left,clip.left);right=Math.min(right,clip.right)}
          if(style.overflowY!=='visible'){top=Math.max(top,clip.top);bottom=Math.min(bottom,clip.bottom)}
        }
        const width=right-left,height=bottom-top
        if(!host.checkVisibility()||width<1||height<1)void window.photo.browser('hide')
        else void action('bounds',{x:left,y:top,width,height})
      })
    }
    const resize=new ResizeObserver(bounds)
    resize.observe(host)
    window.addEventListener('resize',bounds)
    document.addEventListener('scroll',bounds,true)
    const off=window.photo.events(e=>{if(e.type!=='browser')return;if(e.error)setError(e.error);else{setState(e);if(e.url)setURL(e.url)}})
    onCleanup(()=>{cancelAnimationFrame(frame);resize.disconnect();window.removeEventListener('resize',bounds);document.removeEventListener('scroll',bounds,true);off();void window.photo.browser('hide')})
  })
  return <section class="browser-panel"><form class="browser-toolbar" onSubmit={e=>{e.preventDefault();void action('navigate',{url:url()})}}>
    <Button aria-label="Back" disabled={!state().back} onClick={()=>action('back')}>←</Button><Button aria-label="Forward" disabled={!state().forward} onClick={()=>action('forward')}>→</Button><Button aria-label="Reload" onClick={()=>action('reload')}>↻</Button>
    <input aria-label="Browser address" value={url()} onInput={e=>setURL(e.currentTarget.value)}/><Button type="submit">Go</Button></form>
    <p class="muted">Reference browser · public websites · separate from your photos and local assistant</p>
    {error()&&<p role="alert">{error()}</p>}<div class="browser-host" ref={host}><p>Enter a web address and select Go.</p></div></section>
}

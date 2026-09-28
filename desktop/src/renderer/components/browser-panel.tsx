import { createSignal, onMount, onCleanup } from 'solid-js'
import { Button } from '../upstream/button'
export function BrowserPanel(){
  const [url,setURL]=createSignal('https://en.wikipedia.org/wiki/Photography'),[error,setError]=createSignal('')
  const [state,setState]=createSignal<any>({})
  let host!:HTMLDivElement
  const action=async(name:string,args?:any)=>{try{setError('');await window.photo.browser(name,args)}catch(e){setError(String(e))}}
  onMount(()=>{
    const resize=new ResizeObserver(()=>{const r=host.getBoundingClientRect();if(r.width>0&&r.height>0)void action('bounds',{x:r.x,y:r.y,width:r.width,height:r.height})})
    resize.observe(host)
    const off=window.photo.events(e=>{if(e.type!=='browser')return;if(e.error)setError(e.error);else{setState(e);if(e.url)setURL(e.url)}})
    onCleanup(()=>{resize.disconnect();off();void window.photo.browser('hide')})
  })
  return <section class="browser-panel"><form class="browser-toolbar" onSubmit={e=>{e.preventDefault();void action('navigate',{url:url()})}}>
    <Button aria-label="Back" disabled={!state().back} onClick={()=>action('back')}>←</Button><Button aria-label="Forward" disabled={!state().forward} onClick={()=>action('forward')}>→</Button><Button aria-label="Reload" onClick={()=>action('reload')}>↻</Button>
    <input aria-label="Browser address" value={url()} onInput={e=>setURL(e.currentTarget.value)}/><Button type="submit">Go</Button></form>
    <p class="muted">Reference browser · public websites · separate from your photos and local assistant</p>
    {error()&&<p role="alert">{error()}</p>}<div class="browser-host" ref={host}><p>Enter a web address and select Go.</p></div></section>
}

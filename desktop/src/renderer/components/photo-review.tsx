import { createEffect, createSignal, Show } from 'solid-js'
import { Button } from '../upstream/button'

export function PhotoReview(props:{result:any}){
  const [before,setBefore]=createSignal(''),[after,setAfter]=createSignal(''),[error,setError]=createSignal('')
  const [zoom,setZoom]=createSignal('fit'),[split,setSplit]=createSignal(50),[mode,setMode]=createSignal('comparison')
  let viewport!:HTMLDivElement,version=0,drag:{x:number,y:number,left:number,top:number}|undefined
  createEffect(()=>{
    const result=props.result,full=zoom()==='100%',ticket=++version
    setBefore('');setAfter('');setError('')
    if(!result)return
    void Promise.all([window.photo.preview(result.path+'/'+(result.details.baseline_file||'original.tif'),full),window.photo.preview(result.path+'/'+(result.details.composite_file||'composite.tif'),full)]).then(([a,b])=>{if(ticket===version){setBefore(a);setAfter(b)}},e=>{if(ticket===version)setError(String(e))})
  })
  return <section class="photo-review"><div class="review-toolbar">
    <Button onClick={()=>setMode('comparison')}>Before / after</Button><Button onClick={()=>setMode('source')}>Original</Button><Button onClick={()=>setMode('result')}>Result</Button>
    <Button onClick={()=>setZoom(zoom()==='fit'?'100%':'fit')}>{zoom()==='fit'?'100% pixels':'Fit'}</Button>
    <Button onClick={()=>window.photo.reveal(props.result.path)}>Show files</Button>
  </div><p class="muted">Original left · result right. Display uses an 8-bit sRGB preview; saved TIFF precision is unchanged. Drag to pan at 100%.</p>
  <Show when={mode()==='comparison'}><label class="comparison-slider">Before / after<input aria-label="Before and after split" type="range" min="0" max="100" value={split()} onInput={e=>setSplit(+e.currentTarget.value)}/></label></Show>
  <Show when={error()}><p role="alert">{error()}</p></Show>
  <div ref={viewport} class={'compare-viewport '+(zoom()==='fit'?'fit':'actual')} onPointerDown={e=>{if(zoom()==='fit')return;drag={x:e.clientX,y:e.clientY,left:viewport.scrollLeft,top:viewport.scrollTop};viewport.setPointerCapture(e.pointerId)}} onPointerMove={e=>{if(drag){viewport.scrollLeft=drag.left+drag.x-e.clientX;viewport.scrollTop=drag.top+drag.y-e.clientY}}} onPointerUp={()=>drag=undefined} onLostPointerCapture={()=>drag=undefined}>
    <Show when={before()&&after()} fallback={<p>Loading local photo pixels…</p>}><div class="compare-images"><img draggable={false} src={mode()==='source'?before():after()} alt="Local before and after photo comparison"/><Show when={mode()==='comparison'}><img draggable={false} class="before-layer" style={{'clip-path':`inset(0 ${100-split()}% 0 0)`}} src={before()} alt="Original photo"/><span class="compare-divider" style={{left:split()+'%'}}/></Show></div></Show>
  </div></section>
}

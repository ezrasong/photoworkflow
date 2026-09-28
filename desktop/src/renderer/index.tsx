import { render } from 'solid-js/web'
import { createSignal, For, Show, onCleanup, onMount } from 'solid-js'
import { Spinner } from './components/spinner'
import { ResizeHandle } from './components/resize-handle'
import './components/spinner.css'
import './styles.css'

declare global {interface Window {photo:{call:(method:string,args?:any)=>Promise<any>;pick:(kind:string)=>Promise<string[]>;drop:(files:File[])=>Promise<string[]>;preview:(path:string)=>Promise<string>;reveal:(path:string)=>Promise<boolean>;events:(cb:(e:any)=>void)=>()=>void}}}
const api=window.photo
const basename=(value:string)=>value.split(/[\\/]/).pop()||value
const size=(n:number)=>(n/1024**3).toFixed(2)+' GiB'
function App(){
  const [status,setStatus]=createSignal<any>(null),[error,setError]=createSignal(''),[tab,setTab]=createSignal('studio')
  const [sessions,setSessions]=createSignal<any[]>([]),[session,setSession]=createSignal(''),[source,setSource]=createSignal('')
  const [messages,setMessages]=createSignal<any[]>([]),[activity,setActivity]=createSignal<any[]>([]),[draft,setDraft]=createSignal('')
  const [busy,setBusy]=createSignal(false),[jobLabel,setJobLabel]=createSignal('Ready'),[results,setResults]=createSignal<any[]>([])
  const [result,setResult]=createSignal<any>(null),[preview,setPreview]=createSignal(''),[view,setView]=createSignal('comparison')
  const [width,setWidth]=createSignal(360),[zoom,setZoom]=createSignal('fit'),[theme,setTheme]=createSignal('dark')
  const [operation,setOperation]=createSignal('edit'),[scale,setScale]=createSignal(2),[blend,setBlend]=createSignal(.25)
  const [denoiser,setDenoiser]=createSignal('scunet'),[model,setModel]=createSignal('mambairv2'),[exposure,setExposure]=createSignal(0)
  const [recipe,setRecipe]=createSignal(''),[progress,setProgress]=createSignal<any>(null)
  const [projectTitle,setProjectTitle]=createSignal(''),[person,setPerson]=createSignal('')
  const guard=async(fn:()=>Promise<any>)=>{setError('');try{return await fn()}catch(e){setError(String(e).replace('Error: Error invoking remote method \'photo:call\': Error: ',''));setBusy(false)}}
  const refresh=async()=>{const s=await api.call('status');setStatus(s);setSessions(s.sessions);setResults(s.results);return s}
  const event=(e:any)=>{
    if(e.type==='message_update'&&e.assistantMessageEvent?.type==='text_delta'){
      setMessages(previous=>{const list=[...previous],last=list.at(-1);if(last?.role==='assistant'&&last.streaming)list[list.length-1]={...last,text:last.text+e.assistantMessageEvent.delta};else list.push({role:'assistant',text:e.assistantMessageEvent.delta,streaming:true});return list})
    }
    if(e.type==='user')setMessages(p=>[...p.map(m=>({...m,streaming:false})),{role:'user',text:e.text}])
    if(e.type==='agent_start'){setBusy(true);setJobLabel('Thinking locally')}
    if(['tool_execution_start','tool_execution_update','tool_execution_end','job_progress','diagnostic'].includes(e.type)){
      setActivity(p=>[...p.slice(-199),e]);setJobLabel(e.toolName||e.text||'Editing')
    }
    if(e.type==='setup_progress'){setProgress(e);setJobLabel('Installing '+basename(e.file))}
    if(['prompt_result','job_end','setup_complete'].includes(e.type)){
      setBusy(false);setJobLabel(e.status==='error'||e.code?'Needs attention':'Ready for review')
      if(e.error)setError(e.error.message||String(e.error));if(e.code&&e.code!==130)setError('Job failed. Inspect activity before retrying.')
      setMessages(p=>p.map(m=>({...m,streaming:false})));void refresh().catch(e=>setError(String(e)))
    }
    if(e.type==='error'){setError(e.text);setBusy(false)}
    if(e.type==='response'&&e.success===false){setError(e.error||'Assistant command failed');setBusy(false)}
  }
  onMount(()=>{const off=api.events(event);onCleanup(off);void guard(async()=>{await refresh();const settings=await api.call('settings');setTheme(settings.theme);setZoom(settings.reviewZoom)})})
  const openSession=async(id?:string)=>guard(async()=>{setBusy(true);const data=await api.call('session',{id,title:projectTitle()||'Photo session'});setMessages([]);setActivity([]);setSession(data.id);for(const e of data.events)event(e);setBusy(false);setTab('studio');await refresh()})
  const choose=async(kind:string)=>guard(async()=>{
    const paths=await api.pick(kind);if(!paths.length)return
    if(kind==='photo'||kind==='folder'){setSource(paths[0]);setResult(null);setPreview('');if(session())await api.call('select',{kind:'photo',paths});try{setPreview(await api.preview(paths[0]))}catch{} }
    else {if(!session())throw new Error('Create or open a session before adding context');await api.call('select',{kind,paths});setActivity(p=>[...p,{type:'context',text:`Selected ${paths.length} ${kind}`}])}
  })
  const send=()=>guard(async()=>{if(!session())throw new Error('Create a session first');setBusy(true);const text=draft();setDraft('');await api.call('prompt',{text:source()?`${text}\n\nSelected local input: "${source()}"`:text})})
  const showResult=async(item:any,which=view())=>guard(async()=>{setResult(item);setTab('review');setPreview('');setView(which);setPreview(await api.preview(item.path+'/'+(which==='comparison'?'comparison.jpg':which==='source'?'original.tif':'composite.tif')))})
  const run=()=>guard(async()=>{
    if(!source())throw new Error('Choose a photo or folder first')
    let custom:any=recipe().trim()?JSON.parse(recipe()):{exposure:exposure(),denoise:blend(),denoise_model:denoiser()}
    setBusy(true);setJobLabel('Processing locally');await api.call('process',{operation:operation(),source:source(),scale:scale(),blend:blend(),strength:blend(),model:model(),recipe:custom});setBusy(false);await refresh()
  })
  const settings=()=>guard(()=>api.call('settings',{value:{theme:theme(),reviewZoom:zoom()}}))
  return <div class="app" data-theme={theme()} onDragOver={e=>e.preventDefault()} onDrop={e=>{e.preventDefault();void guard(async()=>{if(busy())throw new Error('Wait for the current job before changing input');const paths=await api.drop(Array.from(e.dataTransfer?.files||[]));setSource(paths[0]);if(session())await api.call('select',{kind:'photo',paths});try{setPreview(await api.preview(paths[0]))}catch{setPreview('')}})}}>
    <aside class="sidebar">
      <div class="brand"><span class="brand-mark">◒</span><div>Photo Workflow<small>LOCAL PHOTO STUDIO</small></div></div>
      <button class="primary" disabled={busy()} onClick={()=>openSession()}>＋ New session</button>
      <input aria-label="New project or session title" placeholder="Project / session name" value={projectTitle()} onInput={e=>setProjectTitle(e.currentTarget.value)}/>
      <div class="nav"><button classList={{active:tab()==='studio'}} onClick={()=>setTab('studio')}>◎ Studio</button><button classList={{active:tab()==='review'}} onClick={()=>setTab('review')}>▧ Results <span>{results().length}</span></button><button classList={{active:tab()==='setup'}} onClick={()=>setTab('setup')}>⚙ Setup & settings</button></div>
      <h2>SESSIONS</h2><div class="session-list"><For each={sessions()}>{s=><button disabled={busy()} classList={{active:session()===s.id}} onClick={()=>openSession(s.id)}>{s.title}<small>{new Date(s.updated*1000).toLocaleDateString()}</small></button>}</For></div>
      <div class="local"><span class="dot"/> Photos stay on this computer<small>Oh My Pi · local inference<br/>Setup and reference retrieval use the network only when requested.</small></div>
    </aside>
    <main>
      <header><div><span class="eyebrow">{tab()==='setup'?'YOUR WORKSPACE':tab()==='review'?'REVIEW YOUR WORK':'MAKE SOMETHING WORTH KEEPING'}</span><h1>{tab()==='setup'?'Setup & settings':tab()==='review'?'Before & after':'Photo studio'}</h1></div><div class="state" role="status"><Show when={busy()} fallback={<span class="dot"/>}><Spinner/></Show>{jobLabel().slice(0,75)}</div></header>
      <Show when={error()}><div role="alert" class="error">{error()}<button aria-label="Dismiss error" onClick={()=>setError('')}>×</button></div></Show>
      <Show when={busy()}><div class="job-bar"><span>{jobLabel().slice(0,140)}</span><button onClick={()=>guard(async()=>{const r=await api.call('cancel');setJobLabel(r.message)})}>Stop safely</button></div></Show>
      <Show when={tab()==='studio'}>
        <div class="studio">
          <section class="conversation">
            <div class="selection"><div><span class="eyebrow">SELECTED MEDIA</span><strong>{source()?basename(source()):'Choose a photo to begin'}</strong><small>{source()||'Drop a local photo or folder anywhere in the window.'}</small></div><button disabled={busy()} onClick={()=>choose('photo')}>Choose photo</button><button disabled={busy()} onClick={()=>choose('folder')}>Folder</button></div>
            <div class="messages" aria-live="polite"><Show when={!messages().length}><div class="welcome"><span class="large-mark">◒</span><h2>Your photos. Your direction.</h2><p>Describe what you want to change. Inspect, adjust and review locally with Oh My Pi.</p><div class="suggestions"><For each={['Inspect this photo and suggest natural improvements.','Denoise gently, preserve natural texture and save TIFF and layered PSD.','Upscale 2× with detail strength 0.15. Keep faces unchanged.']}>{text=><button onClick={()=>setDraft(text)}>{text}</button>}</For></div><p class="muted">Assistant editing uses your licensed Lightroom Classic and Photoshop. Manual raster controls can work without Adobe.</p></div></Show><For each={messages()}>{m=><article class={'message '+m.role}><span>{m.role==='user'?'YOU':'OH MY PI'}</span><p>{m.text}</p></article>}</For></div>
            <div class="composer"><textarea aria-label="Photo instructions" placeholder={session()?'Describe your edit…':'Create a session to talk with the local assistant…'} value={draft()} onInput={e=>setDraft(e.currentTarget.value)} onKeyDown={e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();void send()}}}/><div><button disabled={busy()} onClick={()=>choose('references')}>＋ References</button><button disabled={busy()} onClick={()=>choose('notes')}>＋ Vault notes</button><button disabled={busy()||!session()} onClick={()=>guard(()=>api.call('references'))}>Search references</button><span>Ctrl + Enter</span><button class="primary" disabled={busy()||!draft().trim()||!session()} onClick={send}>Send ↑</button></div></div>
          </section>
          <ResizeHandle direction="horizontal" edge="start" size={width()} min={300} max={600} onResize={setWidth} role="separator" aria-label="Detail panel width" tabIndex={0} onKeyDown={e=>{if(e.key==='ArrowLeft')setWidth(Math.min(600,width()+20));if(e.key==='ArrowRight')setWidth(Math.max(300,width()-20))}}/>
          <aside class="details" style={{width:width()+'px'}}><h2>PHOTO CONTROLS</h2><Show when={preview()}><img class="thumbnail" src={preview()} alt="Selected local photo preview"/></Show><p class="muted">Manual actions below run directly through the existing photo backend.</p>
            <label>Operation<select value={operation()} onChange={e=>setOperation(e.currentTarget.value)}><option value="edit">Tone & denoise</option><option value="upscale">Natural upscale</option><option value="single">Face restoration — single</option><option value="batch">Face restoration — folder</option><option value="watch">Face restoration — watch folder</option></select></label>
            <Show when={operation()==='edit'}><label>Exposure (stops)<input type="number" min="-3" max="3" step="0.1" value={exposure()} onInput={e=>setExposure(+e.currentTarget.value)}/></label><label>Denoiser<select value={denoiser()} onChange={e=>setDenoiser(e.currentTarget.value)}><option value="scunet">SCUNet · rendered RGB</option><option value="drunet">DRUNet · Gaussian noise</option></select></label></Show>
            <Show when={operation()!=='edit'}><label>Scale<select value={scale()} onChange={e=>setScale(+e.currentTarget.value)}><Show when={operation()!=='upscale'}><option value="1">1×</option></Show><option value="2">2×</option><option value="4">4×</option></select></label></Show>
            <Show when={operation()==='upscale'}><label>Upscaler<select value={model()} onChange={e=>setModel(e.currentTarget.value)}><option value="mambairv2">MambaIRv2 · RTX 50-series build</option><option value="realesrgan">Real-ESRGAN</option></select></label></Show>
            <label>{operation()==='edit'?'Denoise blend':operation()==='upscale'?'AI detail blend':'Face reconstruction blend'}<input type="number" min="0" max={operation()==='upscale'?.5:1} step="0.05" value={blend()} onInput={e=>setBlend(+e.currentTarget.value)}/></label>
            <Show when={operation()==='edit'}><details><summary>Advanced recipe JSON</summary><p class="muted">Overrides the controls above. The backend validates tone, masks, clone, selective denoise, removal and face fields.</p><textarea aria-label="Advanced recipe JSON" value={recipe()} onInput={e=>setRecipe(e.currentTarget.value)} placeholder='{"exposure":0.2,"denoise":0}'/></details></Show>
            <button class="primary full" disabled={busy()||!source()} onClick={run}>Apply manual operation</button><p class="muted">16-bit output. Originals stay unchanged. Face restoration and removal estimate content; review locally.</p>
            <details><summary>Precision tools & vault</summary><button disabled={busy()} onClick={()=>guard(()=>api.call('panel',{name:'advanced'}))}>Open precision editor & masks</button><button disabled={busy()} onClick={()=>guard(()=>api.call('panel',{name:'batch'}))}>Open advanced native batch</button><p class="muted">Includes paint/erase masks, donor clone, recipe loading, reference search, person mappings, vault and Obsidian controls.</p><input aria-label="Person mapping name" placeholder="Explicit person mapping name" value={person()} onInput={e=>setPerson(e.currentTarget.value)}/><button onClick={()=>guard(()=>api.call('person',{name:person()}))}>Add person to vault</button></details>
            <details open><summary>Tool activity</summary><div class="activity" aria-live="polite"><For each={activity()}>{e=><div><strong>{e.toolName||e.type.replaceAll('_',' ')}</strong><pre>{e.text||JSON.stringify(e.result||e.partialResult||e.args||{},null,2)}</pre></div>}</For></div></details>
          </aside>
        </div>
      </Show>
      <Show when={tab()==='review'}><div class="review"><aside class="result-list"><button onClick={()=>guard(refresh)}>Refresh results</button><For each={results()}>{r=><button classList={{active:result()?.path===r.path}} onClick={()=>showResult(r)}>{r.name}<small>{new Date(r.updated*1000).toLocaleString()}</small></button>}</For><Show when={!results().length}><p>Completed photo jobs appear here.</p></Show></aside><section class="review-main"><Show when={result()} fallback={<div class="welcome"><h2>Review every change.</h2><p>Select a result to compare the original and edited photo.</p></div>}><div class="review-toolbar"><For each={['comparison','source','result']}>{v=><button classList={{active:view()===v}} onClick={()=>showResult(result(),v)}>{v==='comparison'?'Before / after':v}</button>}</For><button onClick={()=>{setZoom(zoom()==='fit'?'100%':'fit');void settings()}}>{zoom()==='fit'?'Fit preview':'Preview pixels'}</button><button onClick={()=>guard(()=>api.reveal(result().path))}>Show files</button><button onClick={()=>guard(()=>api.call('review',{path:result().path}))}>Full resolution review</button><button disabled={busy()} onClick={()=>guard(async()=>{setBusy(true);await api.call('export',{path:result().path});setBusy(false)})}>Export layered PSD</button></div><p class="muted">Comparison: original left, result right. The embedded view is an 8-bit display preview; full precision TIFFs and local 100% review remain in the result package.</p><div class={'canvas '+(zoom()==='fit'?'fit':'actual')}><Show when={preview()}><img src={preview()} alt="Local before and after photo comparison"/></Show></div><details><summary>What changed · saved job details</summary><pre>{JSON.stringify(result()?.details,null,2)}</pre></details></Show></section></div></Show>
      <Show when={tab()==='setup'}><div class="setup"><section><h2>Ready on your computer</h2><p>Install the components you need. Downloads are separate from inference. Interrupted downloads resume; every downloaded file is checked against its pinned SHA-256.</p><Show when={status()}><div class="hardware"><strong>{status().gpu.name||'CUDA unavailable'}</strong><p>{status().gpu.reason||`${size(status().gpu.memory)} GPU memory · compute ${status().gpu.capability?.join('.')}`}</p><p>The primary assistant was verified on RTX 5090 32 GB. Smaller GPUs may run out of memory; there is no automatic CPU or smaller-model fallback. MambaIRv2 requires compute capability 12.0 for this build.</p></div><p>{size(status().free)} free · Data: <code>{status().home}</code></p><For each={status().dependencies}>{d=><article class="dependency"><div><h3>{({runtime:'PyTorch CUDA runtime',assistant:'Local assistant & vision',photo:'Photo editing models',legacy:'Legacy text assistant models',obsidian:'Obsidian · optional vault editor'} as any)[d.group]||d.group}</h3><span>{size(d.bytes)} download · {size(d.missingBytes)} not downloaded</span><small>Allow up to {size(d.bytes*3+1024**3)} free for download and extraction.</small></div><button disabled={busy()} onClick={()=>guard(async()=>{setBusy(true);await api.call('setup',{group:d.group});setBusy(false);await refresh()})}>Install / repair</button></article>}</For><Show when={progress()}><p>{basename(progress().file)} · {size(progress().done)} / {size(progress().total)}</p><progress max={progress().total} value={progress().done}/></Show><button onClick={()=>guard(refresh)}>Refresh hardware & setup</button></Show></section>
        <section><h2>Your Adobe installations</h2><p>Photoshop and Lightroom Classic require your own licensed installations. Add the included plug-in in Lightroom → File → Plug-in Manager → Add. Enable it before assistant editing.</p><For each={['Photoshop','Lightroom']}>{name=><p><strong>{name}: </strong>{status()?.adobe[name]?.join(', ')||'Not found in the standard Adobe installation folder'}</p>}</For><code>{status()?.plugin}</code><button onClick={()=>guard(()=>api.reveal(status().plugin))}>Show Lightroom plug-in</button><p>Adobe dialogs and unsaved documents remain under your control. A failed Adobe step preserves completed TIFF outputs.</p></section>
        <section><h2>Preferences & data</h2><button onClick={()=>guard(()=>api.call('obsidian'))}>Open Photo Vault in Obsidian</button><label>Appearance<select value={theme()} onChange={e=>{setTheme(e.currentTarget.value);void settings()}}><option value="dark">Dark</option><option value="light">Light</option></select></label><button onClick={()=>guard(()=>api.reveal(status().home))}>Show workspace</button><p>Photos, results, notes, models and settings live outside the installation directory. Upgrades and uninstall preserve this workspace. Back it up separately.</p><p>Video editing is a future phase. This release contains photo operations only.</p></section></div></Show>
    </main>
  </div>
}
render(()=><App/>,document.getElementById('root')!)

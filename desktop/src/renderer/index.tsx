import { render } from 'solid-js/web'
import { createSignal, For, Show, onCleanup, onMount } from 'solid-js'
import { Spinner } from './components/spinner'
import { ResizeHandle } from './components/resize-handle'
import './components/spinner.css'
import { Button } from './upstream/button'
import { Tabs } from './upstream/tabs'
import { SidebarShell } from './components/sidebar-shell'
import { BrowserPanel } from './components/browser-panel'
import { PhotoReview } from './components/photo-review'
import './upstream/base.css'
import './upstream/colors.css'
import './upstream/theme.css'
import './upstream/button.css'
import './upstream/icon.css'
import './upstream/icon-button.css'
import './upstream/tabs.css'
import './styles.css'

declare global {interface Window {photo:{call:(method:string,args?:any)=>Promise<any>;pick:(kind:string)=>Promise<string[]>;drop:(files:File[])=>Promise<string[]>;preview:(path:string,full?:boolean)=>Promise<string>;browser:(action:string,args?:any)=>Promise<any>;reveal:(path:string)=>Promise<boolean>;events:(cb:(e:any)=>void)=>()=>void}}}
const api=window.photo
const basename=(value:string)=>value.split(/[\\/]/).pop()||value
const size=(n:number)=>(n/1024**3).toFixed(2)+' GiB'
function App(){
  const [panel,setPanel]=createSignal('controls'),[sidebar,setSidebar]=createSignal(window.innerWidth>1100)
  const [pane,setPane]=createSignal('chat')
  const closeNavigation=()=>{if(window.innerWidth<=1100)setSidebar(false)}
  const openPanel=(value:string)=>{setPanel(value);setPane('details');closeNavigation()}
  const [status,setStatus]=createSignal<any>(null),[error,setError]=createSignal(''),[tab,setTab]=createSignal('studio')
  const [sessions,setSessions]=createSignal<any[]>([]),[session,setSession]=createSignal(''),[source,setSource]=createSignal('')
  const [messages,setMessages]=createSignal<any[]>([]),[activity,setActivity]=createSignal<any[]>([]),[draft,setDraft]=createSignal('')
  const [busy,setBusy]=createSignal(false),[jobLabel,setJobLabel]=createSignal('Ready'),[results,setResults]=createSignal<any[]>([])
  const [result,setResult]=createSignal<any>(null),[preview,setPreview]=createSignal(''),[view,setView]=createSignal('comparison')
  const [width,setWidth]=createSignal(530),[zoom,setZoom]=createSignal('fit'),[theme,setTheme]=createSignal('dark')
  const [focusStrength,setFocusStrength]=createSignal(.35),[focusRadius,setFocusRadius]=createSignal(1)
  const [operation,setOperation]=createSignal('edit'),[scale,setScale]=createSignal(2),[blend,setBlend]=createSignal(.25)
  const [denoiser,setDenoiser]=createSignal('scunet'),[model,setModel]=createSignal('mambairv2'),[exposure,setExposure]=createSignal(0)
  const [recipe,setRecipe]=createSignal(''),[progress,setProgress]=createSignal<any>(null)
  const [projectTitle,setProjectTitle]=createSignal(''),[person,setPerson]=createSignal('')
  const [suggestions,setSuggestions]=createSignal<any>(null),[setupMessage,setSetupMessage]=createSignal('')
  const guard=async(fn:()=>Promise<any>)=>{setError('');try{return await fn()}catch(e){setError(String(e).replace('Error: Error invoking remote method \'photo:call\': Error: ',''));setBusy(false)}}
  const refresh=async()=>{const s=await api.call('status');setStatus(s);setSessions(s.sessions);setResults(s.results);return s}
  const event=(e:any)=>{
    if(e.type==='message_update'&&e.assistantMessageEvent?.type==='text_delta'){
      setMessages(previous=>{const list=[...previous],last=list.at(-1);if(last?.role==='assistant'&&last.streaming)list[list.length-1]={...last,text:last.text+e.assistantMessageEvent.delta};else list.push({role:'assistant',text:e.assistantMessageEvent.delta,streaming:true});return list})
    }
    if(e.type==='user')setMessages(p=>[...p.map(m=>({...m,streaming:false})),{role:'user',text:e.text,corrected:e.corrected}])
    if(e.type==='prompt_suggestions')setSuggestions(e)
    if(e.type==='prompt_correction_start'){setBusy(true);setJobLabel('Prompt Master · correcting locally')}
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
  onMount(()=>{const narrow=window.matchMedia('(max-width:1100px)');const collapse=()=>{if(narrow.matches)setSidebar(false)};narrow.addEventListener('change',collapse);onCleanup(()=>narrow.removeEventListener('change',collapse));const off=api.events(event);onCleanup(off);void guard(async()=>{const state=await refresh();if(state.dependencies.some((d:any)=>d.missingBytes>0))setTab('setup');const settings=await api.call('settings');setTheme(settings.theme);setZoom(settings.reviewZoom)})})
  const openSession=async(id?:string)=>guard(async()=>{setBusy(true);const data=await api.call('session',{id,title:projectTitle()||'Photo session'});setMessages([]);setSuggestions(null);setActivity([]);setSession(data.id);setPreview('');if(id)setSource(data.source||'');else if(source())await api.call('select',{kind:'photo',paths:[source()]});for(const e of data.events)event(e);setBusy(false);setTab('studio');setPane('chat');closeNavigation();await refresh()})
  const choose=async(kind:string)=>guard(async()=>{
    const paths=await api.pick(kind);if(!paths.length)return
    setSuggestions(null)
    if(kind==='photo'||kind==='folder'){setSource(paths[0]);setResult(null);setPreview('');if(session())await api.call('select',{kind:'photo',paths});try{setPreview(await api.preview(paths[0]))}catch{} }
    else {if(!session())throw new Error('Create or open a session before adding context');await api.call('select',{kind,paths});setActivity(p=>[...p,{type:'context',text:`Selected ${paths.length} ${kind}`}])}
  })
  const send=()=>guard(async()=>{if(!session())throw new Error('Create a session first');setBusy(true);const text=draft();await api.call('prompt',{text});if(draft()===text)setDraft('')})
  const suggest=()=>guard(async()=>{setBusy(true);setJobLabel('Inspecting photo for prompt suggestions');await api.call('suggest');setBusy(false);setJobLabel('Suggestions ready');openPanel('prompts')})
  const searchReferences=()=>guard(async()=>{setBusy(true);setJobLabel('Choose references in the search window');const data=await api.call('references');setBusy(false);setSuggestions(null);setJobLabel('Ready');setActivity(p=>[...p,{type:'references',text:data.cancelled?'Reference search closed':`${data.selected_references} references selected · ${data.saved_vault_notes?.length||0} notes saved in Photo Vault`}])})
  const setup=async(group:string)=>guard(async()=>{setBusy(true);setSetupMessage('');setJobLabel('Verifying setup');const data=await api.call('setup',{group});setBusy(false);setSetupMessage(data.restartRecommended?'Setup complete. Restart Photo Studio before model editing.':'Component installed and verified.');await refresh()})
  const showResult=async(item:any)=>{setResult(item);setTab('studio');openPanel('review')}
  const run=()=>guard(async()=>{
    if(!source())throw new Error('Choose a photo or folder first')
    let custom:any=operation()!=='focus'&&recipe().trim()?JSON.parse(recipe()):operation()==='focus'?{focus:{radius:focusRadius(),strength:focusStrength()}}:{exposure:exposure(),denoise:blend(),denoise_model:denoiser()}
    setBusy(true);setJobLabel('Processing locally');await api.call('process',{operation:operation()==='focus'?'edit':operation(),source:source(),scale:scale(),blend:blend(),strength:blend(),model:model(),recipe:custom});setBusy(false);await refresh()
  })
  const settings=()=>guard(()=>api.call('settings',{value:{theme:theme(),reviewZoom:zoom()}}))
  return <div class="app" data-theme={theme()} data-navigation={sidebar()} onDragOver={e=>e.preventDefault()} onDrop={e=>{e.preventDefault();void guard(async()=>{if(busy())throw new Error('Wait for the current job before changing input');const paths=await api.drop(Array.from(e.dataTransfer?.files||[]));setSuggestions(null);setSource(paths[0]);if(session())await api.call('select',{kind:'photo',paths});try{setPreview(await api.preview(paths[0]))}catch{setPreview('')}})}}>
    <SidebarShell opened={sidebar()} onToggle={()=>setSidebar(!sidebar())} onSettings={()=>{setTab('setup');closeNavigation()}} onNew={()=>openSession()}><aside class="sidebar">
      <div class="brand">Photo Studio<small>Workspace</small></div>
      <Button variant="primary" class="primary" disabled={busy()} onClick={()=>openSession()}>＋ New session</Button>
      <input aria-label="New project or session title" placeholder="Project / session name" value={projectTitle()} onInput={e=>setProjectTitle(e.currentTarget.value)}/>
      <div class="nav"><Button variant="ghost" classList={{active:tab()==='studio'}} onClick={()=>{setTab('studio');setPane('chat');closeNavigation()}}>Studio</Button><Button variant="ghost" classList={{active:tab()==='studio'&&panel()==='review'}} onClick={()=>{setTab('studio');openPanel('review')}}>Results <span>{results().length}</span></Button><Button variant="ghost" classList={{active:tab()==='setup'}} onClick={()=>{setTab('setup');closeNavigation()}}>Settings</Button></div>
      <h2>SESSIONS</h2><div class="session-list"><For each={sessions()}>{s=><Button disabled={busy()} classList={{active:session()===s.id}} title={s.title} onClick={()=>openSession(s.id)}><span class="session-title">{s.title}</span><small>{new Date(s.updated*1000).toLocaleDateString()}</small></Button>}</For></div>
      <div class="local">Local processing · Oh My Pi</div>
    </aside></SidebarShell>
    <main>
      <header><Button aria-label="Toggle navigation" aria-expanded={sidebar()} variant="ghost" onClick={()=>setSidebar(!sidebar())}>☰</Button><span class="window-title" title={sessions().find(s=>s.id===session())?.title||'New session'}>Photo Studio <span class="muted"> / {sessions().find(s=>s.id===session())?.title||'New session'}</span></span><div class="state" role="status"><Show when={busy()} fallback={<span class="dot"/>}><Spinner/></Show>{jobLabel().slice(0,65)}</div></header>
      <Show when={error()}><div role="alert" class="error">{error()}<Button aria-label="Dismiss error" onClick={()=>setError('')}>×</Button></div></Show>
      <Show when={busy()}><div class="job-bar"><span>{jobLabel().slice(0,140)}</span><Button onClick={()=>guard(async()=>{const r=await api.call('cancel');setJobLabel(r.message)})}>Stop safely</Button></div></Show>
      <Show when={tab()==='studio'}>
        <nav class="pane-switch" aria-label="Studio panes"><Button aria-pressed={pane()==='chat'} onClick={()=>setPane('chat')}>Conversation</Button><Button aria-pressed={pane()==='details'} onClick={()=>setPane('details')}>Controls & review</Button></nav>
        <div class="studio" data-pane={pane()}>
          <section class="conversation">
            <div class="selection"><div><strong>{source()?basename(source()):'Choose a photo to begin'}</strong><small title={source()}>{source()||'Drop a local photo or folder anywhere in the window.'}</small></div><Button disabled={busy()} onClick={()=>choose('photo')}>Choose photo</Button><Button disabled={busy()} onClick={()=>choose('folder')}>Folder</Button></div>
            <div class="messages" aria-live="polite"><Show when={!messages().length}><div class="welcome"><h2>Start with a photo</h2><p>Choose a photo, then describe the changes you want.</p><div class="suggestions"><For each={['Suggest improvements','Correct mild out-of-focus softness','Reduce noise, keep natural texture']}>{text=><Button onClick={()=>setDraft(text)}>{text}</Button>}</For></div><p class="muted">Assistant editing uses your licensed Lightroom Classic and Photoshop. Manual raster controls can work without Adobe.</p></div></Show><For each={messages()}>{m=><article class={'message '+m.role}><span>{m.role==='user'?'YOU':'OH MY PI'}</span><p>{m.corrected||m.text}</p><Show when={m.corrected}><details><summary>Prompt Master · original & corrected</summary><small>Original</small><p>{m.text}</p><small>Corrected</small><p>{m.corrected}</p></details></Show></article>}</For></div>
            <div class="composer"><textarea aria-label="Photo instructions" placeholder={session()?'Describe your edit…':'Create a session to talk with the local assistant…'} value={draft()} onInput={e=>setDraft(e.currentTarget.value)} onKeyDown={e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();void send()}}}/><div><Button disabled={busy()} onClick={()=>choose('references')}>＋ References</Button><Button disabled={busy()} onClick={()=>choose('notes')}>＋ Vault notes</Button><Button disabled={busy()||!session()} onClick={searchReferences}>Search references</Button><Button disabled={busy()||!session()||!source()} onClick={suggest}>Suggest prompts from photo</Button><span>Prompt Master · local<br/>Ctrl + Enter</span><Button variant="primary" class="primary" disabled={busy()||!draft().trim()||!session()} onClick={send}>Send ↑</Button></div></div>
          </section>
          <ResizeHandle direction="horizontal" edge="start" size={width()} min={300} max={1000} onResize={setWidth} role="separator" aria-label="Detail panel width" tabIndex={0} onKeyDown={e=>{if(e.key==='ArrowLeft')setWidth(Math.min(1000,width()+20));if(e.key==='ArrowRight')setWidth(Math.max(300,width()-20))}}/>
          <aside class="detail-shell" style={{width:width()+'px'}}><Tabs value={panel()} onChange={setPanel}><Tabs.List><Tabs.Trigger value="controls">Photo controls</Tabs.Trigger><Tabs.Trigger value="review">Results</Tabs.Trigger><Tabs.Trigger value="prompts">Prompt Master</Tabs.Trigger><Tabs.Trigger value="browser">Browser</Tabs.Trigger></Tabs.List>
            <Tabs.Content value="controls"><div class="details"><h2>Photo controls</h2><Show when={preview()}><img class="thumbnail" src={preview()} alt="Selected local photo preview"/></Show>
            <label>Operation<select aria-label="Operation" value={operation()} onChange={e=>setOperation(e.currentTarget.value)}><option value="edit">Tone & denoise</option><option value="focus">Correct soft focus</option><option value="upscale">Natural upscale</option><option value="single">Face restoration — single</option><option value="batch">Face restoration — folder</option><option value="watch">Face restoration — watch folder</option></select></label>
            <Show when={operation()==='edit'}><label>Exposure (stops)<input type="number" min="-3" max="3" step="0.1" value={exposure()} onInput={e=>setExposure(+e.currentTarget.value)}/></label><label>Denoiser<select value={denoiser()} onChange={e=>setDenoiser(e.currentTarget.value)}><option value="scunet">SCUNet · rendered RGB</option><option value="drunet">DRUNet · Gaussian noise</option></select></label></Show>
            <Show when={!['edit','focus'].includes(operation())}><label>Scale<select value={scale()} onChange={e=>setScale(+e.currentTarget.value)}><Show when={operation()!=='upscale'}><option value="1">1×</option></Show><option value="2">2×</option><option value="4">4×</option></select></label></Show>
            <Show when={operation()==='upscale'}><label>Upscaler<select value={model()} onChange={e=>setModel(e.currentTarget.value)}><option value="mambairv2">MambaIRv2 · RTX 50-series build</option><option value="realesrgan">Real-ESRGAN</option></select></label></Show>
            <Show when={operation()==='focus'}><label>Blur radius (pixels)<input aria-label="Focus blur radius" type="number" min="0.4" max="3" step="0.1" value={focusRadius()} onInput={e=>setFocusRadius(+e.currentTarget.value)}/></label><label>Correction strength<input aria-label="Focus correction strength" type="number" min="0" max="0.75" step="0.05" value={focusStrength()} onInput={e=>setFocusStrength(+e.currentTarget.value)}/></label><p class="muted">For mild out-of-focus softness. Start low and compare at 100%. Severe blur may not be recoverable; too much correction can add halos.</p></Show>
            <Show when={operation()!=='focus'}><label>{operation()==='edit'?'Denoise blend':operation()==='upscale'?'AI detail blend':'Face reconstruction blend'}<input type="number" min="0" max={operation()==='upscale'?.5:1} step="0.05" value={blend()} onInput={e=>setBlend(+e.currentTarget.value)}/></label></Show>
            <Show when={operation()==='edit'}><details><summary>Advanced recipe JSON</summary><p class="muted">Overrides the controls above. The backend validates tone, masks, clone, selective denoise, removal and face fields.</p><textarea aria-label="Advanced recipe JSON" value={recipe()} onInput={e=>setRecipe(e.currentTarget.value)} placeholder='{"exposure":0.2,"denoise":0}'/></details></Show>
            <Button variant="primary" class="primary full" disabled={busy()||!source()} onClick={run}>Apply manual operation</Button><p class="muted">16-bit output. Originals stay unchanged. Face restoration and removal estimate content; review locally.</p>
            <details><summary>Precision tools & vault</summary><Button disabled={busy()} onClick={()=>guard(()=>api.call('panel',{name:'advanced'}))}>Open precision editor & masks</Button><Button disabled={busy()} onClick={()=>guard(()=>api.call('panel',{name:'batch'}))}>Open advanced native batch</Button><p class="muted">Includes paint/erase masks, donor clone, recipe loading, reference search, person mappings, vault and Obsidian controls.</p><input aria-label="Person mapping name" placeholder="Explicit person mapping name" value={person()} onInput={e=>setPerson(e.currentTarget.value)}/><Button onClick={()=>guard(()=>api.call('person',{name:person()}))}>Add person to vault</Button></details>
            <details><summary>Activity</summary><div class="activity" aria-live="polite"><For each={activity()}>{e=><div><strong>{e.toolName||e.type.replaceAll('_',' ')}</strong><pre>{e.text||JSON.stringify(e.result||e.partialResult||e.args||{},null,2)}</pre></div>}</For></div></details></div></Tabs.Content>
            <Tabs.Content value="review"><div class="review"><div class="result-list"><Button onClick={()=>guard(refresh)}>Refresh results</Button><For each={results()}>{r=><Button variant="ghost" title={r.name} classList={{active:result()?.path===r.path}} onClick={()=>showResult(r)}>{r.name}</Button>}</For></div><Show when={result()} fallback={<div class="welcome"><h2>Review every change</h2><p>Select a completed result to compare original and edited pixels.</p></div>}><PhotoReview result={result()}/><div class="review-footer"><Button disabled={busy()} onClick={()=>guard(async()=>{setBusy(true);await api.call('export',{path:result().path});setBusy(false)})}>Export layered PSD</Button><details><summary>Saved job details</summary><pre>{JSON.stringify(result()?.details,null,2)}</pre></details></div></Show></div></Tabs.Content>
            <Tabs.Content value="prompts"><div class="details"><h2>Prompt Master</h2><p class="muted">Every prompt is corrected locally before Oh My Pi receives it. Original wording remains authoritative for permissions and scope.</p><Button disabled={busy()||!session()||!source()} onClick={suggest}>Suggest prompts from photo</Button><Show when={suggestions()&&suggestions().source===source()}><section class="prompt-suggestions"><h3>Based on this photo</h3><p>{suggestions().summary}</p><p class="muted">Review each draft before sending. Suggestions do not edit your photo.</p><For each={suggestions().prompts}>{text=><article><p>{text}</p><Button disabled={busy()} onClick={()=>{setDraft(text);setPane('chat')}}>Use as draft</Button></article>}</For></section></Show><p class="muted">Search references to compare with this photo and save sources in Photo Vault. References guide a repair plan; current models do not reconstruct from reference pixels. Video suggestions are planned.</p><For each={messages().filter(m=>m.role==='user')}>{m=><article class="prompt-pair"><h3>Original</h3><p>{m.text}</p><h3>Corrected</h3><p>{m.corrected||'Sent before Prompt Master was enabled.'}</p></article>}</For></div></Tabs.Content>
            <Tabs.Content value="browser"><BrowserPanel/></Tabs.Content>
          </Tabs></aside>
        </div>
      </Show>
      <Show when={tab()==='setup'}><div class="setup"><section><h2>Ready on your computer</h2><p>Complete setup installs the CUDA runtime, all photo and assistant models, Oh My Pi, and Obsidian with Photo Vault. Downloads are separate from inference. Interrupted downloads resume; every downloaded file is checked against its pinned SHA-256.</p><Show when={status()}><Button variant="primary" disabled={busy()} onClick={()=>setup('all')}>Install / repair complete setup</Button><p>{size(status().dependencies.reduce((sum:number,d:any)=>sum+d.bytes,0))} total download · allow {size(status().dependencies.reduce((sum:number,d:any)=>sum+d.bytes,0)*3+1024**3)} free for complete setup.</p><Show when={setupMessage()}><p role="status">{setupMessage()}</p></Show><div class="hardware"><strong>{status().gpu.name||'CUDA unavailable'}</strong><p>{status().gpu.reason||`${size(status().gpu.memory)} GPU memory · compute ${status().gpu.capability?.join('.')}`}</p><p>The primary assistant was verified on RTX 5090 32 GB. Smaller GPUs may run out of memory; there is no automatic CPU or smaller-model fallback. MambaIRv2 requires compute capability 12.0 for this build.</p></div><p>{size(status().free)} free · Data: <code>{status().home}</code></p><For each={status().dependencies}>{d=><article class="dependency"><div><h3>{({runtime:'PyTorch CUDA runtime',assistant:'Local assistant & vision',photo:'Photo editing models',legacy:'Legacy text assistant models',obsidian:'Obsidian & Photo Vault'} as any)[d.group]||d.group}</h3><span>{size(d.bytes)} download · {size(d.missingBytes)} not downloaded</span><small>Allow up to {size(d.bytes*3+1024**3)} free for download and extraction.</small></div><Button disabled={busy()} onClick={()=>setup(d.group)}>Install / repair</Button></article>}</For><Show when={progress()}><p>{basename(progress().file)} · {size(progress().done)} / {size(progress().total)}</p><progress max={progress().total} value={progress().done}/></Show><Button onClick={()=>guard(refresh)}>Refresh hardware & setup</Button></Show></section>
        <section><h2>Your Adobe installations</h2><p>Photoshop and Lightroom Classic require your own licensed installations. Add the included plug-in in Lightroom → File → Plug-in Manager → Add. Enable it before assistant editing.</p><For each={['Photoshop','Lightroom']}>{name=><p><strong>{name}: </strong>{status()?.adobe[name]?.join(', ')||'Not found in the standard Adobe installation folder'}</p>}</For><code>{status()?.plugin}</code><Button onClick={()=>guard(()=>api.reveal(status().plugin))}>Show Lightroom plug-in</Button><p>Adobe dialogs and unsaved documents remain under your control. A failed Adobe step preserves completed TIFF outputs.</p></section>
        <section><h2>Preferences & data</h2><Button onClick={()=>guard(()=>api.call('obsidian'))}>Open Photo Vault in Obsidian</Button><label>Appearance<select value={theme()} onChange={e=>{setTheme(e.currentTarget.value);void settings()}}><option value="dark">Dark</option><option value="light">Light</option></select></label><Button onClick={()=>guard(()=>api.reveal(status().home))}>Show workspace</Button><p>Photos, results, notes, models and settings live outside the installation directory. Upgrades and uninstall preserve this workspace. Back it up separately.</p><p>Video editing is a future phase. This release contains photo operations only.</p></section></div></Show>
    </main>
  </div>
}
render(()=><App/>,document.getElementById('root')!)

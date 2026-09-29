import { createSignal, onCleanup, onMount, Show } from 'solid-js'
import { Button } from '../upstream/button'

export function Updates(props:{busy:boolean}) {
  const [state,setState]=createSignal<any>({phase:'disconnected',connected:false,message:'Loading update status…'})
  const [error,setError]=createSignal(''),[pending,setPending]=createSignal(false)
  const working=()=>pending()||['checking','downloading','installing'].includes(state().phase)
  const action=async(name:string)=>{
    setError('');setPending(true)
    try{setState(await window.photo.updates(name))}catch{setError('Update action failed. Check your internet connection, finish active work, and retry.')}
    finally{setPending(false)}
  }
  onMount(()=>{
    const off=window.photo.events(e=>{if(e.type==='updates')setState(e)})
    onCleanup(off)
    void action('status')
  })
  return <section>
    <h2>App updates</h2>
    <p>Photo Studio {state().version||''}. Updates are checked on launch and every six hours, then downloaded automatically. Restart to install when your work is finished.</p>
    <p role="status">{state().message}<Show when={state().availableVersion}> Version {state().availableVersion}.</Show></p>
    <Show when={state().phase==='downloading'}><progress aria-label="Update download progress" max={100} value={state().percent||0}/></Show>
    <Show when={error()}><p role="alert">{error()}</p></Show>
    <Show when={state().connected}>
      <div class="dependency-actions">
        <Button disabled={working()||state().phase==='ready'} onClick={()=>action('check')}>Check for updates</Button>
        <Show when={state().phase==='ready'}><Button variant="primary" disabled={working()||props.busy} onClick={()=>action('install')}>Restart and install update</Button></Show>
      </div>
    </Show>
  </section>
}

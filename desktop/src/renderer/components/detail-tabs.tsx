import { createSignal, For } from 'solid-js'
import { Button } from '../upstream/button'
export const TAB_DRAG_TYPE='application/x-photo-studio-tab'
export const panels={controls:'Photo controls',review:'Results',prompts:'Prompt Master',browser:'Browser'}
export type DetailPanel=keyof typeof panels
export type DetailPreferences={order:DetailPanel[];hidden:DetailPanel[];active:DetailPanel|null}
export const defaultDetails:DetailPreferences={order:['controls','review','prompts','browser'],hidden:[],active:'controls'}

export function DetailTabs(props:{value:DetailPreferences;onChange:(value:DetailPreferences)=>void;onSelect:(id:DetailPanel)=>void;onMenuOpenChange:(opened:boolean)=>void}){
  const [dragging,setDragging]=createSignal<DetailPanel|null>(null),[target,setTarget]=createSignal<DetailPanel|null>(null)
  const [announcement,setAnnouncement]=createSignal('')
  let picker!:HTMLDivElement,addButton!:HTMLButtonElement
  const [menuOpen,setMenuOpen]=createSignal(false)
  const visible=()=>props.value.order.filter(id=>!props.value.hidden.includes(id))
  const focus=(id:DetailPanel|null)=>queueMicrotask(()=>document.getElementById(id?'detail-tab-'+id:'add-detail-tab')?.focus())
  const move=(id:DetailPanel,to:DetailPanel)=>{
    if(id===to)return
    const order=[...props.value.order];order.splice(order.indexOf(id),1);order.splice(props.value.order.indexOf(to),0,id)
    props.onChange({...props.value,order});setAnnouncement(`${panels[id]} moved`)
  }
  const step=(id:DetailPanel,delta:number)=>{const to=visible()[visible().indexOf(id)+delta];if(to){move(id,to);focus(id)}}
  const close=(id:DetailPanel)=>{
    const tabs=visible(),index=tabs.indexOf(id),remaining=tabs.filter(tab=>tab!==id)
    const active=props.value.active===id?(remaining[Math.min(index,remaining.length-1)]??null):props.value.active
    props.onChange({...props.value,hidden:[...props.value.hidden,id],active});focus(active)
    setAnnouncement(`${panels[id]} hidden. Restore it with Add tab.`)
  }
  return <nav class="detail-tabs" aria-label="Workspace panels">
    <div class="detail-tablist" role="tablist" aria-label="Detail tabs" aria-orientation="horizontal"><For each={visible()}>{id=><div class="detail-tab" classList={{'tab-drop-target':target()===id}} role="presentation"
      onDragOver={e=>{if(!dragging()||!e.dataTransfer?.types.includes(TAB_DRAG_TYPE))return;e.preventDefault();e.stopPropagation();e.dataTransfer.dropEffect='move';setTarget(id)}}
      onDrop={e=>{if(!e.dataTransfer?.types.includes(TAB_DRAG_TYPE))return;e.preventDefault();e.stopPropagation();if(dragging())move(dragging()!,id);setDragging(null);setTarget(null)}}>
      <Button id={'detail-tab-'+id} role="tab" aria-selected={props.value.active===id} aria-controls={'detail-panel-'+id} aria-describedby="detail-tab-help" tabIndex={props.value.active===id?0:-1} variant="ghost" class="destination-tab" draggable title={panels[id]}
        onDragStart={(e:DragEvent)=>{setDragging(id);e.dataTransfer!.setData(TAB_DRAG_TYPE,id);e.dataTransfer!.effectAllowed='move'}} onDragEnd={()=>{setDragging(null);setTarget(null)}}
        onClick={()=>props.onSelect(id)} onKeyDown={(e:KeyboardEvent)=>{
          if(e.altKey&&['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();step(id,e.key==='ArrowLeft'?-1:1);return}
          if(e.key==='Delete'){e.preventDefault();close(id);return}
          const tabs=visible(),index=tabs.indexOf(id)
          const next=e.key==='Home'?tabs[0]:e.key==='End'?tabs.at(-1):e.key==='ArrowRight'?tabs[(index+1)%tabs.length]:e.key==='ArrowLeft'?tabs[(index+tabs.length-1)%tabs.length]:null
          if(next){e.preventDefault();props.onSelect(next);focus(next)}
        }}><span class="tab-icon" aria-hidden="true">{({controls:'▣',review:'▤',prompts:'✎',browser:'◎'})[id]}</span><span class="tab-title">{panels[id]}</span></Button>
      <Button variant="ghost" class="tab-close" aria-label={'Close '+panels[id]+' tab'} onClick={()=>close(id)}>×</Button>
    </div>}</For></div>
    <Button ref={addButton} id="add-detail-tab" class="tab-add" variant="ghost" aria-label="Add tab" title="Add tab" aria-haspopup="menu" aria-expanded={menuOpen()} aria-controls="detail-tab-picker" onClick={()=>picker.togglePopover()}>+</Button>
    <div ref={picker} id="detail-tab-picker" popover="auto" class="tab-picker" role="menu" aria-label="Open a tab"
      onBeforeToggle={(event:ToggleEvent)=>{
        const opened=event.newState==='open'
        setMenuOpen(opened);props.onMenuOpenChange(opened)
        if(opened){
          const rect=addButton.getBoundingClientRect()
          picker.style.left=Math.max(8,Math.min(rect.left,window.innerWidth-228))+'px'
          picker.style.top=(rect.bottom+6)+'px'
          picker.style.maxHeight=Math.max(80,window.innerHeight-rect.bottom-14)+'px'
        }
      }}
      onToggle={(event:ToggleEvent)=>{if(event.newState==='open')picker.querySelector<HTMLElement>('[role="menuitem"]')?.focus()}}
      onKeyDown={event=>{
        const items=Array.from(picker.querySelectorAll<HTMLElement>('[role="menuitem"]')),index=items.indexOf(document.activeElement as HTMLElement)
        const next=event.key==='Home'?items[0]:event.key==='End'?items.at(-1):event.key==='ArrowDown'?items[(index+1)%items.length]:event.key==='ArrowUp'?items[(index+items.length-1)%items.length]:null
        if(next){event.preventDefault();next.focus()}
      }}>
      <div class="tab-picker-label">Open a tab</div>
      <For each={Object.keys(panels) as DetailPanel[]}>{id=><Button variant="ghost" role="menuitem" class="tab-picker-item" onClick={()=>{props.onSelect(id);picker.hidePopover();focus(id)}}>
        <span>{panels[id]}</span><span class="tab-picker-status">{props.value.hidden.includes(id)?'Open':'Switch to'}</span>
      </Button>}</For>
    </div>

    <span id="detail-tab-help" class="sr-only">Left and right arrows select tabs. Alt plus left or right reorders. Delete closes a tab without deleting its contents.</span><span class="sr-only" aria-live="polite">{announcement()}</span>
  </nav>
}

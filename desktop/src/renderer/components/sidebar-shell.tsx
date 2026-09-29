// Adapted from OpenCode packages/app/src/pages/layout/sidebar-shell.tsx (MIT).
// Retains the rail + collapsible panel ownership; photo workspace replaces Git projects.
import { createEffect, type JSX } from 'solid-js'
import { IconButton } from '../upstream/icon-button'
export function SidebarShell(props:{opened:boolean;busy:boolean;onToggle:()=>void;onSettings:()=>void;onNew:()=>void;children:JSX.Element}){
  let panel!:HTMLDivElement
  createEffect(()=>{if(props.opened)panel?.removeAttribute('inert');else panel?.setAttribute('inert','')})
  return <div class="sidebar-shell"><div data-component="sidebar-rail"><div class="rail-projects"><IconButton icon="photo" size="large" aria-label="Photo workspace" onClick={props.onToggle}/><IconButton icon="plus" size="large" variant="ghost" disabled={props.busy} aria-label="New photo session" onClick={props.onNew}/></div><IconButton icon="settings-gear" size="large" variant="ghost" aria-label="Setup and settings" onClick={props.onSettings}/></div><div ref={panel} class="sidebar-panel" aria-hidden={!props.opened} style={{display:props.opened?'flex':'none'}}>{props.children}</div></div>
}

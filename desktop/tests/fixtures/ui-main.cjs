// Real renderer, preload, Electron IPC/path validation and native image decoder.
// Only the expensive Python/assistant process, browser and updater are fixtures.
const {app,BrowserWindow,dialog}=require('electron')
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm')
const {EventEmitter}=require('node:events'),{PassThrough}=require('node:stream')
const ts=require('typescript')
const desktop=path.resolve(__dirname,'../..'),home=process.env.PHOTOWORKFLOW_HOME
// Keep both the app profile and Chromium session files inside this test's home.
const profile=path.join(home,'profile')
fs.mkdirSync(profile,{recursive:true})
app.setPath('appData',profile)
app.setPath('userData',profile)
app.setPath('sessionData',profile)
const preferences=path.join(home,'settings.json')
let window,source='',references=[],session=''
global.fixture={calls:[],pick:[],failSelect:false,delaySelect:0,browser:[]}
dialog.showOpenDialog=async()=>({canceled:!global.fixture.pick.length,filePaths:global.fixture.pick})
dialog.showMessageBox=async()=>({response:1})
const backend=new EventEmitter()
backend.exitCode=null;backend.stdin=new PassThrough();backend.stdout=new PassThrough();backend.stderr=new PassThrough()
global.fixture.event=event=>backend.stdout.write(JSON.stringify({event})+'\n')
backend.stdin.on('finish',()=>{backend.exitCode=0;backend.emit('exit',0)})
backend.stdin.on('data',async bytes=>{
 for(const line of bytes.toString().trim().split('\n')){
  const {id,method,args}=JSON.parse(line);global.fixture.calls.push({method,args})
  try{
   let result={}
   if(method==='status')result={home,gpu:{},adobe:{},dependencies:[],sessions:session?[{id:session,title:'Fixture session',updated:1}]:[],results:[{name:'Fixture result',path:home,details:{baseline_file:'first.png',composite_file:'second.png'}}]}
   if(method==='settings'){
    result=fs.existsSync(preferences)?JSON.parse(fs.readFileSync(preferences)):{theme:'dark',reviewZoom:'fit'}
    if(args.value){Object.assign(result,args.value);fs.writeFileSync(preferences,JSON.stringify(result))}
   }
   if(method==='session'){session=args.id||'1'.repeat(32);result={id:session,source,references,events:[]}}
   if(method==='select'){
    if(global.fixture.delaySelect)await new Promise(r=>setTimeout(r,global.fixture.delaySelect))
    if(global.fixture.failSelect)throw Error('Fixture selection failed')
    if(args.kind==='photo')source=args.paths[0]
    if(args.kind==='references')references=args.paths
    result={selected:args.paths}
   }
   if(method==='references'){references=[path.join(home,'reference.png')];result={references,selected_references:1}}
   if(method==='preview')throw Error('Fixture cannot decode this image')
   backend.stdout.write(JSON.stringify({id,result})+'\n')
  }catch(error){backend.stdout.write(JSON.stringify({id,error:error.message})+'\n')}
 }
})
const windows={registerRendererProtocol(){},trusted:()=>true,createWindow(){
 window=new BrowserWindow({width:1440,height:960,show:true,webPreferences:{preload:path.join(desktop,'out/preload/index.js'),contextIsolation:true,nodeIntegration:false,sandbox:true}})
 window.loadFile(path.join(desktop,'out/renderer/index.html'));return window
}}
const sourceCode=ts.transpileModule(fs.readFileSync(path.join(desktop,'src/main/index.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
vm.compileFunction(sourceCode,['require','exports','__dirname'])(name=>{
 if(name==='./windows')return windows
 if(name==='./browser')return {referenceBrowser:()=>async(action,args)=>{global.fixture.browser.push({action,args});return true}}
 if(name==='./updates')return {createUpdates:()=>({initialize:async()=>{},command:async()=>({phase:'idle',version:'0.1.7'}),dispose(){}})}
 if(name==='node:child_process')return {spawn:()=>backend}
 return require(name)
},{},path.join(desktop,'out/main'))

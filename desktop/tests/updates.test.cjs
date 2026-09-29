const test=require('node:test'),assert=require('node:assert/strict')
const fs=require('node:fs'),fsp=require('node:fs/promises'),os=require('node:os'),path=require('node:path'),vm=require('node:vm')
const {EventEmitter}=require('node:events'),ts=require('typescript')
const source=ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/main/updates.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
async function fixture(t){
 const home=await fsp.mkdtemp(path.join(os.tmpdir(),'photo-updates-')),events=[],order=[]
 let updater,busy=false,packaged=true,tick,interval
 class FakeUpdater extends EventEmitter {
  constructor(){super();updater=this;this.checks=0;this.downloads=0}
  setFeedURL(feed){this.feed=feed}
  async checkForUpdates(){this.checks++;return this.checkResult??{isUpdateAvailable:false}}
  async downloadUpdate(){this.downloads++;if(this.downloadError)throw this.downloadError;this.emit('download-progress',{percent:42});this.emit('update-downloaded',{version:'0.1.8'});return ['verified.exe']}
  quitAndInstall(...args){this.installArgs=args;order.push('install')}
 }
 const electron={app:{getVersion:()=> '0.1.10',getPath:()=>home,get isPackaged(){return packaged}},safeStorage:{decryptString:()=>{throw Error('Legacy credentials must not be read')}}}
 const module={exports:{}}
 const sandbox={exports:module.exports,module,Buffer,setInterval:(fn,ms)=>{tick=fn;interval=ms;return {unref(){}}},clearInterval(){},require:name=>name==='electron'?electron:name==='electron-updater'?{NsisUpdater:FakeUpdater}:require(name)}
 vm.runInNewContext(source,sandbox)
 const api=module.exports.createUpdates(s=>events.push(s),()=>busy,async()=>{order.push('drain')})
 t.after(async()=>{api.dispose();await fsp.rm(home,{recursive:true,force:true})})
 return {home,api,updater,events,order,tick,interval,setBusy:v=>busy=v,setPackaged:v=>packaged=v}
}
const token='github_pat_fixture_read_only_123456'
async function settle(){await new Promise(r=>setImmediate(r))}

test('public updates check on launch without a token and ignore legacy credentials',async t=>{
 const f=await fixture(t)
 await fsp.writeFile(path.join(f.home,'update-access.bin'),'corrupt legacy credential')
 await f.api.initialize();await settle()
 assert.equal(f.updater.checks,1)
 assert.equal(f.updater.feed.owner,'ezrasong');assert.equal(f.updater.feed.repo,'photoworkflow');assert.equal(f.updater.feed.private,false)
 assert.equal(f.updater.feed.token,undefined)
 assert.equal(f.updater.autoInstallOnAppQuit,false);assert.equal(f.updater.allowDowngrade,false);assert.equal(f.updater.logger,null)
 assert.ok(!JSON.stringify(f.events).includes(token));assert.ok(!JSON.stringify(await f.api.command('status')).includes(token))
 assert.equal((await f.api.command('status')).connected,true)
 await assert.rejects(f.api.command('connect',token),/Unsupported/)
 await assert.rejects(f.api.command('disconnect'),/Unsupported/)
})

test('verified update waits for an idle app and drained backend before interactive install',async t=>{
 const f=await fixture(t);f.updater.checkResult={isUpdateAvailable:true,updateInfo:{version:'0.1.8'}}
 await f.api.initialize();await settle()
 assert.equal(f.updater.downloads,1);assert.equal((await f.api.command('status')).phase,'ready')
 await f.api.command('check');assert.equal(f.updater.downloads,1)
 f.setBusy(true);await assert.rejects(f.api.command('install'),/current job/);assert.deepEqual(f.order,[])
 f.setBusy(false);await f.api.command('install');assert.deepEqual(f.order,['drain','install']);assert.deepEqual(f.updater.installArgs,[false,true])
 await assert.rejects(f.api.command('install'),/Download/)
})

test('failed downloads cannot install or leak upstream headers',async t=>{
 const f=await fixture(t);f.updater.checkResult={isUpdateAvailable:true,updateInfo:{version:'0.1.8'}}
 f.updater.downloadError=Error('Authorization: token '+token)
 await f.api.initialize();await settle()
 assert.equal((await f.api.command('status')).phase,'error');assert.ok(!JSON.stringify(f.events).includes(token))
 await assert.rejects(f.api.command('install'),/Download/);assert.deepEqual(f.order,[])
 f.updater.downloadError=null;await f.api.command('check');assert.equal((await f.api.command('status')).phase,'ready')
})

test('periodic checks wait for idle and development builds never check',async t=>{
 const f=await fixture(t)
 assert.equal(f.interval,6*60*60*1000)
 f.setBusy(true);f.tick();await settle();assert.equal(f.updater.checks,0)
 f.setBusy(false);f.tick();await settle();assert.equal(f.updater.checks,1)
 f.setPackaged(false);await f.api.initialize();f.tick();await settle();assert.equal(f.updater.checks,1)
 await assert.rejects(f.api.command('check'),/installed app/)
 await assert.rejects(f.api.command('shell'),/Unsupported/)
})

test('only one network operation runs and an incomplete download cannot install',async t=>{
 const f=await fixture(t);let release
 f.updater.checkForUpdates=()=>{f.updater.checks++;return new Promise(r=>release=r)}
 await f.api.initialize();await f.api.command('check');assert.equal(f.updater.checks,1)
 await assert.rejects(f.api.command('install'),/Download/)
 release({isUpdateAvailable:false});await settle();assert.equal((await f.api.command('status')).phase,'idle')
})

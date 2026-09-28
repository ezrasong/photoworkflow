// Execute the production NSIS gate against small, deterministic child executables.
// No registry writes, shortcuts, real app installation or model downloads.
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict')
const {spawnSync}=require('node:child_process')
const {getMakeNsisPath}=require('app-builder-lib/out/toolsets/windows')
const root=path.resolve(__dirname,'../..'),out=path.join(root,'.cache/installer-acceptance',String(Date.now()))
;(async()=>{
 const compiler=await getMakeNsisPath()
 const compile=async(name,source)=>{
  const file=path.join(out,name+'.nsi');await fs.writeFile(file,source)
  const result=spawnSync(compiler.path,['/V2',file],{env:{...process.env,...compiler.env},encoding:'utf8',windowsHide:true})
  assert.equal(result.status,0,result.stdout+result.stderr)
 }
 const checks=[]
 for(const expected of [0,1,2,'missing']){
  const dir=path.join(out,'case '+expected),python=path.join(dir,'resources/backend/python'),receipt=path.join(dir,'command.txt'),complete=path.join(dir,'complete.txt')
  await fs.mkdir(python,{recursive:true})
  if(expected!=='missing')await compile('child-'+expected,`
!include "FileFunc.nsh"
OutFile "${path.join(python,'pythonw.exe')}"
RequestExecutionLevel user
SilentInstall silent
Section
 \${GetParameters} $0
 FileOpen $1 "${receipt}" w
 FileWrite $1 $0
 FileClose $1
 SetErrorLevel ${expected}
 Quit
SectionEnd
`)
  const installer=path.join(out,'gate-'+expected+'.exe')
  await compile('gate-'+expected,`
!include "LogicLib.nsh"
!include "${path.join(root,'desktop/resources/installer.nsh')}"
OutFile "${installer}"
RequestExecutionLevel user
SilentInstall silent
Section
 StrCpy $INSTDIR "${dir}"
 !insertmacro customInstall
 FileOpen $2 "${complete}" w
 FileWrite $2 "complete"
 FileClose $2
SectionEnd
`)
  const result=spawnSync(installer,['/S'],{windowsHide:true,timeout:30000})
  assert.equal(result.error,undefined)
  assert.equal(result.status,expected==='missing'?1:expected,'installer exit for '+expected)
  const finished=await fs.stat(complete).then(()=>true,()=>false)
  assert.equal(finished,expected===0,'Finish must require successful setup')
  if(expected!=='missing'){
   const command=await fs.readFile(receipt,'utf8')
   assert.ok(command.startsWith('-I "'+path.join(dir,'resources/backend/scripts/install_desktop.py')+'"'),command)
   assert.ok(command.endsWith('--silent'),command)
  }
  checks.push({childExit:expected,installerExit:result.status,finished})
 }
 await fs.writeFile(path.join(out,'report.json'),JSON.stringify({status:'passed',checks},null,2))
 console.log('Installer completion, failure, cancellation and missing-runtime gates passed:',out)
})().catch(error=>{console.error(error);process.exitCode=1})

// Assert that the release feed describes the exact installer that passed CI.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict')
const yaml=require('js-yaml')
const root=path.resolve(__dirname,'..'),dist=path.join(root,'dist')
const version=JSON.parse(fs.readFileSync(path.join(root,'package.json'))).version
const metadata=yaml.load(fs.readFileSync(path.join(dist,'latest.yml'),'utf8'))
assert.equal(metadata.version,version)
assert.equal(metadata.files.length,1)
const entry=metadata.files[0],filename=`PhotoStudio-${version}-x64-Setup.exe`
assert.equal(entry.url,filename)
const installer=fs.readFileSync(path.join(dist,filename))
assert.equal(entry.size,installer.length)
assert.equal(entry.sha512,crypto.createHash('sha512').update(installer).digest('base64'))
assert.ok(fs.statSync(path.join(dist,filename+'.blockmap')).size>0)
const config=yaml.load(fs.readFileSync(path.join(dist,'win-unpacked/resources/app-update.yml'),'utf8'))
assert.equal(config.provider,'github');assert.equal(config.owner,'ezrasong');assert.equal(config.repo,'photoworkflow');assert.equal(config.private,false)
assert.equal(config.token,undefined)
console.log('Public update feed matches installer version, size and SHA-512; no embedded credential.')

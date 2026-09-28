// Test-only native OMP HEAD request, with no local photo/note content.
import {writeFileSync} from 'node:fs';
export default function(pi) {
  pi.on('session_start',async()=>{
    let result;
    try {
      const response=await fetch('https://www.microsoft.com/',{method:'HEAD',signal:AbortSignal.timeout(6000)});
      result={connected:true,status:response.status,api:'OMP native fetch',method:'HEAD'};
    } catch(error) {result={connected:false,error:String(error),api:'OMP native fetch',method:'HEAD'};}
    writeFileSync(process.env.PHOTO_PROBE_OUTPUT,JSON.stringify(result));
    process.exit(0);
  });
}

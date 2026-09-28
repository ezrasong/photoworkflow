"""Private runtime entry point. Invoked with bundled Python -I, never pip/npx.

serve exposes the upstream MCP to an explicitly configured client. Photo Studio
uses probe/inspect only; neither accepts a tool name or model-provided arguments.
"""
import asyncio
import csv
from datetime import timedelta
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys

CODE = Path(__file__).resolve().parents[1]
PAYLOAD = CODE/'creative-mcp'
HOME = Path(os.environ['PHOTOWORKFLOW_HOME']).resolve()
READS = {
    'photoshop': ('photoshop_get_document_info', {}),
    'lightroom': ('get_selected_photos', {'limit': 10, 'offset': 0}),
    # runtime_mode inspects running state without launching Resolve or opening a project.
    'resolve': ('resolve_control', {'action': 'runtime_mode'}),
}


def environment(name):
    # No cloud credentials, proxy configuration, NODE_OPTIONS or Python hooks.
    env = {k: v for k, v in os.environ.items() if k.upper() in
           {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PROGRAMFILES', 'PROGRAMFILES(X86)',
            'PROGRAMDATA', 'PATHEXT'}}
    state = HOME/'desktop/mcp'/name
    for folder in ('home', 'roaming', 'local', 'temp', 'logs'):
        (state/folder).mkdir(parents=True, exist_ok=True)
    system32 = Path(env.get('SYSTEMROOT', 'C:/Windows'))/'System32'
    env.update(HOME=str(state/'home'), USERPROFILE=str(state/'home'),
               APPDATA=str(state/'roaming'), LOCALAPPDATA=str(state/'local'),
               TEMP=str(state/'temp'), TMP=str(state/'temp'),
               PATH=os.pathsep.join([str(PAYLOAD/'node'), str(Path(sys.executable).parent),
                                    str(system32), str(system32/'WindowsPowerShell/v1.0'),
                                    str(system32/'Wbem')]),
               PHOTOWORKFLOW_HOME=str(HOME), PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1',
               ANALYTICS_DISABLED='1', POSTHOG_DISABLED='1', PSMCP_FEEDBACK='0',
               PHOTOSHOP_MCP_HOME=str(state/'home'),
               DAVINCI_RESOLVE_MCP_UPDATE_CHECK='0', DAVINCI_RESOLVE_MCP_UPDATE_MODE='never',
               PHOTOSTUDIO_MCP_LOG_DIR=str(state/'logs'),
               RESOLVE_MCP_LOG_FILE=str(state/'logs/server.log'),
               RESOLVE_MCP_OPERATION_LOG_FILE=str(state/'logs/operations.jsonl'),
               RESOLVE_MCP_SERVER_PREFS=str(state/'preferences.json'),
               DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS=str(state/'analysis-preferences.json'),
               DAVINCI_RESOLVE_MCP_UPDATE_STATE=str(state/'update-state.json'),
               DAVINCI_RESOLVE_BRIDGE_CONFIG=str(state/'bridge.json'))
    # The Lightroom plug-in runs in the real host and creates this local token.
    # Preserve only this exact path, never the rest of the host environment.
    env['LIGHTROOM_MCP_TOKEN_PATH'] = str(Path(os.environ.get('USERPROFILE', str(Path.home())))/
                                           '.config/lightroom-mcp/token')
    return env, state


def command(name):
    if name == 'photoshop':
        return [str(PAYLOAD/'node/node.exe'), str(PAYLOAD/'photoshop/dist/index.js')]
    if name == 'lightroom':
        return [str(PAYLOAD/'lightroom/lightroom.exe')]
    if name == 'resolve':
        return [sys.executable, '-I', str(Path(__file__).resolve()), 'serve', 'resolve']
    raise ValueError('Unknown bundled MCP')


async def check(name, probe):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    env, state = environment(name)
    args = command(name)
    async with asyncio.timeout(40):
        async with stdio_client(StdioServerParameters(command=args[0], args=args[1:], env=env,
                                                       cwd=str(state))) as (reader, writer):
            async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=30)) as session:
                info = await session.initialize()
                tools = []
                cursor = None
                for _ in range(20):
                    page = await session.list_tools(cursor=cursor)
                    tools.extend(t.name for t in page.tools)
                    cursor = page.nextCursor
                    if not cursor:
                        break
                else:
                    raise RuntimeError('Too many MCP tool pages')
                tool, arguments = READS[name]
                if tool not in tools:
                    raise RuntimeError('Pinned MCP inspection tool is unavailable: '+tool)
                result = dict(server=name, serverReady=True, serverInfo=info.serverInfo.model_dump(),
                              toolCount=len(tools), hostChecked=False)
                if not probe:
                    if name == 'photoshop':
                        running = subprocess.run([str(Path(env['SYSTEMROOT'])/'System32/tasklist.exe'),
                            '/FI', 'IMAGENAME eq Photoshop.exe', '/FO', 'CSV', '/NH'],
                            capture_output=True, text=True, errors='replace', timeout=10,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=True)
                        if not any(row and row[0].lower() == 'photoshop.exe'
                                   for row in csv.reader(running.stdout.splitlines())):
                            result.update(hostChecked=True, inspection={'isError': True, 'content': [
                                {'type': 'text', 'text': 'Open Photoshop and a document, then inspect again.'}]})
                            return result
                        # Detection is lazy upstream. Document reads alone cannot
                        # initialize a new connection even when Photoshop is open.
                        if 'photoshop_ping' not in tools:
                            raise RuntimeError('Pinned Photoshop detection tool is missing')
                        detected = await session.call_tool('photoshop_ping', {})
                        if detected.isError:
                            result.update(hostChecked=True, inspection=detected.model_dump(mode='json', exclude_none=True))
                            return result
                    response = await session.call_tool(tool, arguments)
                    result.update(hostChecked=True, inspection=response.model_dump(mode='json', exclude_none=True))
                return result


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in {'serve', 'probe', 'inspect'} or sys.argv[2] not in READS:
        raise ValueError('Use serve/probe/inspect and photoshop/lightroom/resolve')
    mode, name = sys.argv[1:]
    sys.path.insert(0, str(PAYLOAD/'python-libs'))
    if mode == 'serve':
        env, state = environment(name)
        os.environ.clear()
        os.environ.update(env)
        os.chdir(state)
        if name == 'resolve':
            sys.argv = [str(PAYLOAD/'resolve/src/server.py')]
            runpy.run_path(sys.argv[0], run_name='__main__')
        else:
            raise SystemExit(subprocess.call(command(name), env=env,
                                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)))
    else:
        print(json.dumps(asyncio.run(check(name, mode == 'probe'))))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        while isinstance(error, BaseExceptionGroup) and error.exceptions:
            error = error.exceptions[0]
        print(f'{type(error).__name__}: {error}', file=sys.stderr)
        raise SystemExit(1)

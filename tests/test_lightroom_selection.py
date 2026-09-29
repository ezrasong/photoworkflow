"""Execute SDK fixtures in installed Lua; never start Lightroom or open a catalog."""
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LightroomSelectionTests(unittest.TestCase):
    def test_packaged_bridge_matches_maintained_source(self):
        self.assertEqual((ROOT/'integrations/PhotoWorkflow.lrplugin/Bridge.lua').read_bytes(),
                         (ROOT/'packaging/seed/apps/PhotoWorkflow.lrplugin/Bridge.lua').read_bytes())

    def test_sdk_selection_contract(self):
        lua = shutil.which('lua') or shutil.which('luajit')
        if lua:
            subprocess.run([lua, 'tests/lightroom_selection.lua'], cwd=ROOT, check=True)
            return
        # Lightroom ships a Lua 5.1 interpreter. Load only its runtime, with fake
        # SDK globals; no Lightroom process, plug-in queue, catalog or photo I/O.
        dll = Path(os.environ.get('ProgramFiles', 'C:/Program Files'))/'Adobe/Adobe Lightroom Classic/AgKernel.dll'
        if os.name != 'nt' or not dll.is_file():
            self.skipTest('Requires an installed Lua interpreter or Lightroom Lua runtime')
        lua = ctypes.CDLL(str(dll))
        lua.luaL_newstate.restype = ctypes.c_void_p
        lua.luaL_openlibs.argtypes = [ctypes.c_void_p]
        lua.luaL_loadstring.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lua.lua_pcall.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        lua.lua_tolstring.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        lua.lua_tolstring.restype = ctypes.c_char_p
        lua.lua_close.argtypes = [ctypes.c_void_p]
        state = lua.luaL_newstate()
        self.assertTrue(state)
        previous = Path.cwd()
        try:
            os.chdir(ROOT)
            lua.luaL_openlibs(state)
            result = lua.luaL_loadstring(state, (ROOT/'tests/lightroom_selection.lua').read_bytes())
            if not result:
                result = lua.lua_pcall(state, 0, 0, 0)
            self.assertEqual(result, 0, lua.lua_tolstring(state, -1, None))
        finally:
            lua.lua_close(state)
            os.chdir(previous)


if __name__ == '__main__':
    unittest.main()

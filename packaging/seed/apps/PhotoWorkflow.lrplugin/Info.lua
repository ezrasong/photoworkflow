return {
 LrSdkVersion = 6.0,
 LrSdkMinimumVersion = 6.0,
 LrToolkitIdentifier = 'local.photoworkflow.bridge',
 LrPluginName = 'Luma Atelier',
 LrInitPlugin = 'Bridge.lua',
 -- Menu-only plug-ins otherwise defer initialization until their first use.
 LrForceInitPlugin = true,
 LrShutdownPlugin = 'Shutdown.lua',
 LrLibraryMenuItems = {{title='Luma Atelier bridge status', file='Status.lua'}},
 VERSION = {major=1, minor=2, revision=0},
}

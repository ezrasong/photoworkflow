return {
 LrSdkVersion = 6.0,
 LrSdkMinimumVersion = 6.0,
 LrToolkitIdentifier = 'local.photoworkflow.bridge',
 LrPluginName = 'Photo Studio',
 LrInitPlugin = 'Bridge.lua',
 -- Menu-only plug-ins otherwise defer initialization until their first use.
 LrForceInitPlugin = true,
 LrShutdownPlugin = 'Shutdown.lua',
 LrLibraryMenuItems = {{title='Photo Studio bridge status', file='Status.lua'}},
 VERSION = {major=1, minor=2, revision=0},
}

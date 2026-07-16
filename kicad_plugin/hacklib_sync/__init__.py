"""HackLib Sync — KiCad action plugin package.

Registers a toolbar button / Tools-menu entry in the PCB editor that downloads the
latest shared library bundle from the HackLib server.
"""
from .hacklib_sync_action import HackLibSyncPlugin

HackLibSyncPlugin().register()

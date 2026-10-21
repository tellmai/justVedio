"""Independent settings: the reference application's preferences are untouched."""
from PySide6.QtCore import QSettings
from .version import APP_NAME, ORGANIZATION

def application_settings():
    return QSettings(ORGANIZATION, APP_NAME)

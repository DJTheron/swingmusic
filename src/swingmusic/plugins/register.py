from swingmusic.db.userdata import PluginTable
from sqlalchemy.exc import IntegrityError


def register_plugins():
    try:
        PluginTable.insert_one(
            {
                "name": "lyrics_finder",
                "active": False,
                "settings": {"auto_download": False},
                "extra": {
                    "description": "Find lyrics from the internet",
                },
            }
        )
    except IntegrityError:
        pass

    try:
        PluginTable.insert_one(
            {
                "name": "metadata_editor",
                "active": False,
                "settings": {
                    "beets_auto_apply": False,
                },
                "extra": {
                    "description": "Edit music metadata, upload album art, and auto-fetch via beets",
                },
            }
        )
    except IntegrityError:
        pass

---
name: swingmusic-plugin-creator
description: Create, modify, and extend Swing Music plugins. Use this skill whenever the user wants to add new functionality to Swing Music — such as integrating external music services, adding new audio processing features, building recommendation engines, creating scrobblers, adding lyric providers, building notification systems, or any other music-related feature. This skill knows the full plugin architecture, database layer, API patterns, and configuration system. Use it even if the user just says they want to "add a feature" or "integrate with X" or "build something for Swing Music" — those are all plugin tasks.
---

# Swing Music Plugin Creator

A skill for creating, modifying, and extending plugins in the Swing Music self-hosted music player. This skill encodes deep knowledge of the Swing Music architecture so you can build production-ready plugins that follow all project conventions.

## Architecture Overview

Swing Music is a Flask-based self-hosted music server built on:
- **Framework**: Flask 3.1+ with `flask-openapi3` (OpenAPI 3.0 auto-documentation)
- **Database**: SQLAlchemy 2.0+ with SQLite (WAL mode, two databases: `swingmusic.db` for library data, `userdata.db` for user/plugin data)
- **Auth**: JWT via `flask-jwt-extended` with role-based access
- **Validation**: Pydantic `BaseModel` schemas for all request/response bodies
- **Plugin System**: Class-based inheritance with decorator-driven lifecycle

The source code lives under `src/swingmusic/`. Read `references/architecture.md` for the full directory map when you need details on any specific subsystem.

## Plugin System Deep Dive

Every plugin in Swing Music follows this pattern:

### 1. The Base Plugin Class

**Location**: `src/swingmusic/plugins/__init__.py`

```python
class Plugin:
    def __init__(self, name: str, description: str) -> None:
        self.enabled = False
        self.name = name
        self.description = description

    def set_active(self, state: bool):
        self.enabled = state
```

The `@plugin_method` decorator prevents execution when a plugin is disabled:

```python
def plugin_method(func):
    def wrapper(*args, **kwargs):
        plugin: Plugin = args[0]
        if plugin.enabled:
            return func(*args, **kwargs)
        else:
            return
    return wrapper
```

### 2. Plugin Data Model

**Location**: `src/swingmusic/models/plugins.py`

```python
@dataclass
class Plugin:
    name: str
    active: bool
    settings: dict
    extra: dict
```

### 3. Plugin Database Table

**Location**: `src/swingmusic/db/userdata.py`

The `PluginTable` stores plugin state persistently:

```python
class PluginTable(Base):
    __tablename__ = "plugin"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(), unique=True)
    active: Mapped[bool] = mapped_column(Boolean())
    settings: Mapped[dict[str, Any]] = mapped_column(JSON())
    extra: Mapped[dict[str, Any]] = mapped_column(JSON(), nullable=True)
```

Key class methods: `get_all()`, `get_by_name(name)`, `activate(name, value)`, `update_settings(name, settings)`.

### 4. Plugin Registration

**Location**: `src/swingmusic/plugins/register.py`

Plugins are registered at startup by inserting a row into `PluginTable`. The `IntegrityError` catch allows safe re-runs:

```python
def register_plugins():
    try:
        PluginTable.insert_one({
            "name": "my_plugin",
            "active": False,
            "settings": {"some_option": False},
            "extra": {"description": "What the plugin does"},
        })
    except IntegrityError:
        pass
```

### 5. Plugin API Endpoints

**Location**: `src/swingmusic/api/plugins/__init__.py`

Existing management endpoints (you get these for free):
- `GET /plugins/` — list all plugins
- `POST /plugins/setactive` — enable/disable a plugin
- `POST /plugins/settings` — update plugin settings

For plugin-specific endpoints, create a new file under `src/swingmusic/api/plugins/`.

### 6. App Builder Integration

**Location**: `src/swingmusic/app_builder.py`

Plugin API blueprints are registered in `load_plugins()`:

```python
def load_plugins(web: OpenAPI):
    web.register_api(swing_api.plugins.api)
    web.register_api(lyrics_plugin.api)
    web.register_api(mixes_plugin.api)
```

---

## Creating a New Plugin — Step by Step

When a user asks for new functionality, follow these steps in order. Each step references the exact files to create or modify.

### Step 1: Design the Plugin

Before writing code, clarify with the user:
1. **What** does the plugin do? (e.g., "Scrobble to ListenBrainz", "Download album art from Fanart.tv")
2. **What settings** should be configurable? (API keys, toggle options, thresholds)
3. **Does it need external API calls?** If so, what endpoints?
4. **Does it need its own database tables?** Most plugins just use `PluginTable.settings` for config; only add custom tables for complex data
5. **Does it need API endpoints?** Most plugins that provide data to the frontend need them

### Step 2: Create the Plugin Class

Create a new file: `src/swingmusic/plugins/<plugin_name>.py`

Follow this template:

```python
import json
from pathlib import Path
from typing import Any

from swingmusic.plugins import Plugin, plugin_method
from swingmusic.db.userdata import PluginTable
from swingmusic.settings import Paths
from swingmusic.logger import log


class MyPlugin(Plugin):
    """
    Brief description of what this plugin does.
    """

    def __init__(self):
        super().__init__("my_plugin", "Human-readable description")

        # Load state from database
        entry = PluginTable.get_by_name("my_plugin")
        if entry:
            self.set_active(entry.active)
            self._settings = entry.settings
        else:
            self._settings = {}

    @plugin_method
    def do_something(self, track, **kwargs):
        """
        Main functionality. The @plugin_method decorator ensures
        this returns None if the plugin is disabled.
        """
        # Implementation here
        pass

    def _get_storage_dir(self) -> Path:
        """Plugin-specific storage under ~/.swingmusic/plugins/<name>/"""
        path = Paths().plugins_path / "my_plugin"
        path.mkdir(parents=True, exist_ok=True)
        return path
```

Key patterns from existing plugins:
- **LastFmPlugin** takes `current_userid` in `__init__` for per-user state
- **MixesPlugin** sets itself active unconditionally in `__init__`
- **Lyrics** plugin loads a token from disk cache under `Paths().lyrics_plugins_path`
- Use `@background` decorator from `swingmusic.utils.threading` for async work

### Step 3: Register the Plugin

Edit `src/swingmusic/plugins/register.py` — add a new `try/except` block:

```python
def register_plugins():
    # ... existing registrations ...

    try:
        PluginTable.insert_one({
            "name": "my_plugin",
            "active": False,
            "settings": {"api_key": "", "auto_sync": False},
            "extra": {"description": "What this plugin does for the user"},
        })
    except IntegrityError:
        pass
```

The `name` field MUST match the name passed to `super().__init__()` in your plugin class.

### Step 4: Create API Endpoints (if needed)

Create: `src/swingmusic/api/plugins/<plugin_name>.py`

Follow this exact pattern:

```python
from flask_openapi3 import Tag, APIBlueprint
from pydantic import BaseModel, Field

bp_tag = Tag(name="My Plugin", description="Description of plugin endpoints")
api = APIBlueprint(
    "myplugin", __name__,
    url_prefix="/plugins/myplugin",
    abp_tags=[bp_tag]
)


class MyRequestBody(BaseModel):
    """Pydantic model for request validation"""
    some_field: str = Field(description="What this field is", example="example_value")


@api.post("/action")
def do_action(body: MyRequestBody):
    """
    Endpoint description for OpenAPI docs.
    """
    # Use plugin class here
    plugin = MyPlugin()
    result = plugin.do_something(body.some_field)

    if result:
        return {"data": result}, 200
    return {"error": "Something went wrong"}, 400
```

Important conventions:
- URL prefix MUST be `/plugins/<plugin_name>`
- Use `APIBlueprint` from `flask_openapi3`, NOT regular Flask `Blueprint`
- All request bodies use Pydantic `BaseModel` with `Field` descriptions
- Return JSON dicts with HTTP status codes
- Use `@admin_required()` from `swingmusic.api.auth` for admin-only endpoints

### Step 5: Wire Up the Blueprint

Edit `src/swingmusic/app_builder.py`:

1. Add the import at the top:
```python
from swingmusic.api.plugins import my_plugin as my_plugin_module
```

2. Register in `load_plugins()`:
```python
def load_plugins(web: OpenAPI):
    web.register_api(swing_api.plugins.api)
    web.register_api(lyrics_plugin.api)
    web.register_api(mixes_plugin.api)
    web.register_api(my_plugin_module.api)  # NEW
```

### Step 6: Add Custom Database Tables (only if needed)

Most plugins store their config in `PluginTable.settings` (a JSON column). Only create a custom table if the plugin manages its own collection of records (like `MixTable` does for mixes).

If needed, add to `src/swingmusic/db/userdata.py`:

```python
class MyPluginDataTable(Base):
    __tablename__ = "my_plugin_data"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Add your columns...
    data: Mapped[dict[str, Any]] = mapped_column(JSON())
```

The `Base` class provides: `insert_one()`, `insert_many()`, `remove_one()`, `all()`, `count()`, `execute()`.

### Step 7: Add Background/Periodic Tasks (if needed)

For background work, use the `@background` decorator:

```python
from swingmusic.utils.threading import background

class MyPlugin(Plugin):
    @plugin_method
    @background
    def sync_data(self):
        """Runs in a background thread"""
        pass
```

For periodic tasks, look at `src/swingmusic/crons/` for patterns — but prefer on-demand execution through API endpoints when possible.

### Step 8: Handle Plugin-Specific File Storage

Plugins that need to cache data on disk should use `Paths().plugins_path / "<plugin_name>"`:

```python
storage_dir = Paths().plugins_path / "my_plugin"
storage_dir.mkdir(parents=True, exist_ok=True)

# Write cache
(storage_dir / "cache.json").write_text(json.dumps(data))

# Read cache
data = json.loads((storage_dir / "cache.json").read_text())
```

This resolves to `~/.swingmusic/plugins/my_plugin/` (or the configured config directory).

---

## Modifying Existing Plugins

When the user wants to extend an existing plugin:

1. Read the existing plugin class carefully — check `references/existing-plugins.md` for summaries
2. Add new methods with `@plugin_method` decorator
3. If adding new settings, update the `register_plugins()` defaults AND handle missing keys gracefully (existing installs won't have the new settings)
4. If adding new endpoints, follow Step 4-5 above

Common modification patterns:
- **Adding a setting**: Update `register_plugins()` defaults, read from `self._settings` in the plugin class
- **Adding an endpoint**: Create or edit the API file under `api/plugins/`, register in `app_builder.py`
- **Adding background work**: Use `@background` decorator, trigger from API endpoint or existing hook

---

## Accessing Core Data

Plugins often need to interact with the music library. Here's how:

### Track/Album/Artist Stores

In-memory stores hold the indexed library:

```python
from swingmusic.store.tracks import TrackStore
from swingmusic.store.albums import AlbumStore
from swingmusic.store.artists import ArtistStore

# Get a track by hash
track = TrackStore.trackmap.get(trackhash)

# Get all tracks
all_tracks = TrackStore.tracks

# Get album by hash
album = AlbumStore.albummap.get(albumhash)

# Get artist by hash
artist = ArtistStore.artistmap.get(artisthash)
```

### User Context

```python
from swingmusic.utils.auth import get_current_userid

userid = get_current_userid()  # Current authenticated user's ID
```

### Configuration

```python
from swingmusic.config import UserConfig

config = UserConfig()  # Singleton
# Access any config field, e.g.:
# config.lastfmApiKey, config.rootDirs, etc.
```

### Hashing

```python
from swingmusic.utils.hashing import create_hash

hash_val = create_hash("some string")  # Used for deduplication throughout the app
```

---

## Testing Your Plugin

1. **Manual testing**: Start the dev server with `python run.py` and test endpoints via the OpenAPI docs at `/docs`
2. **Check registration**: Verify your plugin appears in `GET /plugins/`
3. **Check enable/disable**: Toggle via `POST /plugins/setactive` and confirm `@plugin_method` respects the state
4. **Check settings**: Update via `POST /plugins/settings` and verify persistence

---

## Complete File Checklist

When creating a new plugin, you will typically touch these files:

| File | Action | Required? |
|------|--------|-----------|
| `src/swingmusic/plugins/<name>.py` | Create plugin class | Yes |
| `src/swingmusic/plugins/register.py` | Add registration entry | Yes |
| `src/swingmusic/api/plugins/<name>.py` | Create API endpoints | If plugin has endpoints |
| `src/swingmusic/app_builder.py` | Register API blueprint | If plugin has endpoints |
| `src/swingmusic/db/userdata.py` | Add custom DB table | Only for complex data |
| `src/swingmusic/models/<name>.py` | Add data model | Only for complex data |
| `src/swingmusic/config.py` | Add config fields | Only if global config needed |

---

## Reference Files

Read these when you need deeper detail on specific subsystems:

- `references/architecture.md` — Full project directory structure and module map
- `references/existing-plugins.md` — Detailed breakdown of Lyrics, LastFm, and Mixes plugins
- `references/api-patterns.md` — API blueprint patterns, auth decorators, response formats

---

## Common Plugin Ideas and Patterns

Here are patterns for frequently requested plugin types:

### External Service Integration (e.g., ListenBrainz, Spotify, Tidal)
- Plugin class makes HTTP requests to external API
- Store API keys/tokens in `PluginTable.settings`
- Use `@background` for async API calls
- Cache responses in `Paths().plugins_path / "<name>"/`

### Audio Processing (e.g., ReplayGain, Loudness Normalization)
- Plugin processes audio files from `Track.filepath`
- Store computed values in a custom DB table or `Track.extra`
- Trigger processing via API endpoint or during library scan

### Notification/Webhook (e.g., Discord, Slack notifications)
- Plugin sends HTTP POST to webhook URL on events (play, scrobble)
- Store webhook URL in `PluginTable.settings`
- Hook into scrobble/playback flow via background tasks

### Data Import/Export (e.g., playlist import, library stats export)
- Plugin reads/writes files via `Paths()` system
- Create API endpoints for trigger/download
- Use existing store data (`TrackStore`, `AlbumStore`) for exports

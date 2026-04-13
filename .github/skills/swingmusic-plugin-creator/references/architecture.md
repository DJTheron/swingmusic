# Swing Music Architecture Reference

## Project Root Structure

```
swingmusic/
├── run.py                    # CLI entry point (argparse → start_swingmusic)
├── pyproject.toml            # Build config (hatchling, Python ≥3.10)
├── requirements.txt          # Dependencies
├── version.txt               # Version string
├── src/swingmusic/
│   ├── __main__.py           # Package entry point
│   ├── start_swingmusic.py   # Server startup orchestrator
│   ├── app_builder.py        # Flask app factory (build())
│   ├── config.py             # UserConfig singleton (settings.json)
│   ├── settings.py           # Paths singleton + Metadata + Defaults
│   ├── logger.py             # Logging setup
│   ├── tools.py              # CLI argument parsing
│   ├── periodic_scan.py      # Periodic library scanning
│   ├── api/                  # REST API layer
│   ├── plugins/              # Plugin system
│   ├── models/               # Data models (dataclasses)
│   ├── db/                   # Database layer (SQLAlchemy)
│   ├── store/                # In-memory data stores
│   ├── crons/                # Background/periodic tasks
│   ├── utils/                # Utility modules
│   ├── enums/                # Enumerations
│   ├── serializers/          # Data serialization
│   ├── setup/                # First-run setup
│   ├── migrations/           # DB schema migrations
│   ├── data/                 # Static data files
│   ├── assets/               # App assets
│   ├── jsoni/                # JSON index files
│   ├── request/              # External HTTP request helpers
│   └── lib/                  # Vendored libraries (pydub, etc.)
```

## Startup Flow

1. `run.py` / `__main__.py` → parses CLI args via `tools.py`
2. `start_swingmusic.py` → orchestrates startup:
   - Initializes `Paths()` and `UserConfig()` singletons
   - Creates database tables
   - Runs migrations
   - Starts library indexing
   - Calls `register_plugins()` as background task
   - Calls `app_builder.build()` to create Flask app
   - Starts the Waitress WSGI server

## Database Architecture

Two separate SQLite databases:

### App Database (`swingmusic.db`)
- `TrackTable` — all indexed tracks
- `AlbumTable` — all albums
- `ArtistTable` — all artists

### User Database (`userdata.db`)
- `UserTable` — authentication & profiles
- `PluginTable` — plugin state & config
- `PlaylistTable` — user playlists
- `FavoritesTable` — favorited items
- `PlaybackLogTable` — play history / scrobbles
- `SimilarArtistTable` — cached similar artists
- `MixTable` — generated mixes/recommendations

### Database Engine (`db/engine.py`)

```python
class DbEngine:
    """App database engine — singleton pattern"""
    _engine: Engine | None = None

    @classproperty
    def engine(cls) -> Engine:
        # Creates SQLite engine with WAL mode, pool_size=10, max_overflow=20

class UserDataDbEngine:
    """User database engine — same pattern"""
```

SQLite pragmas applied on connect:
- `journal_mode=WAL` (concurrent reads/writes)
- `synchronous=NORMAL`
- `cache_size=10000`
- `foreign_keys=ON`

### Base Table Class (`db/__init__.py`)

All tables inherit from `Base(MappedAsDataclass, DeclarativeBase)` which provides:
- `execute(stmt, commit)` — runs any SQLAlchemy statement
- `insert_one(item)` / `insert_many(items)`
- `remove_one(id)`
- `all()` — fetch all records
- `count()` — count records

## In-Memory Stores (`store/`)

The library is loaded into memory for fast access:

- `TrackStore` — `tracks: list[Track]`, `trackmap: dict[str, Track]`
- `AlbumStore` — `albums: list[Album]`, `albummap: dict[str, Album]`
- `ArtistStore` — `artists: list[Artist]`, `artistmap: dict[str, Artist]`

These are populated during startup from the database and refreshed on library rescans.

## API Layer (`api/`)

### Blueprint Registration

All blueprints are registered in `app_builder.py`:
- `load_endpoints(web)` — core API blueprints
- `load_plugins(web)` — plugin API blueprints

### Blueprint Pattern

```python
from flask_openapi3 import APIBlueprint, Tag
from pydantic import BaseModel, Field

bp_tag = Tag(name="Module Name", description="Module description")
api = APIBlueprint("module_name", __name__, url_prefix="/module", abp_tags=[bp_tag])

class RequestBody(BaseModel):
    field: str = Field(description="...", example="...")

@api.post("/endpoint")
def handler(body: RequestBody):
    return {"data": result}, 200
```

### Auth Decorators

```python
from swingmusic.api.auth import admin_required

@api.post("/admin-only")
@admin_required()
def protected_endpoint(body: SomeBody):
    pass
```

### Core API Modules

| Module | URL Prefix | Purpose |
|--------|-----------|---------|
| `album.py` | `/album` | Album info & tracks |
| `artist.py` | `/artist` | Artist info & discography |
| `stream.py` | `/stream` | Audio streaming & transcoding |
| `search.py` | `/search` | Full-text search |
| `folder.py` | `/folder` | Directory browsing |
| `playlist.py` | `/playlist` | Playlist CRUD |
| `favorites.py` | `/favorites` | Favorites management |
| `imgserver.py` | `/img` | Image serving |
| `settings.py` | `/settings` | App settings |
| `colors.py` | `/colors` | Color extraction from images |
| `lyrics.py` | `/lyrics` | Lyrics (non-plugin) |
| `auth.py` | `/auth` | Login / registration / JWT |
| `scrobble/` | `/logger` | Play logging |
| `home/` | `/home` | Homepage recommendations |
| `getall/` | `/getall` | Bulk data endpoints |
| `plugins/` | `/plugins` | Plugin management + plugin-specific |

## Configuration (`config.py`)

`UserConfig` is a singleton dataclass that auto-persists to `~/.swingmusic/settings.json`:

Key plugin-related fields:
- `enablePlugins: bool` — global plugin toggle
- `lastfmApiKey: str` — Last.fm API key
- `lastfmApiSecret: str` — Last.fm API secret
- `lastfmSessionKeys: dict[str, str]` — per-user session keys

Setting any attribute on `UserConfig()` automatically writes to disk.

## Paths (`settings.py`)

`Paths` singleton manages all filesystem paths:

| Property | Resolves To |
|----------|------------|
| `config_dir` | `~/.swingmusic/` or `~/.config/swingmusic/` |
| `plugins_path` | `<config_dir>/plugins/` |
| `app_db_path` | `<config_dir>/swingmusic.db` |
| `userdata_db_path` | `<config_dir>/userdata.db` |
| `config_file_path` | `<config_dir>/settings.json` |
| `artist_img_path` | `<config_dir>/images/artists/` |
| `client_path` | `<config_dir>/client/` |

## Utility Modules (`utils/`)

| Module | Purpose |
|--------|---------|
| `auth.py` | `get_current_userid()` — current JWT user |
| `threading.py` | `@background` decorator for async execution |
| `hashing.py` | `create_hash()` — content hashing for dedup |
| `dates.py` | Date/time range utilities |
| `files.py` | File system operations |
| `parsers.py` | Metadata parsing helpers |
| `network.py` | HTTP request helpers |
| `stats.py` | Listening statistics |
| `mixes.py` | Mix balancing algorithms |

## Key Dependencies

- `flask` / `flask-openapi3` — Web framework
- `sqlalchemy` — ORM / database
- `flask-jwt-extended` — Authentication
- `flask-cors` — CORS handling
- `flask-compress` — Response compression
- `pydantic` — Request validation
- `requests` — HTTP client
- `Pillow` — Image processing
- `mutagen` — Audio metadata reading
- `waitress` — Production WSGI server
- `unidecode` — Unicode text normalization

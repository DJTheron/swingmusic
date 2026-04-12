# Existing Swing Music Plugins Reference

This document describes the three existing plugins in detail. Use these as templates when creating new plugins.

---

## 1. Lyrics Plugin

**Files**:
- Plugin class: `src/swingmusic/plugins/lyrics.py`
- API endpoints: `src/swingmusic/api/plugins/lyrics.py`

### Plugin Class: `Lyrics`

```
Lyrics(Plugin)
├── Inherits from Plugin base class
├── Constructor: super().__init__("lyrics_finder", "...")
│   └── Loads active state from PluginTable
├── search_lyrics_by_title_and_artist(title, artist) → list[dict]
│   └── Searches Musixmatch API for matching lyrics
├── download_lyrics(track_id, filepath) → str | None
│   └── Downloads .lrc file and saves alongside audio file
└── Uses LyricsProvider (Musixmatch) as underlying engine
```

### Key Patterns:
- **External API integration**: Uses `requests.Session` with custom User-Agent
- **Token caching**: Stores Musixmatch tokens at `Paths().lyrics_plugins_path / "token.json"`
- **File I/O**: Saves `.lrc` files next to audio files
- **No `@plugin_method`**: Active state checked manually in constructor
- **Settings**: `{"auto_download": False}`

### Sub-classes:
- `LRCProvider` — Abstract base for synced lyrics providers
- `LyricsProvider(LRCProvider)` — Musixmatch implementation with:
  - Token fetching and caching
  - Search by title+artist
  - LRC download by track ID

### API Endpoint:
```
POST /plugins/lyrics/search
Body: {title, artist, album, filepath, trackhash}
Response: {trackhash, lyrics: [...]}
```

---

## 2. Last.fm Plugin

**Files**:
- Plugin class: `src/swingmusic/plugins/lastfm.py`
- API endpoints: `src/swingmusic/api/plugins/__init__.py` (inline with main plugin API)

### Plugin Class: `LastFmPlugin`

```
LastFmPlugin(Plugin)
├── Constructor: super().__init__("lastfm", "Last.fm scrobbler")
│   ├── Takes current_userid parameter (per-user auth)
│   ├── Loads UserConfig for API keys
│   └── Sets active based on: API key + secret + session key all present
├── get_api_signature(data) → str
│   └── MD5-based HMAC signing for Last.fm API
├── post(data, useSessionKey=True) → Response
│   └── Sends signed POST to Last.fm API
├── get_session_key(token) → str | None
│   └── OAuth: exchanges token for session key
├── @plugin_method @background
│   scrobble(track, timestamp) → bool
│   ├── Posts scrobble to Last.fm
│   ├── On failure: dumps to disk for retry
│   └── On success: uploads any pending dumps
├── post_scrobble_data(data) → bool
│   └── Handles Last.fm API response + error codes
├── dump_scrobble(data)
│   └── Saves failed scrobble to Paths().plugins_path / "lastfm" / "<timestamp>.json"
└── upload_dumps()
    └── Retries all dumped scrobbles, deletes on success
```

### Key Patterns:
- **Per-user state**: Constructor takes `current_userid`, session keys stored per-user in `UserConfig.lastfmSessionKeys`
- **Background execution**: `@plugin_method` + `@background` for async scrobbling
- **Resilient delivery**: Failed scrobbles dumped to disk, retried on next success
- **Config-based activation**: Active only when all required config present (API key, secret, session key)
- **Class-level flag**: `UPLOADING_DUMPS = False` prevents concurrent dump uploads

### API Endpoints:
```
POST /plugins/lastfm/session/create
Body: {token}
Response: {status, session_key}

POST /plugins/lastfm/session/delete
Response: {status}
```

---

## 3. Mixes Plugin

**Files**:
- Plugin class: `src/swingmusic/plugins/mixes.py`
- API endpoints: `src/swingmusic/api/plugins/mixes.py`

### Plugin Class: `MixesPlugin`

```
MixesPlugin(Plugin)
├── Constructor: super().__init__("mixes", "Mixes")
│   ├── Always sets active to True
│   └── Configures cloud server URL
├── Class constants:
│   ├── MAX_TRACKS_TO_FETCH = 5
│   ├── MIN_TRACK_MIX_LENGTH = 15
│   ├── MIN_ARTISTS_PER_MIX = 4
│   └── MIX_TRACKS_LENGTH = 40
├── ping_server() → bool
│   └── Health check with retries
├── @plugin_method
│   get_track_mix_data(tracks) → list[str]
│   └── Fetches recommendations from cloud server
├── create_artist_mixes(userid) → list[Mix]
│   ├── Generates mixes for user's top artists
│   ├── Uses listening stats (daily/weekly/monthly)
│   └── Stores results in MixTable
├── create_artist_mix() → Mix
│   └── Single artist mix generation
├── create_mix_image(tracks) → bytes
│   └── Composite image from multiple track covers using Pillow
└── Various helper methods for mix balancing and filtering
```

### Key Patterns:
- **External cloud service**: Calls `https://smcloud.mungaist.com/radio` for recommendations
- **Unconditional activation**: Always active (no per-user config needed)
- **Database integration**: Uses `MixTable` for persistent mix storage
- **Image generation**: Uses Pillow to create composite mix cover images
- **Store access**: Reads from `TrackStore`, `AlbumStore`, `ArtistStore` for library data
- **Statistics integration**: Uses `swingmusic.utils.stats` for listening history analysis
- **Complex business logic**: Mix balancing, artist diversity, duration thresholds

### API Endpoints:
```
GET /plugins/mixes/<mixtype>
Response: {mixes: [...]}

GET /plugins/mixes/
Query: {sourcehash, userid}
Response: {mix: {...}}

POST /plugins/mixes/save
Body: {mix data}
Response: {status}
```

---

## Summary: Plugin Pattern Comparison

| Aspect | Lyrics | LastFm | Mixes |
|--------|--------|--------|-------|
| Registration name | `lyrics_finder` | `lastfm` | `mixes` |
| Activation | From DB state | Config-dependent | Always active |
| Per-user state | No | Yes (session keys) | Yes (userid for mixes) |
| External API | Musixmatch | Last.fm | Cloud server |
| File storage | Token cache, .lrc files | Failed scrobble dumps | Mix images |
| Custom DB table | No | No | Yes (MixTable) |
| Background tasks | No | Yes (@background) | No |
| Uses @plugin_method | Limited | Yes | Yes |
| Settings | auto_download | N/A (uses UserConfig) | N/A |

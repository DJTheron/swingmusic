# Swing Music API Patterns Reference

This document covers the patterns, conventions, and auth system used in the Swing Music REST API. Use this when creating API endpoints for new plugins.

---

## Blueprint Creation

Every API module creates an `APIBlueprint` with:
1. A unique name string (used internally by Flask)
2. `__name__` for module resolution
3. A `url_prefix` for route namespacing
4. One or more `Tag` objects for OpenAPI documentation grouping

```python
from flask_openapi3 import APIBlueprint, Tag

bp_tag = Tag(name="Display Name", description="Description for API docs")
api = APIBlueprint("unique_name", __name__, url_prefix="/prefix", abp_tags=[bp_tag])
```

For plugins, the convention is:
- Blueprint name: plugin name without underscores (e.g., `"lyricsplugin"`)
- URL prefix: `/plugins/<plugin_name>` (e.g., `/plugins/lyrics`)
- Tag name: Human-readable with "Plugin" suffix (e.g., `"Lyrics Plugin"`)

---

## Request Body Schemas

All POST/PUT request bodies are validated via Pydantic `BaseModel`:

```python
from pydantic import BaseModel, Field

class MyBody(BaseModel):
    required_field: str = Field(description="What this is", example="sample")
    optional_field: int = Field(default=10, description="Optional with default")
```

Common shared schemas are in `src/swingmusic/api/apischemas.py`:

```python
class TrackHashSchema(BaseModel):
    trackhash: str = Field(description="Track hash")

class AlbumHashSchema(BaseModel):
    albumhash: str = Field(description="Album hash")

class AlbumLimitSchema(BaseModel):
    limit: int = Field(default=6, description="Result limit")
```

Inherit from these when your endpoint needs a trackhash or albumhash.

---

## Route Decorators

### HTTP Methods

```python
@api.get("/path")          # GET request
@api.post("/path")         # POST request
@api.put("/path")          # PUT request
@api.delete("/path")       # DELETE request
```

### Authentication

All routes require JWT authentication by default (enforced in `app_builder.py:verify_auth()`).

For admin-only endpoints:

```python
from swingmusic.api.auth import admin_required

@api.post("/admin-action")
@admin_required()
def admin_endpoint(body: SomeBody):
    pass
```

Routes that don't need auth are whitelisted in `app_builder.py:check_auth_need()`.

---

## Response Format

Endpoints return a tuple of `(dict, status_code)`:

```python
# Success
return {"data": result, "status": "success"}, 200

# Error
return {"error": "Description of what went wrong"}, 400

# Simple acknowledgment
return {"message": "OK"}, 200
```

Common patterns from existing code:
```python
# List response
return {"plugins": list_of_plugins}

# Single item
return {"trackhash": hash_val, "lyrics": lyrics_data}, 200

# Status response
return {"status": "success", "settings": new_settings}
```

---

## Accessing Current User

```python
from swingmusic.utils.auth import get_current_userid

@api.get("/my-data")
def get_my_data():
    userid = get_current_userid()
    # Use userid to fetch user-specific data
```

For full user object:
```python
from flask_jwt_extended import current_user

@api.get("/profile")
def get_profile():
    user = current_user  # Dict with id, username, roles, etc.
```

---

## Path Parameters

```python
@api.get("/<string:mixtype>")
def get_mixes(path: MixTypeSchema):
    mixtype = path.mixtype
```

With schema:
```python
class MixTypeSchema(BaseModel):
    mixtype: str = Field(description="Type of mix", example="artist_mixes")
```

---

## Query Parameters

```python
class MyQuery(BaseModel):
    page: int = Field(default=1, description="Page number")
    limit: int = Field(default=20, description="Items per page")

@api.get("/items")
def get_items(query: MyQuery):
    page = query.page
    limit = query.limit
```

---

## File Uploads

Not commonly used in plugins, but the pattern exists in backup/restore:

```python
from flask import request

@api.post("/upload")
def upload_file():
    file = request.files.get("file")
    if file:
        file.save(target_path)
```

---

## Plugin API Registration

Plugin APIs are registered separately from core APIs in `app_builder.py`:

```python
# Import at top of app_builder.py
from swingmusic.api.plugins import my_plugin as my_plugin_module

# Register in load_plugins()
def load_plugins(web: OpenAPI):
    web.register_api(swing_api.plugins.api)       # Plugin management endpoints
    web.register_api(lyrics_plugin.api)             # Lyrics plugin
    web.register_api(mixes_plugin.api)              # Mixes plugin
    web.register_api(my_plugin_module.api)          # Your new plugin
```

---

## OpenAPI Documentation

All endpoints are automatically documented at `/docs`. The documentation uses:
- `Tag` objects for grouping
- Pydantic `Field` descriptions for parameter docs
- Docstrings on handler functions for endpoint descriptions

Write clear docstrings — they show up in the API docs:

```python
@api.post("/search")
def search_lyrics(body: LyricsSearchBody):
    """
    Search for lyrics by title and artist.

    Returns matched lyrics data including synced LRC content.
    """
```

---

## Error Handling Patterns

```python
# Input validation
if not body.required_field:
    return {"error": "Missing required_field"}, 400

# Not found
plugin = PluginTable.get_by_name(name)
if not plugin:
    return {"error": "Plugin not found"}, 404

# External service failure
try:
    result = external_api.call()
except Exception as e:
    log.error(f"API call failed: {e}")
    return {"error": "External service unavailable"}, 503
```

---

## CORS and Compression

Configured globally in `app_builder.py:config_app()`:
- CORS: All origins allowed (`origins="*"`)
- Compression: Only `application/json` responses (not CSS/JS for Safari compat)

No per-endpoint CORS config needed.

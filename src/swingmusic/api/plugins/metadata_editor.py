import base64
import logging
from typing import Optional

from flask import request
from flask_openapi3 import APIBlueprint, Tag
from pydantic import BaseModel, Field

from swingmusic.api.auth import admin_required
from swingmusic.plugins.metadata_editor import MetadataEditorPlugin
from swingmusic.store.tracks import TrackStore
from swingmusic.store.albums import AlbumStore

log = logging.getLogger(__name__)

bp_tag = Tag(
    name="Metadata Editor Plugin",
    description="Edit music file metadata, upload album art, and auto-fetch via beets",
)
api = APIBlueprint(
    "metadataeditor",
    __name__,
    url_prefix="/plugins/metadata_editor",
    abp_tags=[bp_tag],
)


# ------------------------------------------------------------------
# Request schemas
# ------------------------------------------------------------------


class TrackMetadataBody(BaseModel):
    filepath: str = Field(description="Absolute path to the audio file")
    title: Optional[str] = Field(default=None, description="Track title")
    artist: Optional[str] = Field(default=None, description="Artist name")
    album: Optional[str] = Field(default=None, description="Album name")
    albumartist: Optional[str] = Field(default=None, description="Album artist name")
    genre: Optional[str] = Field(default=None, description="Genre")
    date: Optional[str] = Field(default=None, description="Release date / year")
    track: Optional[str] = Field(default=None, description="Track number (e.g. '3' or '3/12')")
    disc: Optional[str] = Field(default=None, description="Disc number (e.g. '1' or '1/2')")
    copyright: Optional[str] = Field(default=None, description="Copyright info")
    comment: Optional[str] = Field(default=None, description="Comment")


class AlbumMetadataBody(BaseModel):
    albumhash: str = Field(description="Album hash to identify the album")
    album: Optional[str] = Field(default=None, description="Album name")
    albumartist: Optional[str] = Field(default=None, description="Album artist name")
    genre: Optional[str] = Field(default=None, description="Genre")
    date: Optional[str] = Field(default=None, description="Release date / year")
    copyright: Optional[str] = Field(default=None, description="Copyright info")


class AlbumArtBody(BaseModel):
    filepath: str = Field(description="Absolute path to the audio file")
    image_base64: str = Field(description="Base64-encoded image data (JPEG/PNG)")


class TrackFetchBody(BaseModel):
    filepath: str = Field(description="Absolute path to the audio file")


class AlbumFetchBody(BaseModel):
    folder: str = Field(description="Absolute path to the album folder")


class TrackAutoBody(BaseModel):
    filepath: str = Field(description="Absolute path to the audio file to auto-tag")


class AlbumAutoBody(BaseModel):
    folder: str = Field(description="Absolute path to the album folder to auto-tag")


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


@api.post("/track/update")
@admin_required()
def update_track_metadata(body: TrackMetadataBody):
    """
    Update metadata tags on a single audio file.

    Provide only the fields you want to change; omitted fields are left untouched.
    """
    plugin = MetadataEditorPlugin()

    metadata = {
        k: v
        for k, v in body.model_dump(exclude={"filepath"}).items()
        if v is not None
    }

    if not metadata:
        return {"error": "No metadata fields provided"}, 400

    result = plugin.update_track_metadata(body.filepath, metadata)

    if result is None:
        return {"error": "Plugin is disabled"}, 403

    if not result.get("success"):
        return {"error": result.get("error", "Unknown error")}, 400

    return {"status": "success", "data": result}, 200


@api.post("/album/update")
@admin_required()
def update_album_metadata(body: AlbumMetadataBody):
    """
    Batch-update metadata tags for all tracks in an album.

    Provide only the fields you want to change; omitted fields are left untouched.
    """
    plugin = MetadataEditorPlugin()

    entry = AlbumStore.albummap.get(body.albumhash)
    if entry is None:
        return {"error": "Album not found"}, 404

    tracks = TrackStore.get_tracks_by_trackhashes(entry.trackhashes)
    filepaths = [t.filepath for t in tracks]

    if not filepaths:
        return {"error": "No tracks found for this album"}, 404

    metadata = {
        k: v
        for k, v in body.model_dump(exclude={"albumhash"}).items()
        if v is not None
    }

    if not metadata:
        return {"error": "No metadata fields provided"}, 400

    result = plugin.update_album_metadata(filepaths, metadata)

    if result is None:
        return {"error": "Plugin is disabled"}, 403

    return {"status": "success", "data": result}, 200


@api.post("/track/art/upload")
@admin_required()
def upload_album_art(body: AlbumArtBody):
    """
    Upload and embed album art into an audio file.

    Send the image as a base64-encoded string (JPEG or PNG).
    """
    plugin = MetadataEditorPlugin()

    try:
        image_data = base64.b64decode(body.image_base64)
    except Exception:
        return {"error": "Invalid base64 image data"}, 400

    if len(image_data) > 10 * 1024 * 1024:
        return {"error": "Image too large (max 10 MB)"}, 400

    result = plugin.embed_album_art(body.filepath, image_data)

    if result is None:
        return {"error": "Plugin is disabled"}, 403

    if not result.get("success"):
        return {"error": result.get("error", "Unknown error")}, 400

    return {"status": "success", "data": result}, 200


@api.post("/track/fetch")
@admin_required()
def fetch_track_metadata(body: TrackFetchBody):
    """
    Use beets to preview suggested metadata for a single track.

    Returns beets output with candidate matches (no changes written).
    """
    plugin = MetadataEditorPlugin()
    result = plugin.fetch_track_metadata_via_beets(body.filepath)

    if result is None:
        return {"error": "Plugin is disabled"}, 403

    if not result.get("success"):
        return {"error": result.get("error", "Unknown error")}, 400

    return {"status": "success", "data": result}, 200


@api.post("/album/fetch")
@admin_required()
def fetch_album_metadata(body: AlbumFetchBody):
    """
    Use beets to preview suggested metadata for all tracks in a folder.

    Returns beets output with candidate matches (no changes written).
    """
    plugin = MetadataEditorPlugin()
    result = plugin.fetch_album_metadata_via_beets(body.folder)

    if result is None:
        return {"error": "Plugin is disabled"}, 403

    if not result.get("success"):
        return {"error": result.get("error", "Unknown error")}, 400

    return {"status": "success", "data": result}, 200


@api.post("/track/auto")
@admin_required()
def auto_tag_track(body: TrackAutoBody):
    """
    Automatically apply beets metadata to a single track (auto button).

    This writes tags directly to the file using beets' best match.
    """
    plugin = MetadataEditorPlugin()
    result = plugin.apply_beets_auto(body.filepath)

    if result is None:
        return {"error": "Plugin is disabled"}, 403

    if not result.get("success"):
        return {"error": result.get("error", "Unknown error")}, 400

    return {"status": "success", "data": result}, 200


@api.post("/album/auto")
@admin_required()
def auto_tag_album(body: AlbumAutoBody):
    """
    Automatically apply beets metadata to all tracks in an album folder (auto button).

    This writes tags directly to files using beets' best match.
    """
    plugin = MetadataEditorPlugin()
    result = plugin.apply_beets_auto_album(body.folder)

    if result is None:
        return {"error": "Plugin is disabled"}, 403

    if not result.get("success"):
        return {"error": result.get("error", "Unknown error")}, 400

    return {"status": "success", "data": result}, 200


@api.get("/beets/status")
def get_beets_status():
    """
    Check whether beets is installed and available on the server.
    """
    plugin = MetadataEditorPlugin()
    result = plugin.check_beets_status()

    if result is None:
        return {"error": "Plugin is disabled"}, 403

    return {"status": "success", "data": result}, 200

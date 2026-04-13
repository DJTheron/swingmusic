import base64
import logging
import os
import shutil
import subprocess
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

from PIL import Image, UnidentifiedImageError

from swingmusic.db.userdata import PluginTable
from swingmusic.plugins import Plugin, plugin_method
from swingmusic.settings import Paths
from swingmusic.utils.threading import background

log = logging.getLogger(__name__)


class MetadataEditorPlugin(Plugin):
    """
    Plugin for editing music file metadata (tags) and album art.
    Supports manual editing via mutagen and auto-fetching via beets.
    """

    def __init__(self):
        super().__init__("metadata_editor", "Music metadata editor with beets integration")

        entry = PluginTable.get_by_name("metadata_editor")
        if entry:
            self.set_active(entry.active)
            self._settings = entry.settings
        else:
            self._settings = {}

    # ------------------------------------------------------------------
    # Manual metadata editing
    # ------------------------------------------------------------------

    @plugin_method
    def update_track_metadata(self, filepath: str, metadata: dict[str, Any]) -> dict[str, Any]:
        """
        Write metadata tags to an audio file using mutagen.

        Supported keys: title, artist, album, albumartist, genre, date,
        track, disc, copyright, comment.
        """
        import mutagen

        filepath = Path(filepath)
        if not filepath.exists():
            return {"success": False, "error": "File not found"}

        try:
            audio = mutagen.File(str(filepath), easy=True)
        except Exception as e:
            log.error(f"Failed to open file for tagging: {e}")
            return {"success": False, "error": f"Cannot open file: {e}"}

        if audio is None:
            return {"success": False, "error": "Unsupported audio format"}

        # Map of our field names → mutagen easy-tag keys
        tag_map = {
            "title": "title",
            "artist": "artist",
            "album": "album",
            "albumartist": "albumartist",
            "genre": "genre",
            "date": "date",
            "track": "tracknumber",
            "disc": "discnumber",
            "copyright": "copyright",
            "comment": "comment",
        }

        for key, value in metadata.items():
            tag_key = tag_map.get(key)
            if tag_key and value is not None:
                audio[tag_key] = str(value)

        try:
            audio.save()
        except Exception as e:
            log.error(f"Failed to save tags: {e}")
            return {"success": False, "error": f"Failed to save: {e}"}

        # Touch the file so the library scanner picks up the change
        os.utime(str(filepath))

        return {"success": True, "filepath": str(filepath)}

    @plugin_method
    def update_album_metadata(
        self, filepaths: list[str], metadata: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Batch-update the same metadata fields across multiple files
        (typically all tracks in an album).
        """
        results = []
        for fp in filepaths:
            result = self.update_track_metadata(fp, metadata)
            results.append(result)

        succeeded = sum(1 for r in results if r and r.get("success"))
        return {
            "success": True,
            "updated": succeeded,
            "total": len(filepaths),
            "results": results,
        }

    # ------------------------------------------------------------------
    # Album art upload / embed
    # ------------------------------------------------------------------

    @plugin_method
    def embed_album_art(self, filepath: str, image_data: bytes) -> dict[str, Any]:
        """
        Embed album art into an audio file.

        Supports MP3 (ID3), FLAC, OGG Vorbis, Opus, and MP4/M4A.
        """
        import mutagen
        from mutagen.id3 import APIC, ID3
        from mutagen.mp4 import MP4, MP4Cover
        from mutagen.flac import FLAC, Picture
        from mutagen.oggvorbis import OggVorbis
        from mutagen.oggopus import OggOpus

        filepath = Path(filepath)
        if not filepath.exists():
            return {"success": False, "error": "File not found"}

        # Validate it's actually an image
        try:
            img = Image.open(BytesIO(image_data))
            img.verify()
        except Exception:
            return {"success": False, "error": "Invalid image data"}

        suffix = filepath.suffix.lower()

        try:
            if suffix == ".mp3":
                audio = ID3(str(filepath))
                audio.delall("APIC")
                audio.add(
                    APIC(
                        encoding=3,
                        mime="image/jpeg",
                        type=3,  # Cover (front)
                        desc="Cover",
                        data=image_data,
                    )
                )
                audio.save()

            elif suffix == ".flac":
                audio = FLAC(str(filepath))
                pic = Picture()
                pic.type = 3
                pic.mime = "image/jpeg"
                pic.desc = "Cover"
                pic.data = image_data
                audio.clear_pictures()
                audio.add_picture(pic)
                audio.save()

            elif suffix == ".ogg":
                audio = OggVorbis(str(filepath))
                pic = Picture()
                pic.type = 3
                pic.mime = "image/jpeg"
                pic.desc = "Cover"
                pic.data = image_data
                audio["metadata_block_picture"] = [
                    base64.b64encode(pic.write()).decode("ascii")
                ]
                audio.save()

            elif suffix == ".opus":
                audio = OggOpus(str(filepath))
                pic = Picture()
                pic.type = 3
                pic.mime = "image/jpeg"
                pic.desc = "Cover"
                pic.data = image_data
                audio["metadata_block_picture"] = [
                    base64.b64encode(pic.write()).decode("ascii")
                ]
                audio.save()

            elif suffix in (".m4a", ".mp4", ".aac"):
                audio = MP4(str(filepath))
                audio["covr"] = [MP4Cover(image_data, imageformat=MP4Cover.FORMAT_JPEG)]
                audio.save()

            else:
                return {"success": False, "error": f"Unsupported format: {suffix}"}

        except Exception as e:
            log.error(f"Failed to embed album art: {e}")
            return {"success": False, "error": str(e)}

        os.utime(str(filepath))
        return {"success": True, "filepath": str(filepath)}

    # ------------------------------------------------------------------
    # Beets integration for auto-fetching metadata
    # ------------------------------------------------------------------

    @staticmethod
    def _beets_available() -> bool:
        """Check if the beets CLI is available on the system."""
        return shutil.which("beet") is not None

    @plugin_method
    def fetch_track_metadata_via_beets(self, filepath: str) -> dict[str, Any]:
        """
        Use beets to identify a single track and return the suggested metadata.
        Runs `beet import -t --pretend` (timid + pretend = no writes, shows candidates).
        """
        if not self._beets_available():
            return {"success": False, "error": "beets is not installed on this system. Install it with: pip install beets"}

        filepath = Path(filepath)
        if not filepath.exists():
            return {"success": False, "error": "File not found"}

        try:
            result = subprocess.run(
                ["beet", "import", "-S", str(filepath)],
                capture_output=True,
                text=True,
                timeout=60,
                env={**os.environ, "BEETSDIR": str(self._get_beets_config_dir())},
            )
            output = result.stdout + result.stderr
            return {
                "success": True,
                "filepath": str(filepath),
                "beets_output": output,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Beets timed out"}
        except Exception as e:
            log.error(f"Beets import failed: {e}")
            return {"success": False, "error": str(e)}

    @plugin_method
    def fetch_album_metadata_via_beets(self, folder: str) -> dict[str, Any]:
        """
        Use beets to identify an entire album folder and return suggestions.
        Runs `beet import --pretend` on the directory.
        """
        if not self._beets_available():
            return {"success": False, "error": "beets is not installed on this system. Install it with: pip install beets"}

        folder = Path(folder)
        if not folder.exists() or not folder.is_dir():
            return {"success": False, "error": "Folder not found"}

        try:
            result = subprocess.run(
                ["beet", "import", "-S", str(folder)],
                capture_output=True,
                text=True,
                timeout=120,
                env={**os.environ, "BEETSDIR": str(self._get_beets_config_dir())},
            )
            output = result.stdout + result.stderr
            return {
                "success": True,
                "folder": str(folder),
                "beets_output": output,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Beets timed out"}
        except Exception as e:
            log.error(f"Beets album import failed: {e}")
            return {"success": False, "error": str(e)}

    @plugin_method
    def apply_beets_auto(self, filepath: str) -> dict[str, Any]:
        """
        Automatically apply beets metadata to a single track (non-interactive).
        Uses `beet import -q -s` for quiet singleton mode with automatic matching.
        """
        if not self._beets_available():
            return {"success": False, "error": "beets is not installed on this system. Install it with: pip install beets"}

        filepath = Path(filepath)
        if not filepath.exists():
            return {"success": False, "error": "File not found"}

        try:
            result = subprocess.run(
                ["beet", "import", "-q", "-s", str(filepath)],
                capture_output=True,
                text=True,
                timeout=120,
                env={**os.environ, "BEETSDIR": str(self._get_beets_config_dir())},
            )
            output = result.stdout + result.stderr
            success = result.returncode == 0
            if success:
                os.utime(str(filepath))
            return {
                "success": success,
                "filepath": str(filepath),
                "beets_output": output,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Beets timed out"}
        except Exception as e:
            log.error(f"Beets auto-apply failed: {e}")
            return {"success": False, "error": str(e)}

    @plugin_method
    def apply_beets_auto_album(self, folder: str) -> dict[str, Any]:
        """
        Automatically apply beets metadata to an entire album folder.
        Uses `beet import -q` for quiet album mode.
        """
        if not self._beets_available():
            return {"success": False, "error": "beets is not installed on this system. Install it with: pip install beets"}

        folder = Path(folder)
        if not folder.exists() or not folder.is_dir():
            return {"success": False, "error": "Folder not found"}

        try:
            result = subprocess.run(
                ["beet", "import", "-q", str(folder)],
                capture_output=True,
                text=True,
                timeout=300,
                env={**os.environ, "BEETSDIR": str(self._get_beets_config_dir())},
            )
            output = result.stdout + result.stderr
            success = result.returncode == 0

            # Touch all audio files in folder so scanner picks up changes
            if success:
                for f in folder.iterdir():
                    if f.suffix.lower() in (".mp3", ".flac", ".ogg", ".opus", ".m4a", ".mp4", ".aac", ".wma"):
                        os.utime(str(f))

            return {
                "success": success,
                "folder": str(folder),
                "beets_output": output,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Beets timed out"}
        except Exception as e:
            log.error(f"Beets auto-apply album failed: {e}")
            return {"success": False, "error": str(e)}

    @plugin_method
    def check_beets_status(self) -> dict[str, Any]:
        """Check if beets is available and return version info."""
        available = self._beets_available()
        version = None

        if available:
            try:
                result = subprocess.run(
                    ["beet", "version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                version = result.stdout.strip()
            except Exception:
                pass

        return {
            "available": available,
            "version": version,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_beets_config_dir(self) -> Path:
        """
        Return a beets config directory under the Swing Music plugin storage.
        Creates a minimal config.yaml if it doesn't exist.
        """
        beets_dir = Paths().plugins_path / "metadata_editor" / "beets"
        beets_dir.mkdir(parents=True, exist_ok=True)

        config_file = beets_dir / "config.yaml"
        if not config_file.exists():
            config_file.write_text(
                "# Beets config managed by Swing Music metadata editor plugin\n"
                "import:\n"
                "  copy: no\n"
                "  move: no\n"
                "  write: yes\n"
                "  timid: no\n"
            )

        return beets_dir

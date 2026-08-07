"""Storage for generated content versions and approvals."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.generation.content_schema import GeneratedContent
from app.storage import json_store

log = logging.getLogger("pmi.generation.content_store")


class ContentVersion:
    """One approved version of generated content."""

    def __init__(
        self,
        session_id: str,
        version: int,
        content: GeneratedContent,
        output_format: str,
        approved_at: Optional[str] = None,
    ):
        self.session_id = session_id
        self.version = version
        self.content = content
        self.output_format = output_format
        self.approved_at = approved_at or datetime.now().isoformat()

    def to_dict(self) -> dict:
        """Serialize to dict."""
        return {
            "session_id": self.session_id,
            "version": self.version,
            "content": self.content.model_dump(),
            "output_format": self.output_format,
            "approved_at": self.approved_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ContentVersion:
        """Load from dict."""
        return cls(
            session_id=data["session_id"],
            version=data["version"],
            content=GeneratedContent(**data["content"]),
            output_format=data["output_format"],
            approved_at=data.get("approved_at"),
        )


def save_approved_content(
    session_id: str,
    content: GeneratedContent,
    output_format: str,
) -> ContentVersion:
    """Save approved content as a version.

    Returns the ContentVersion that was saved.
    """
    # Get next version number
    versions = list_versions(session_id)
    next_version = max([v.version for v in versions], default=0) + 1

    cv = ContentVersion(
        session_id=session_id,
        version=next_version,
        content=content,
        output_format=output_format,
    )

    # Save to disk
    versions_dir = json_store.session_dir(session_id) / "content_versions"
    versions_dir.mkdir(exist_ok=True)

    version_file = versions_dir / f"v{next_version}.json"
    version_file.write_text(json.dumps(cv.to_dict(), indent=2))

    # Update current pointer
    current_file = json_store.session_dir(session_id) / "content_current.json"
    current_file.write_text(json.dumps({
        "version": next_version,
        "output_format": output_format,
        "approved_at": cv.approved_at,
    }, indent=2))

    log.info("saved approved content version %d for session %s", next_version, session_id)
    return cv


def get_current_approved(session_id: str) -> Optional[ContentVersion]:
    """Get the most recently approved content version."""
    current_file = json_store.session_dir(session_id) / "content_current.json"
    if not current_file.exists():
        return None

    try:
        current = json.loads(current_file.read_text())
        version_file = (
            json_store.session_dir(session_id) / "content_versions" / f"v{current['version']}.json"
        )
        if version_file.exists():
            data = json.loads(version_file.read_text())
            return ContentVersion.from_dict(data)
    except Exception as e:
        log.error("failed to load current approved content: %s", e)

    return None


def get_version(session_id: str, version: int) -> Optional[ContentVersion]:
    """Get a specific version by number."""
    version_file = (
        json_store.session_dir(session_id) / "content_versions" / f"v{version}.json"
    )

    if not version_file.exists():
        return None

    try:
        data = json.loads(version_file.read_text())
        return ContentVersion.from_dict(data)
    except Exception as e:
        log.error("failed to load version %d: %s", version, e)
        return None


def list_versions(session_id: str) -> list[ContentVersion]:
    """List all approved versions for a session."""
    versions_dir = json_store.session_dir(session_id) / "content_versions"
    if not versions_dir.exists():
        return []

    versions = []
    for version_file in sorted(versions_dir.glob("v*.json")):
        try:
            data = json.loads(version_file.read_text())
            versions.append(ContentVersion.from_dict(data))
        except Exception as e:
            log.error("failed to load version file %s: %s", version_file, e)

    return sorted(versions, key=lambda v: v.version)


def delete_version(session_id: str, version: int) -> bool:
    """Delete a specific version."""
    version_file = (
        json_store.session_dir(session_id) / "content_versions" / f"v{version}.json"
    )

    if not version_file.exists():
        return False

    try:
        version_file.unlink()
        log.info("deleted version %d for session %s", version, session_id)
        return True
    except Exception as e:
        log.error("failed to delete version: %s", e)
        return False

"""FtM entity bundle exporter.

Exports investigation entities as FtM JSON Lines (`.ftm.json`) —
the standard format for importing entities into Aleph.

Each line is a complete FtM entity dict. The bundle includes:
  - All investigation entities with their properties
  - Provenance metadata as additional properties
  - A manifest file describing the bundle

This allows round-tripping: investigate in Emet → export → import
into Aleph for further analysis or sharing.
"""

from __future__ import annotations

import json
import logging
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class FtMBundleExporter:
    """Export investigation results as FtM-compatible bundles.

    Parameters
    ----------
    include_provenance:
        Attach ``_provenance`` metadata to exported entities.
    include_orphans:
        Include placeholder entities created during graph building.
    """

    def __init__(
        self,
        include_provenance: bool = True,
        include_orphans: bool = False,
    ) -> None:
        self._include_provenance = include_provenance
        self._include_orphans = include_orphans

    def export_jsonl(
        self,
        entities: list[dict[str, Any]],
        path: str | Path,
    ) -> int:
        """Export entities as FtM JSON Lines file.

        Parameters
        ----------
        entities:
            List of FtM entity dicts.
        path:
            Output file path (.ftm.json or .jsonl).

        Returns
        -------
        Number of entities written.
        """
        path = Path(path)
        count = 0

        with open(path, "w") as f:
            for entity in entities:
                if not self._include_orphans and entity.get("_orphan"):
                    continue

                clean = self._clean_entity(entity)
                if clean:
                    f.write(json.dumps(clean, ensure_ascii=False) + "\n")
                    count += 1

        logger.info("Exported %d entities to %s", count, path)
        return count

    def export_zip(
        self,
        entities: list[dict[str, Any]],
        path: str | Path,
        investigation_name: str = "investigation",
    ) -> Path:
        """Export entities as a zip bundle with manifest.

        The zip contains:
          - entities.ftm.json — FtM JSON Lines
          - manifest.json — bundle metadata

        Parameters
        ----------
        entities:
            List of FtM entity dicts.
        path:
            Output zip file path.
        investigation_name:
            Human-readable name for the investigation.

        Returns
        -------
        Path to the created zip file.
        """
        path = Path(path)

        # Build JSONL content
        jsonl_lines: list[str] = []
        schema_counts: dict[str, int] = {}

        for entity in entities:
            if not self._include_orphans and entity.get("_orphan"):
                continue

            clean = self._clean_entity(entity)
            if clean:
                jsonl_lines.append(json.dumps(clean, ensure_ascii=False))
                schema = clean.get("schema", "Unknown")
                schema_counts[schema] = schema_counts.get(schema, 0) + 1

        # Build manifest
        manifest = {
            "format": "ftm-bundle",
            "version": "1.0",
            "generator": "Emet Investigative Framework",
            "investigation": investigation_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "entity_count": len(jsonl_lines),
            "schema_counts": schema_counts,
        }

        # Write zip
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("entities.ftm.json", "\n".join(jsonl_lines) + "\n")
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))

        logger.info(
            "Exported bundle to %s (%d entities, %d bytes)",
            path, len(jsonl_lines), path.stat().st_size,
        )
        return path

    def to_bytes(self, entities: list[dict[str, Any]]) -> bytes:
        """Export entities as FtM JSON Lines bytes (for API responses)."""
        lines: list[str] = []
        for entity in entities:
            if not self._include_orphans and entity.get("_orphan"):
                continue
            clean = self._clean_entity(entity)
            if clean:
                lines.append(json.dumps(clean, ensure_ascii=False))
        return ("\n".join(lines) + "\n").encode("utf-8")

    def _clean_entity(self, entity: dict[str, Any]) -> dict[str, Any] | None:
        """Clean entity for export — remove internal fields, validate."""
        if not entity.get("id") or not entity.get("schema"):
            return None

        clean: dict[str, Any] = {
            "id": entity["id"],
            "schema": entity["schema"],
            "properties": entity.get("properties", {}),
        }

        # Optionally attach provenance
        if self._include_provenance and entity.get("_provenance"):
            provenance = entity["_provenance"]
            props = clean["properties"]
            if provenance.get("source"):
                props.setdefault("sourceUrl", []).append(provenance["source"])
            if provenance.get("retrieved_at"):
                props.setdefault("modifiedAt", []).append(provenance["retrieved_at"])

        return clean

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from pydantic import Field

from ai_pcb.models.common import StrictModel
from ai_pcb.models.schematic import SchematicDesign, SchematicSheet
from ai_pcb.validation.schematic import validate_schematic_design

_NAMESPACE = uuid.UUID("37a3db45-c6bf-51b9-b75f-c6d72c303b5c")


class GeneratedKiCadProject(StrictModel):
    project_file: str
    root_schematic_file: str
    sheet_files: list[str] = Field(min_length=1)
    ir_file: str


def _quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _uuid(key: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, key))


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_") or "sheet"


class KiCadSchematicBackend:
    """Deterministic KiCad s-expression emitter accepting only validated typed IR."""

    def generate(self, design: SchematicDesign, output_directory: Path) -> GeneratedKiCadProject:
        if not isinstance(design, SchematicDesign):
            raise TypeError("KiCad generation requires a validated SchematicDesign instance")
        failures = [
            result for result in validate_schematic_design(design) if result.status == "FAIL"
        ]
        if failures:
            raise ValueError("schematic IR failed deterministic checks")
        output_directory.mkdir(parents=True, exist_ok=True)
        project_stem = _slug(design.design_id)
        project_file = output_directory / f"{project_stem}.kicad_pro"
        root_file = output_directory / f"{project_stem}.kicad_sch"
        ir_file = output_directory / f"{project_stem}.schematic_ir.json"
        project_file.write_text(
            json.dumps(
                {
                    "board": {},
                    "boards": [],
                    "cvpcb": {},
                    "erc": {},
                    "meta": {"filename": f"{project_stem}.kicad_pro", "version": 1},
                    "net_settings": {},
                    "pcbnew": {},
                    "schematic": {},
                    "text_variables": {"SCHEMATIC_IR": ir_file.name},
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        ir_file.write_text(
            design.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        children = [sheet for sheet in design.sheets if sheet.parent_sheet_id is not None]
        root_file.write_text(self._root_schematic(design, children), encoding="utf-8", newline="\n")
        child_paths: list[str] = []
        for sheet in children:
            child_path = output_directory / sheet.file_name
            child_path.write_text(
                self._child_schematic(design, sheet), encoding="utf-8", newline="\n"
            )
            child_paths.append(str(child_path))
        return GeneratedKiCadProject(
            project_file=str(project_file),
            root_schematic_file=str(root_file),
            sheet_files=child_paths,
            ir_file=str(ir_file),
        )

    def _header(self, design: SchematicDesign, key: str) -> list[str]:
        return [
            "(kicad_sch (version 20231120) (generator ai_pcb)",
            f"  (uuid {_uuid(f'{design.design_id}:{key}')})",
            '  (paper "A4")',
            "  (lib_symbols)",
        ]

    def _root_schematic(self, design: SchematicDesign, children: list[SchematicSheet]) -> str:
        lines = self._header(design, "root")
        for index, sheet in enumerate(children):
            x = 25.4 + (index % 2) * 88.9
            y = 25.4 + (index // 2) * 38.1
            sheet_uuid = _uuid(f"{design.design_id}:sheet:{sheet.sheet_id}")
            lines.extend(
                [
                    f"  (sheet (at {x:.1f} {y:.1f}) (size 76.2 25.4)",
                    "    (stroke (width 0) (type default))",
                    "    (fill (color 0 0 0 0.0000))",
                    f"    (uuid {sheet_uuid})",
                    (
                        f'    (property "Sheetname" "{_quote(sheet.name)}" '
                        f"(at {x:.1f} {y - 0.7:.1f} 0)"
                    ),
                    "      (effects (font (size 1.27 1.27)) (justify left bottom)))",
                    (
                        f'    (property "Sheetfile" "{_quote(sheet.file_name)}" '
                        f"(at {x:.1f} {y + 26.1:.1f} 0)"
                    ),
                    "      (effects (font (size 1.27 1.27)) (justify left top)))",
                    "  )",
                ]
            )
        lines.append('  (sheet_instances (path "/" (page "1")))')
        lines.append("  (embedded_fonts no)")
        lines.append(")")
        return "\n".join(lines) + "\n"

    def _child_schematic(self, design: SchematicDesign, sheet: SchematicSheet) -> str:
        lines = self._header(design, sheet.sheet_id)
        components = [item for item in design.components if item.sheet_id == sheet.sheet_id]
        nets = [
            net
            for net in design.nets
            if any(
                endpoint.component_id in {item.component_id for item in components}
                for endpoint in net.endpoints
            )
        ]
        lines.extend(
            [
                f'  (text "{_quote(sheet.name)}" (exclude_from_sim no) (at 20.32 15.24 0)',
                "    (effects (font (size 2.54 2.54) (thickness 0.4)) (justify left bottom)))",
            ]
        )
        for index, component in enumerate(components):
            x = 20.32 + (index % 3) * 58.42
            y = 30.48 + (index // 3) * 8.89
            label = f"{component.reference}  {component.value}"
            lines.extend(
                [
                    f'  (text "{_quote(label)}" (exclude_from_sim no) (at {x:.2f} {y:.2f} 0)',
                    "    (effects (font (size 1.27 1.27)) (justify left bottom)))",
                ]
            )
        net_y = 170.18
        for index, net in enumerate(nets):
            x = 20.32 + (index % 4) * 45.72
            y = net_y + (index // 4) * 5.08
            lines.extend(
                [
                    f'  (label "{_quote(net.name)}" (at {x:.2f} {y:.2f} 0)',
                    "    (effects (font (size 1.27 1.27)) (justify left bottom))",
                    f"    (uuid {_uuid(f'{design.design_id}:{sheet.sheet_id}:net:{net.net_id}')}))",
                ]
            )
        lines.append('  (sheet_instances (path "/" (page "1")))')
        lines.append("  (embedded_fonts no)")
        lines.append(")")
        return "\n".join(lines) + "\n"

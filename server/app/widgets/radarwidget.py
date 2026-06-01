from __future__ import annotations
from pathlib import Path
from typing import Any, Dict

from chatkit.widgets import WidgetTemplate, DynamicWidgetRoot

_TEMPLATE_PATH = Path(__file__).with_name("radar.widget")
_radar_template = WidgetTemplate.from_file(str(_TEMPLATE_PATH))

def build_radar_widget_from_data(data: Dict[str, Any]) -> DynamicWidgetRoot:
    safe = {
        "name": str(data.get("name") or "Radar"),
        "buttonLabel": str(data.get("buttonLabel") or "Open"),
        "html": str(data.get("html") or ""),  # ✅ IMPORTANT
    }
    return _radar_template.build(safe)

"""QGIS tool definitions and dispatcher for the AI agentic loop.

TOOL_DEFINITIONS follows the Anthropic tool-use schema and is passed to the
ClaudeClient so the model knows which actions it can take.

dispatch_tool(name, input) executes the requested tool and returns a JSON
string result that is sent back to the model as a tool_result message.

Call initialize(iface) once from AIAssistantPlugin.initGui() so that tools
that need the QGIS interface (map canvas, layer loading) work correctly.
"""

import json
import threading

from qgis.PyQt.QtCore import QObject, Qt, pyqtSignal, pyqtSlot

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_iface = None
_bridge = None  # _MainThreadBridge instance, created on the main thread


def initialize(iface):
    """Call from AIAssistantPlugin.initGui() to bind the QGIS interface."""
    global _iface, _bridge
    _iface = iface
    _bridge = _MainThreadBridge()


# ---------------------------------------------------------------------------
# Main-thread bridge
# ---------------------------------------------------------------------------

class _MainThreadBridge(QObject):
    """Allows Worker (background) threads to run callables on the Qt main thread.

    Pattern:
      1. Worker calls bridge.call(func, *args) — this blocks the Worker thread.
      2. A queued signal fires on the main thread, which runs func(*args).
      3. The result (or exception) is handed back and the Worker unblocks.
    """

    _request = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._queue = []
        self._request.connect(self._process, Qt.QueuedConnection)

    def call(self, func, *args, **kwargs):
        """Execute func(*args, **kwargs) on the main thread and return the result."""
        event = threading.Event()
        result = {}

        def work():
            try:
                result["value"] = func(*args, **kwargs)
            except Exception as exc:
                result["error"] = exc
            finally:
                event.set()

        with self._lock:
            self._queue.append(work)
        self._request.emit()
        timed_out = not event.wait(timeout=120)
        if timed_out:
            raise TimeoutError(
                "Main-thread operation timed out after 120 s. "
                "The QGIS main thread may be blocked."
            )

        if "error" in result:
            raise result["error"]
        return result.get("value")

    @pyqtSlot()
    def _process(self):
        with self._lock:
            items, self._queue[:] = list(self._queue), []
        for work in items:
            work()


def _run_on_main_thread(func, *args, **kwargs):
    """Run func on the main thread, blocking the caller until complete."""
    if _bridge is None:
        # Fallback: call directly (e.g. during testing or if initialize was skipped)
        return func(*args, **kwargs)
    return _bridge.call(func, *args, **kwargs)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _find_layer_by_name(name: str):
    """Return the first QgsMapLayer whose name matches (case-insensitive)."""
    from qgis.core import QgsProject

    name_lower = name.lower()
    for layer in QgsProject.instance().mapLayers().values():
        if layer.name().lower() == name_lower:
            return layer
    return None


def _layer_type_str(layer) -> str:
    from qgis.core import QgsMapLayer

    return {
        QgsMapLayer.VectorLayer: "Vector",
        QgsMapLayer.RasterLayer: "Raster",
        QgsMapLayer.MeshLayer: "Mesh",
        QgsMapLayer.VectorTileLayer: "VectorTile",
        QgsMapLayer.AnnotationLayer: "Annotation",
        QgsMapLayer.PointCloudLayer: "PointCloud",
    }.get(layer.type(), "Unknown")


def _geom_type_str(layer) -> str:
    from qgis.core import QgsWkbTypes

    return QgsWkbTypes.displayString(layer.wkbType())


# ---------------------------------------------------------------------------
# Individual tool implementations
# ---------------------------------------------------------------------------

def _tool_list_layers(_params: dict) -> str:
    from qgis.core import QgsProject, QgsVectorLayer

    layers = list(QgsProject.instance().mapLayers().values())
    if not layers:
        return "No layers are currently loaded in the QGIS project."

    result = []
    for lyr in layers:
        entry = {
            "name": lyr.name(),
            "type": _layer_type_str(lyr),
            "crs": lyr.crs().authid(),
        }
        if isinstance(lyr, QgsVectorLayer):
            entry["geometry_type"] = _geom_type_str(lyr)
            entry["feature_count"] = lyr.featureCount()
        result.append(entry)

    return json.dumps(result, ensure_ascii=False, indent=2)


def _tool_get_layer_info(params: dict) -> str:
    from qgis.core import QgsVectorLayer, QgsRasterLayer

    layer_name = params.get("layer_name", "")
    try:
        sample_count = min(int(params.get("sample_features", 3)), 10)
    except (TypeError, ValueError):
        sample_count = 3

    lyr = _find_layer_by_name(layer_name)
    if lyr is None:
        return (
            f"Layer '{layer_name}' not found. "
            "Use list_layers to see available layer names."
        )

    info = {
        "name": lyr.name(),
        "type": _layer_type_str(lyr),
        "crs": lyr.crs().authid(),
        "crs_description": lyr.crs().description(),
        "extent": {
            "xmin": round(lyr.extent().xMinimum(), 6),
            "ymin": round(lyr.extent().yMinimum(), 6),
            "xmax": round(lyr.extent().xMaximum(), 6),
            "ymax": round(lyr.extent().yMaximum(), 6),
        },
    }

    if isinstance(lyr, QgsVectorLayer):
        info["geometry_type"] = _geom_type_str(lyr)
        info["feature_count"] = lyr.featureCount()
        info["fields"] = [
            {
                "name": f.name(),
                "type": f.typeName(),
                "alias": f.alias() or "",
            }
            for f in lyr.fields()
        ]
        if sample_count > 0:
            samples = []
            for i, feat in enumerate(lyr.getFeatures()):
                if i >= sample_count:
                    break
                attrs = {}
                for field in lyr.fields():
                    val = feat[field.name()]
                    attrs[field.name()] = str(val) if val is not None else None
                samples.append(attrs)
            info["sample_features"] = samples

    elif isinstance(lyr, QgsRasterLayer):
        info["band_count"] = lyr.bandCount()
        info["width_px"] = lyr.width()
        info["height_px"] = lyr.height()

    return json.dumps(info, ensure_ascii=False, indent=2)


def _tool_get_selected_features(params: dict) -> str:
    from qgis.core import QgsVectorLayer

    layer_name = params.get("layer_name", "")
    lyr = _find_layer_by_name(layer_name)
    if lyr is None:
        return f"Layer '{layer_name}' not found."
    if not isinstance(lyr, QgsVectorLayer):
        return f"Layer '{layer_name}' is not a vector layer."

    selected = lyr.selectedFeatures()
    if not selected:
        return f"No features are currently selected in layer '{layer_name}'."

    result = []
    for feat in selected:
        attrs = {}
        for field in lyr.fields():
            val = feat[field.name()]
            attrs[field.name()] = str(val) if val is not None else None
        result.append(attrs)

    return json.dumps(
        {"layer": layer_name, "selected_count": len(result), "features": result},
        ensure_ascii=False,
        indent=2,
    )


def _tool_search_algorithms(params: dict) -> str:
    from qgis.core import QgsApplication

    keyword = params.get("keyword", "").lower()
    registry = QgsApplication.processingRegistry()
    matches = []
    for alg in registry.algorithms():
        if keyword in alg.id().lower() or keyword in alg.displayName().lower():
            matches.append(
                {
                    "id": alg.id(),
                    "name": alg.displayName(),
                    "provider": alg.provider().name() if alg.provider() else "unknown",
                    "group": alg.group(),
                }
            )

    if not matches:
        return f"No algorithms found matching '{keyword}'."
    # Cap results to avoid overwhelming the context window
    MAX_SEARCH_RESULTS = 30
    return json.dumps(matches[:MAX_SEARCH_RESULTS], ensure_ascii=False, indent=2)


def _tool_get_algorithm_info(params: dict) -> str:
    from qgis.core import QgsApplication

    alg_id = params.get("algorithm_id", "")
    alg = QgsApplication.processingRegistry().algorithmById(alg_id)
    if alg is None:
        return (
            f"Algorithm '{alg_id}' not found. "
            "Use search_processing_algorithms to find valid IDs."
        )

    param_defs = [
        {
            "name": p.name(),
            "type": type(p).__name__,
            "description": p.description(),
            "optional": bool(p.flags() & p.FlagOptional),
            "default": (
                str(p.defaultValue()) if p.defaultValue() is not None else None
            ),
        }
        for p in alg.parameterDefinitions()
    ]

    output_defs = [
        {
            "name": o.name(),
            "type": type(o).__name__,
            "description": o.description(),
        }
        for o in alg.outputDefinitions()
    ]

    return json.dumps(
        {
            "id": alg.id(),
            "name": alg.displayName(),
            "provider": alg.provider().name() if alg.provider() else "unknown",
            "group": alg.group(),
            "description": alg.shortDescription() or alg.displayName(),
            "parameters": param_defs,
            "outputs": output_defs,
        },
        ensure_ascii=False,
        indent=2,
    )


def _do_run_algorithm(params: dict) -> str:
    """Inner implementation — always called on the main thread."""
    import processing
    from qgis.core import (
        QgsApplication,
        QgsProcessingFeedback,
        QgsProcessingOutputMultipleLayers,
        QgsProcessingOutputRasterLayer,
        QgsProcessingOutputVectorLayer,
        QgsProject,
        QgsRasterLayer,
        QgsVectorLayer,
    )

    alg_id = params.get("algorithm_id", "")
    alg_params = dict(params.get("parameters", {}))
    load_result = bool(params.get("load_result", True))

    # Resolve layer name strings to layer objects
    for key, value in list(alg_params.items()):
        if isinstance(value, str):
            layer = _find_layer_by_name(value)
            if layer is not None:
                alg_params[key] = layer

    alg = QgsApplication.processingRegistry().algorithmById(alg_id)
    if alg is None:
        return json.dumps(
            {"status": "error", "message": f"Algorithm '{alg_id}' not found."}
        )

    # Auto-set TEMPORARY_OUTPUT for unspecified vector/raster outputs
    for out in alg.outputDefinitions():
        if isinstance(
            out,
            (
                QgsProcessingOutputVectorLayer,
                QgsProcessingOutputRasterLayer,
                QgsProcessingOutputMultipleLayers,
            ),
        ):
            if out.name() not in alg_params:
                alg_params[out.name()] = "TEMPORARY_OUTPUT"

    feedback = QgsProcessingFeedback()
    try:
        result = processing.run(alg_id, alg_params, feedback=feedback)
    except Exception as exc:
        return json.dumps({"status": "error", "message": str(exc)})

    loaded_layers = []
    if load_result:
        for key, value in result.items():
            if isinstance(value, (QgsVectorLayer, QgsRasterLayer)) and value.isValid():
                QgsProject.instance().addMapLayer(value)
                loaded_layers.append(value.name())
            elif isinstance(value, str) and value and key not in ("STDOUT", "STDERR"):
                vec = QgsVectorLayer(value, key, "ogr")
                if vec.isValid():
                    QgsProject.instance().addMapLayer(vec)
                    loaded_layers.append(vec.name())

    serialized = {}
    for k, v in result.items():
        if hasattr(v, "name"):
            serialized[k] = f"[Layer: {v.name()}]"
        elif v is not None:
            serialized[k] = str(v)

    return json.dumps(
        {
            "status": "success",
            "algorithm": alg_id,
            "outputs": serialized,
            "loaded_layers": loaded_layers,
        },
        ensure_ascii=False,
        indent=2,
    )


def _tool_run_algorithm(params: dict) -> str:
    # processing.run() and addMapLayer() must run on the main thread
    return _run_on_main_thread(_do_run_algorithm, params)


def _tool_get_map_extent(_params: dict) -> str:
    if _iface is None:
        return "iface not initialised — call qgis_tools.initialize(iface) first."

    canvas = _iface.mapCanvas()
    extent = canvas.extent()
    crs = canvas.mapSettings().destinationCrs()

    return json.dumps(
        {
            "extent": {
                "xmin": round(extent.xMinimum(), 6),
                "ymin": round(extent.yMinimum(), 6),
                "xmax": round(extent.xMaximum(), 6),
                "ymax": round(extent.yMaximum(), 6),
            },
            "crs": crs.authid(),
            "scale": round(canvas.scale(), 2),
        },
        ensure_ascii=False,
        indent=2,
    )


def _tool_load_vector_layer(params: dict) -> str:
    import os
    from qgis.core import QgsProject, QgsVectorLayer

    file_path = params.get("file_path", "")
    layer_name = params.get("layer_name") or os.path.splitext(
        os.path.basename(file_path)
    )[0]

    def _add():
        lyr = QgsVectorLayer(file_path, layer_name, "ogr")
        if not lyr.isValid():
            raise ValueError(f"Cannot open vector file: {file_path}")
        QgsProject.instance().addMapLayer(lyr)
        return {
            "layer_name": lyr.name(),
            "feature_count": lyr.featureCount(),
            "crs": lyr.crs().authid(),
        }

    try:
        info = _run_on_main_thread(_add)
        return json.dumps({"status": "success", **info}, ensure_ascii=False, indent=2)
    except Exception as exc:
        return json.dumps({"status": "error", "message": str(exc)})


def _tool_load_raster_layer(params: dict) -> str:
    import os
    from qgis.core import QgsProject, QgsRasterLayer

    file_path = params.get("file_path", "")
    layer_name = params.get("layer_name") or os.path.splitext(
        os.path.basename(file_path)
    )[0]

    def _add():
        lyr = QgsRasterLayer(file_path, layer_name)
        if not lyr.isValid():
            raise ValueError(f"Cannot open raster file: {file_path}")
        QgsProject.instance().addMapLayer(lyr)
        return {
            "layer_name": lyr.name(),
            "bands": lyr.bandCount(),
            "crs": lyr.crs().authid(),
        }

    try:
        info = _run_on_main_thread(_add)
        return json.dumps({"status": "success", **info}, ensure_ascii=False, indent=2)
    except Exception as exc:
        return json.dumps({"status": "error", "message": str(exc)})


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_TOOLS = {
    "list_layers": _tool_list_layers,
    "get_layer_info": _tool_get_layer_info,
    "get_selected_features": _tool_get_selected_features,
    "search_processing_algorithms": _tool_search_algorithms,
    "get_algorithm_info": _tool_get_algorithm_info,
    "run_algorithm": _tool_run_algorithm,
    "get_map_extent": _tool_get_map_extent,
    "load_vector_layer": _tool_load_vector_layer,
    "load_raster_layer": _tool_load_raster_layer,
}


def dispatch_tool(tool_name: str, tool_input: dict) -> str:
    """Execute the named tool and return a JSON string result.

    Raises ValueError for unknown tool names; individual tools raise
    on internal errors (callers should catch and format as tool_result errors).
    """
    if tool_name not in _TOOLS:
        raise ValueError(
            f"Unknown tool: '{tool_name}'. Available: {sorted(_TOOLS)}"
        )
    return _TOOLS[tool_name](tool_input)


# ---------------------------------------------------------------------------
# Tool definitions — Anthropic schema
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "name": "list_layers",
        "description": (
            "List all layers currently loaded in the QGIS project. "
            "Returns the name, type (Vector/Raster/…), CRS, geometry type, "
            "and feature count for every layer."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_layer_info",
        "description": (
            "Get detailed information about a specific layer: all field names "
            "and types, feature count, bounding extent, CRS, and optional "
            "sample feature attributes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "layer_name": {
                    "type": "string",
                    "description": (
                        "Exact name of the layer as returned by list_layers."
                    ),
                },
                "sample_features": {
                    "type": "integer",
                    "description": "Number of sample features to return (0–10). Default 3.",
                },
            },
            "required": ["layer_name"],
        },
    },
    {
        "name": "get_selected_features",
        "description": (
            "Return the attribute values of all currently selected features "
            "in a vector layer."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "layer_name": {
                    "type": "string",
                    "description": "Name of the vector layer.",
                }
            },
            "required": ["layer_name"],
        },
    },
    {
        "name": "search_processing_algorithms",
        "description": (
            "Search the QGIS Processing toolbox for algorithms matching a "
            "keyword. Returns up to 30 results with algorithm ID, display "
            "name, provider, and group."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": (
                        "Search term, e.g. 'buffer', 'clip', 'dissolve', 'reproject'."
                    ),
                }
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "get_algorithm_info",
        "description": (
            "Get the full parameter and output definitions for a specific QGIS "
            "processing algorithm. Call this before run_algorithm to understand "
            "the required inputs and their types."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "algorithm_id": {
                    "type": "string",
                    "description": "Algorithm ID, e.g. 'native:buffer' or 'qgis:dissolve'.",
                }
            },
            "required": ["algorithm_id"],
        },
    },
    {
        "name": "run_algorithm",
        "description": (
            "Execute a QGIS processing algorithm. "
            "Use layer names (strings) for layer parameters — they are "
            "resolved to layer objects automatically. "
            "Output layers are added to the project when load_result is true."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "algorithm_id": {
                    "type": "string",
                    "description": "Algorithm ID to run, e.g. 'native:buffer'.",
                },
                "parameters": {
                    "type": "object",
                    "description": (
                        "Key-value pairs matching the algorithm's parameter names. "
                        "Pass layer names (strings) for layer inputs; "
                        "numbers for numeric parameters."
                    ),
                },
                "load_result": {
                    "type": "boolean",
                    "description": (
                        "Whether to add output layers to the QGIS project. Default: true."
                    ),
                },
            },
            "required": ["algorithm_id", "parameters"],
        },
    },
    {
        "name": "get_map_extent",
        "description": "Return the current map canvas extent and map scale.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "load_vector_layer",
        "description": (
            "Load a vector file (Shapefile, GeoJSON, GeoPackage, …) into the "
            "QGIS project."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the vector file.",
                },
                "layer_name": {
                    "type": "string",
                    "description": "Optional display name for the layer.",
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "load_raster_layer",
        "description": (
            "Load a raster file (GeoTIFF, …) into the QGIS project."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the raster file.",
                },
                "layer_name": {
                    "type": "string",
                    "description": "Optional display name for the layer.",
                },
            },
            "required": ["file_path"],
        },
    },
]

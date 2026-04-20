import json
import processing
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsRasterLayer,
    QgsProcessingFeedback
)
from qgis.utils import iface


# ── Tool definitions sent to Claude API ──────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "list_layers",
        "description": "Zwraca listę wszystkich warstw załadowanych w projekcie QGIS wraz z ich typem, CRS i liczbą obiektów.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "get_layer_fields",
        "description": "Zwraca schemat atrybutów (nazwy pól, typy) dla podanej warstwy wektorowej.",
        "input_schema": {
            "type": "object",
            "properties": {
                "layer_name": {"type": "string", "description": "Nazwa warstwy w projekcie QGIS"}
            },
            "required": ["layer_name"]
        }
    },
    {
        "name": "get_selected_features",
        "description": "Zwraca atrybuty zaznaczonych obiektów z podanej warstwy (max 50 obiektów).",
        "input_schema": {
            "type": "object",
            "properties": {
                "layer_name": {"type": "string", "description": "Nazwa warstwy w projekcie QGIS"}
            },
            "required": ["layer_name"]
        }
    },
    {
        "name": "get_feature_sample",
        "description": "Zwraca próbkę obiektów z warstwy (domyślnie 10) do analizy atrybutów.",
        "input_schema": {
            "type": "object",
            "properties": {
                "layer_name": {"type": "string"},
                "limit": {"type": "integer", "description": "Liczba obiektów do zwrócenia (domyślnie 10)"}
            },
            "required": ["layer_name"]
        }
    },
    {
        "name": "search_processing_algorithms",
        "description": "Wyszukuje algorytmy QGIS Processing po słowie kluczowym. Używaj tego zanim wywołasz run_processing_algorithm.",
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "Słowo kluczowe np. 'buffer', 'clip', 'dissolve'"}
            },
            "required": ["keyword"]
        }
    },
    {
        "name": "get_algorithm_info",
        "description": "Zwraca szczegółowy opis algorytmu QGIS Processing: parametry i ich typy.",
        "input_schema": {
            "type": "object",
            "properties": {
                "algorithm_id": {"type": "string", "description": "Identyfikator algorytmu np. 'native:buffer'"}
            },
            "required": ["algorithm_id"]
        }
    },
    {
        "name": "run_processing_algorithm",
        "description": "Uruchamia algorytm QGIS Processing z podanymi parametrami. Wynik jest dodawany jako nowa warstwa.",
        "input_schema": {
            "type": "object",
            "properties": {
                "algorithm_id": {"type": "string", "description": "Identyfikator algorytmu np. 'native:buffer'"},
                "parameters": {"type": "object", "description": "Parametry algorytmu. Dla INPUT podaj nazwę warstwy. OUTPUT ustaw na 'memory:'."}
            },
            "required": ["algorithm_id", "parameters"]
        }
    },
    {
        "name": "load_layer",
        "description": "Wczytuje plik warstwy do projektu QGIS. Obsługuje .shp, .gpkg, .geojson, .tif i inne.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Pełna ścieżka do pliku"},
                "layer_name": {"type": "string", "description": "Opcjonalna nazwa dla warstwy"}
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "execute_python_code",
        "description": "Wykonuje kod Python/PyQGIS bezpośrednio w QGIS. Używaj gdy inne narzędzia nie wystarczają.",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Kod Python do wykonania"}
            },
            "required": ["code"]
        }
    }
]


# ── Tool implementations ──────────────────────────────────────────────────────

def _get_layer_by_name(name: str):
    layers = QgsProject.instance().mapLayersByName(name)
    if not layers:
        raise Exception(f"Nie znaleziono warstwy o nazwie: '{name}'")
    return layers[0]


def list_layers() -> dict:
    layers = QgsProject.instance().mapLayers().values()
    result = []
    for lyr in layers:
        info = {
            "name": lyr.name(),
            "type": "wektorowa" if lyr.type() == 0 else "rastrowa",
            "crs": lyr.crs().authid(),
        }
        if lyr.type() == 0:
            info["feature_count"] = lyr.featureCount()
            info["geometry_type"] = ["Punkt", "Linia", "Poligon", "Brak", "Kolekcja"][lyr.geometryType()]
        result.append(info)
    return {"layers": result, "count": len(result)}


def get_layer_fields(layer_name: str) -> dict:
    layer = _get_layer_by_name(layer_name)
    fields = []
    for field in layer.fields():
        fields.append({
            "name": field.name(),
            "type": field.typeName(),
            "length": field.length()
        })
    return {"layer": layer_name, "fields": fields}


def get_selected_features(layer_name: str) -> dict:
    layer = _get_layer_by_name(layer_name)
    selected = layer.selectedFeatures()
    if not selected:
        return {"layer": layer_name, "selected_count": 0, "message": "Brak zaznaczonych obiektów"}
    field_names = [f.name() for f in layer.fields()]
    features = []
    for feat in selected[:50]:
        attrs = {}
        for name, val in zip(field_names, feat.attributes()):
            attrs[name] = str(val) if val is not None else None
        features.append(attrs)
    return {"layer": layer_name, "selected_count": len(selected), "features": features}


def get_feature_sample(layer_name: str, limit: int = 10) -> dict:
    layer = _get_layer_by_name(layer_name)
    field_names = [f.name() for f in layer.fields()]
    features = []
    for i, feat in enumerate(layer.getFeatures()):
        if i >= limit:
            break
        attrs = {}
        for name, val in zip(field_names, feat.attributes()):
            attrs[name] = str(val) if val is not None else None
        features.append(attrs)
    return {"layer": layer_name, "sample_size": len(features), "total_features": layer.featureCount(), "features": features}


def search_processing_algorithms(keyword: str) -> dict:
    from qgis.core import QgsApplication
    reg = QgsApplication.processingRegistry()
    results = []
    keyword_lower = keyword.lower()
    for alg in reg.algorithms():
        if keyword_lower in alg.name().lower() or keyword_lower in alg.displayName().lower():
            results.append({
                "id": alg.id(),
                "name": alg.displayName(),
                "group": alg.group()
            })
    return {"keyword": keyword, "results": results[:20], "total_found": len(results)}


def get_algorithm_info(algorithm_id: str) -> dict:
    from qgis.core import QgsApplication
    reg = QgsApplication.processingRegistry()
    alg = reg.algorithmById(algorithm_id)
    if not alg:
        raise Exception(f"Nie znaleziono algorytmu: {algorithm_id}")
    params = []
    for p in alg.parameterDefinitions():
        params.append({
            "name": p.name(),
            "description": p.description(),
            "type": p.__class__.__name__,
            "optional": bool(p.flags() & p.FlagOptional)
        })
    outputs = []
    for o in alg.outputDefinitions():
        outputs.append({"name": o.name(), "description": o.description()})
    return {"id": algorithm_id, "name": alg.displayName(), "parameters": params, "outputs": outputs}


def run_processing_algorithm(algorithm_id: str, parameters: dict) -> dict:
    resolved = {}
    for key, val in parameters.items():
        if isinstance(val, str) and val != "memory:":
            layers = QgsProject.instance().mapLayersByName(val)
            resolved[key] = layers[0] if layers else val
        else:
            resolved[key] = val

    if "OUTPUT" not in resolved:
        resolved["OUTPUT"] = "memory:"

    feedback = QgsProcessingFeedback()
    result = processing.run(algorithm_id, resolved, feedback=feedback)

    output_layer = result.get("OUTPUT")
    layer_name = None
    if output_layer and hasattr(output_layer, "name"):
        layer_name = f"Wynik_{algorithm_id.split(':')[-1]}"
        output_layer.setName(layer_name)
        QgsProject.instance().addMapLayer(output_layer)

    return {"algorithm": algorithm_id, "success": True, "output_layer": layer_name, "result_keys": list(result.keys())}


def load_layer(file_path: str, layer_name: str = None) -> dict:
    name = layer_name or file_path.replace("\\", "/").split("/")[-1]
    ext = file_path.lower().split(".")[-1]

    if ext in ["tif", "tiff", "asc", "img"]:
        layer = QgsRasterLayer(file_path, name)
    else:
        layer = QgsVectorLayer(file_path, name, "ogr")

    if not layer.isValid():
        raise Exception(f"Nie można wczytać pliku: {file_path}")

    QgsProject.instance().addMapLayer(layer)
    result = {
        "loaded": True,
        "name": name,
        "crs": layer.crs().authid(),
        "type": "rastrowa" if ext in ["tif", "tiff", "asc", "img"] else "wektorowa"
    }
    if hasattr(layer, "featureCount"):
        result["feature_count"] = layer.featureCount()
    return result


def execute_python_code(code: str) -> dict:
    import io, sys
    namespace = {
        "iface": iface,
        "QgsProject": QgsProject,
        "processing": processing,
        "print": print
    }
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        exec(code, namespace)
        output = sys.stdout.getvalue()
    finally:
        sys.stdout = old_stdout
    return {"executed": True, "output": output or "Kod wykonany (brak wyjscia)"}


# ── Dispatcher ────────────────────────────────────────────────────────────────

def dispatch_tool(tool_name: str, tool_input: dict) -> str:
    tools_map = {
        "list_layers":                  lambda: list_layers(),
        "get_layer_fields":             lambda: get_layer_fields(**tool_input),
        "get_selected_features":        lambda: get_selected_features(**tool_input),
        "get_feature_sample":           lambda: get_feature_sample(**tool_input),
        "search_processing_algorithms": lambda: search_processing_algorithms(**tool_input),
        "get_algorithm_info":           lambda: get_algorithm_info(**tool_input),
        "run_processing_algorithm":     lambda: run_processing_algorithm(**tool_input),
        "load_layer":                   lambda: load_layer(**tool_input),
        "execute_python_code":          lambda: execute_python_code(**tool_input),
    }
    if tool_name not in tools_map:
        raise Exception(f"Nieznane narzedzie: {tool_name}")
    result = tools_map[tool_name]()
    return json.dumps(result, ensure_ascii=False, indent=2)

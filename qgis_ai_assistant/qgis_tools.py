import builtins as python_builtins
import contextlib
import copy
import io
import json
import os
import shutil
import time

from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsExpression,
    QgsExpressionContext,
    QgsExpressionContextUtils,
    QgsFeatureRequest,
    QgsField,
    QgsMessageLog,
    QgsProject,
    QgsRasterLayer,
    QgsUnitTypes,
    QgsVectorLayer,
    QgsWkbTypes,
)


def make_tool_definition(name, description, properties=None, required=None):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": required or [],
            },
        },
    }


class QGISToolExecutor:
    SAFE_ALGORITHMS = {
        "native:buffer",
        "native:clip",
        "native:dissolve",
        "native:fixgeometries",
        "native:intersection",
        "native:reprojectlayer",
    }

    LAYER_PARAMETER_KEYS = {
        "INPUT",
        "INPUT_2",
        "LAYER",
        "LAYERS",
        "MASK",
        "OVERLAY",
        "SOURCE",
    }

    CRS_PARAMETER_KEYS = {
        "CRS",
        "DEST_CRS",
        "DESTINATION_CRS",
        "SOURCE_CRS",
        "TARGET_CRS",
    }

    TOOL_DEFINITIONS = [
        make_tool_definition(
            "get_project_info",
            (
                "Zwraca podstawowe informacje o aktualnym projekcie QGIS: sciezke, "
                "nazwe, CRS projektu, jednostki mapy, extent mapy, liste warstw "
                "oraz nazwe aktywnej warstwy."
            ),
        ),
        make_tool_definition(
            "list_layers",
            (
                "Zwraca liste wszystkich warstw w projekcie wraz z podstawowymi "
                "metadanymi: nazwa, typ, CRS, zrodlo danych i liczba obiektow."
            ),
        ),
        make_tool_definition(
            "get_active_layer_info",
            (
                "Zwraca szczegolowe informacje o aktywnej warstwie: nazwa, typ, "
                "geometria, CRS, pola, liczba obiektow, zrodlo danych i selekcja."
            ),
        ),
        make_tool_definition(
            "get_selected_features_info",
            (
                "Zwraca informacje o zaznaczonych obiektach w aktywnej albo wskazanej "
                "warstwie: liczbe rekordow, probke atrybutow i bbox zaznaczenia."
            ),
            {
                "layer_name": {
                    "type": "string",
                    "description": "Opcjonalna nazwa warstwy wektorowej.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Liczba rekordow do zwrocenia, maksymalnie 100.",
                    "default": 20,
                },
            },
        ),
        make_tool_definition(
            "add_vector_layer",
            "Dodaje do projektu warstwe wektorowa z podanej sciezki albo zrodla danych.",
            {
                "source": {
                    "type": "string",
                    "description": "Sciezka do pliku albo datasource URI.",
                },
                "layer_name": {
                    "type": "string",
                    "description": "Opcjonalna nazwa warstwy w projekcie.",
                },
                "provider_name": {
                    "type": "string",
                    "description": "Provider warstwy, domyslnie ogr.",
                    "default": "ogr",
                },
                "make_active": {
                    "type": "boolean",
                    "description": "Czy ustawic warstwe jako aktywna po dodaniu.",
                    "default": True,
                },
            },
            ["source"],
        ),
        make_tool_definition(
            "add_raster_layer",
            "Dodaje do projektu warstwe rastrowa z podanej sciezki albo zrodla danych.",
            {
                "source": {
                    "type": "string",
                    "description": "Sciezka do pliku albo datasource URI.",
                },
                "layer_name": {
                    "type": "string",
                    "description": "Opcjonalna nazwa warstwy w projekcie.",
                },
                "make_active": {
                    "type": "boolean",
                    "description": "Czy ustawic warstwe jako aktywna po dodaniu.",
                    "default": True,
                },
            },
            ["source"],
        ),
        make_tool_definition(
            "set_active_layer",
            "Ustawia wskazana warstwe jako aktywna warstwe w interfejsie QGIS.",
            {
                "layer_name": {
                    "type": "string",
                    "description": "Nazwa warstwy, ktora ma zostac aktywowana.",
                }
            },
            ["layer_name"],
        ),
        make_tool_definition(
            "save_layer_as",
            (
                "Zapisuje wskazana warstwe do nowego pliku. Dla warstw wektorowych "
                "moze tez wykonac reprojekcje podczas zapisu."
            ),
            {
                "layer_name": {
                    "type": "string",
                    "description": "Nazwa warstwy do zapisu.",
                },
                "output_path": {
                    "type": "string",
                    "description": "Docelowa sciezka pliku wynikowego.",
                },
                "target_crs": {
                    "type": "string",
                    "description": "Opcjonalny docelowy CRS, np. EPSG:2180.",
                },
                "add_to_project": {
                    "type": "boolean",
                    "description": "Czy dodac zapisany wynik z powrotem do projektu.",
                    "default": False,
                },
                "output_name": {
                    "type": "string",
                    "description": "Opcjonalna nazwa warstwy przy ponownym dodaniu.",
                },
            },
            ["layer_name", "output_path"],
        ),
        make_tool_definition(
            "get_fields",
            "Zwraca liste pol atrybutowych wskazanej warstwy wraz z typami danych.",
            {
                "layer_name": {
                    "type": "string",
                    "description": "Nazwa warstwy wektorowej.",
                }
            },
            ["layer_name"],
        ),
        make_tool_definition(
            "calculate_field",
            (
                "Oblicza albo aktualizuje wartosci pola atrybutowego na podstawie "
                "wyrazenia QGIS."
            ),
            {
                "layer_name": {
                    "type": "string",
                    "description": "Nazwa warstwy wektorowej.",
                },
                "field_name": {
                    "type": "string",
                    "description": "Nazwa pola do obliczenia.",
                },
                "expression": {
                    "type": "string",
                    "description": "Wyrazenie QGIS uzywane do obliczen.",
                },
                "create_if_missing": {
                    "type": "boolean",
                    "description": "Czy utworzyc pole, jesli nie istnieje.",
                    "default": False,
                },
                "field_type": {
                    "type": "string",
                    "description": "Typ nowego pola przy create_if_missing, np. string, int, double.",
                    "default": "string",
                },
                "field_length": {
                    "type": "integer",
                    "description": "Dlugosc nowego pola tekstowego.",
                    "default": 255,
                },
                "field_precision": {
                    "type": "integer",
                    "description": "Precyzja nowego pola liczbowego.",
                    "default": 0,
                },
                "only_selected": {
                    "type": "boolean",
                    "description": "Czy aktualizowac tylko zaznaczone obiekty.",
                    "default": False,
                },
            },
            ["layer_name", "field_name", "expression"],
        ),
        make_tool_definition(
            "select_by_expression",
            "Zaznacza obiekty warstwy na podstawie wyrazenia QGIS.",
            {
                "layer_name": {
                    "type": "string",
                    "description": "Nazwa warstwy wektorowej.",
                },
                "expression": {
                    "type": "string",
                    "description": "Wyrazenie QGIS do selekcji.",
                },
                "selection_mode": {
                    "type": "string",
                    "description": "replace, add, remove albo intersect.",
                    "default": "replace",
                },
            },
            ["layer_name", "expression"],
        ),
        make_tool_definition(
            "filter_layer",
            (
                "Ustawia filtr warstwy przez subset string, ograniczajac widoczne rekordy."
            ),
            {
                "layer_name": {
                    "type": "string",
                    "description": "Nazwa warstwy wektorowej.",
                },
                "expression": {
                    "type": "string",
                    "description": "Wyrazenie filtra.",
                },
            },
            ["layer_name", "expression"],
        ),
        make_tool_definition(
            "get_unique_values",
            "Zwraca unikalne wartosci z wybranego pola atrybutowego.",
            {
                "layer_name": {
                    "type": "string",
                    "description": "Nazwa warstwy wektorowej.",
                },
                "field_name": {
                    "type": "string",
                    "description": "Nazwa pola atrybutowego.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maksymalna liczba wartosci w odpowiedzi.",
                    "default": 100,
                },
            },
            ["layer_name", "field_name"],
        ),
        make_tool_definition(
            "summarize_field",
            "Zwraca podstawowe statystyki pola atrybutowego.",
            {
                "layer_name": {
                    "type": "string",
                    "description": "Nazwa warstwy wektorowej.",
                },
                "field_name": {
                    "type": "string",
                    "description": "Nazwa pola atrybutowego.",
                },
                "only_selected": {
                    "type": "boolean",
                    "description": "Czy analizowac tylko zaznaczone obiekty.",
                    "default": False,
                },
            },
            ["layer_name", "field_name"],
        ),
        make_tool_definition(
            "fix_geometries",
            "Tworzy nowa warstwe z naprawiona geometria obiektow.",
            {
                "layer_name": {
                    "type": "string",
                    "description": "Nazwa warstwy wektorowej.",
                },
                "output_name": {
                    "type": "string",
                    "description": "Opcjonalna nazwa nowej warstwy wynikowej.",
                },
            },
            ["layer_name"],
        ),
        make_tool_definition(
            "buffer",
            "Tworzy bufor wokol obiektow warstwy wektorowej.",
            {
                "layer_name": {
                    "type": "string",
                    "description": "Nazwa warstwy wektorowej.",
                },
                "distance": {
                    "type": "number",
                    "description": "Odleglosc bufora w jednostkach warstwy.",
                },
                "segments": {
                    "type": "integer",
                    "description": "Liczba segmentow zaokraglenia bufora.",
                    "default": 8,
                },
                "dissolve": {
                    "type": "boolean",
                    "description": "Czy scalic bufory.",
                    "default": False,
                },
                "output_name": {
                    "type": "string",
                    "description": "Opcjonalna nazwa nowej warstwy wynikowej.",
                },
            },
            ["layer_name", "distance"],
        ),
        make_tool_definition(
            "clip",
            "Przycina warstwe wejsciowa do zasiegu geometrii warstwy nakladajacej.",
            {
                "input_layer_name": {
                    "type": "string",
                    "description": "Nazwa warstwy wejsciowej.",
                },
                "overlay_layer_name": {
                    "type": "string",
                    "description": "Nazwa warstwy nakladajacej.",
                },
                "output_name": {
                    "type": "string",
                    "description": "Opcjonalna nazwa nowej warstwy wynikowej.",
                },
            },
            ["input_layer_name", "overlay_layer_name"],
        ),
        make_tool_definition(
            "intersection",
            "Tworzy warstwe bedaca przecieciem dwoch warstw wektorowych.",
            {
                "input_layer_name": {
                    "type": "string",
                    "description": "Nazwa warstwy wejsciowej.",
                },
                "overlay_layer_name": {
                    "type": "string",
                    "description": "Nazwa warstwy nakladajacej.",
                },
                "output_name": {
                    "type": "string",
                    "description": "Opcjonalna nazwa nowej warstwy wynikowej.",
                },
            },
            ["input_layer_name", "overlay_layer_name"],
        ),
        make_tool_definition(
            "dissolve",
            "Scala obiekty warstwy wedlug wskazanego pola albo bez pola.",
            {
                "layer_name": {
                    "type": "string",
                    "description": "Nazwa warstwy wektorowej.",
                },
                "dissolve_field": {
                    "type": "string",
                    "description": "Opcjonalne pole grupowania.",
                },
                "separate_disjoint": {
                    "type": "boolean",
                    "description": "Czy zachowac rozlaczne czesci oddzielnie.",
                    "default": False,
                },
                "output_name": {
                    "type": "string",
                    "description": "Opcjonalna nazwa nowej warstwy wynikowej.",
                },
            },
            ["layer_name"],
        ),
        make_tool_definition(
            "reproject_layer",
            "Tworzy nowa warstwe przeliczona do wskazanego CRS.",
            {
                "layer_name": {
                    "type": "string",
                    "description": "Nazwa warstwy wektorowej.",
                },
                "target_crs": {
                    "type": "string",
                    "description": "Docelowy CRS, np. EPSG:2180.",
                },
                "output_name": {
                    "type": "string",
                    "description": "Opcjonalna nazwa nowej warstwy wynikowej.",
                },
            },
            ["layer_name", "target_crs"],
        ),
        make_tool_definition(
            "get_project_crs",
            "Zwraca CRS aktualnego projektu QGIS.",
        ),
        make_tool_definition(
            "get_layer_crs",
            "Zwraca CRS wskazanej warstwy.",
            {
                "layer_name": {
                    "type": "string",
                    "description": "Nazwa warstwy.",
                }
            },
            ["layer_name"],
        ),
        make_tool_definition(
            "set_project_crs",
            "Ustawia CRS projektu QGIS.",
            {
                "target_crs": {
                    "type": "string",
                    "description": "Docelowy CRS projektu, np. EPSG:3857.",
                }
            },
            ["target_crs"],
        ),
        make_tool_definition(
            "zoom_to_layer",
            "Ustawia widok mapy tak, aby objac zasieg wskazanej warstwy.",
            {
                "layer_name": {
                    "type": "string",
                    "description": "Nazwa warstwy.",
                }
            },
            ["layer_name"],
        ),
        make_tool_definition(
            "zoom_to_selection",
            "Ustawia widok mapy tak, aby objac zaznaczone obiekty warstwy.",
            {
                "layer_name": {
                    "type": "string",
                    "description": "Opcjonalna nazwa warstwy wektorowej.",
                }
            },
        ),
        make_tool_definition(
            "refresh_canvas",
            "Odswieza widok mapy QGIS po zmianach w danych, stylu albo widoku.",
        ),
        make_tool_definition(
            "run_safe_algorithm",
            (
                "Uruchamia algorytm QGIS Processing tylko z dozwolonej whitelisty "
                "bezpiecznych algorytmow."
            ),
            {
                "algorithm_id": {
                    "type": "string",
                    "description": "ID algorytmu Processing, np. native:buffer.",
                },
                "parameters": {
                    "type": "object",
                    "description": "Slownik parametrow algorytmu.",
                },
                "output_name": {
                    "type": "string",
                    "description": "Opcjonalna nazwa warstwy wynikowej.",
                },
            },
            ["algorithm_id", "parameters"],
        ),
        make_tool_definition(
            "generate_pyqgis_code",
            (
                "Generuje szkic kodu PyQGIS dla opisanego zadania na podstawie "
                "kontekstu projektu, ale go nie uruchamia."
            ),
            {
                "task_description": {
                    "type": "string",
                    "description": "Opis zadania, dla ktorego ma powstac kod.",
                },
                "layer_name": {
                    "type": "string",
                    "description": "Opcjonalna nazwa warstwy, na ktorej ma pracowac kod.",
                },
                "include_project_context": {
                    "type": "boolean",
                    "description": "Czy dolaczyc komentarze z kontekstem projektu.",
                    "default": True,
                },
            },
            ["task_description"],
        ),
        make_tool_definition(
            "insert_into_pyqgis_console",
            (
                "Wstawia wygenerowany kod do konsoli PyQGIS bez automatycznego "
                "uruchamiania. W razie problemu kopiuje kod do schowka."
            ),
            {
                "code": {
                    "type": "string",
                    "description": "Kod, ktory ma zostac wstawiony do konsoli.",
                }
            },
            ["code"],
        ),
        make_tool_definition(
            "run_pyqgis_code",
            (
                "Uruchamia kod PyQGIS w kontrolowanym kontekscie QGIS i zwraca "
                "wynik wykonania wraz ze stdout i stderr."
            ),
            {
                "code": {
                    "type": "string",
                    "description": "Kod PyQGIS do wykonania.",
                },
                "action_label": {
                    "type": "string",
                    "description": "Opcjonalny opis wykonywanej operacji.",
                },
            },
            ["code"],
        ),
        make_tool_definition(
            "log_message",
            "Zapisuje komunikat do logow pluginu albo QGIS Message Log.",
            {
                "message": {
                    "type": "string",
                    "description": "Tresc komunikatu.",
                },
                "level": {
                    "type": "string",
                    "description": "Poziom logu: info, warning albo error.",
                    "default": "info",
                },
                "tag": {
                    "type": "string",
                    "description": "Tag logu.",
                    "default": "AI Assistant",
                },
            },
            ["message"],
        ),
        make_tool_definition(
            "show_message_bar",
            "Pokazuje uzytkownikowi komunikat w pasku powiadomien QGIS.",
            {
                "message": {
                    "type": "string",
                    "description": "Tresc komunikatu.",
                },
                "title": {
                    "type": "string",
                    "description": "Tytul komunikatu.",
                    "default": "AI Assistant",
                },
                "level": {
                    "type": "string",
                    "description": "info, warning albo error.",
                    "default": "info",
                },
                "duration": {
                    "type": "integer",
                    "description": "Czas wyswietlania w sekundach.",
                    "default": 5,
                },
            },
            ["message"],
        ),
        make_tool_definition(
            "validate_layer",
            (
                "Sprawdza, czy warstwa jest poprawna i gotowa do uzycia: czy istnieje, "
                "jest poprawnie zaladowana, ma geometrie, CRS i pola."
            ),
            {
                "layer_name": {
                    "type": "string",
                    "description": "Opcjonalna nazwa warstwy. Gdy brak, uzywa aktywnej.",
                },
                "require_vector": {
                    "type": "boolean",
                    "description": "Czy wymagana jest warstwa wektorowa.",
                    "default": False,
                },
                "require_geometry": {
                    "type": "boolean",
                    "description": "Czy warstwa musi miec geometrie.",
                    "default": False,
                },
                "require_fields": {
                    "type": "boolean",
                    "description": "Czy warstwa musi miec pola atrybutowe.",
                    "default": False,
                },
            },
        ),
        make_tool_definition(
            "preview_action",
            (
                "Zwraca opis planowanej operacji przed jej wykonaniem: jakie warstwy "
                "zostana uzyte, co zostanie utworzone lub zmienione i jakie sa skutki."
            ),
            {
                "action_name": {
                    "type": "string",
                    "description": "Nazwa planowanej operacji albo toola.",
                },
                "target_layers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista nazw warstw, ktorych dotyczy operacja.",
                },
                "output_name": {
                    "type": "string",
                    "description": "Opcjonalna nazwa warstwy wynikowej.",
                },
                "target_crs": {
                    "type": "string",
                    "description": "Opcjonalny docelowy CRS.",
                },
                "expression": {
                    "type": "string",
                    "description": "Opcjonalne wyrazenie filtrowania albo selekcji.",
                },
                "notes": {
                    "type": "string",
                    "description": "Dodatkowe notatki o planowanej operacji.",
                },
            },
            ["action_name"],
        ),
        make_tool_definition(
            "get_layer_details",
            (
                "Zwraca szczegoly wskazanej warstwy po nazwie: typ, CRS, pola, "
                "geometrie, liczbe obiektow i zasieg."
            ),
            {
                "layer_name": {
                    "type": "string",
                    "description": "Nazwa warstwy w projekcie QGIS.",
                }
            },
            ["layer_name"],
        ),
        make_tool_definition(
            "get_selected_features_count",
            "Zwraca liczbe zaznaczonych obiektow w warstwie wektorowej.",
            {
                "layer_name": {
                    "type": "string",
                    "description": "Nazwa warstwy wektorowej.",
                }
            },
            ["layer_name"],
        ),
        make_tool_definition(
            "get_attribute_table_page",
            (
                "Zwraca strone tabeli atrybutow warstwy wektorowej: kolumny, rekordy, "
                "FID oraz informacje o stronicowaniu."
            ),
            {
                "layer_name": {
                    "type": "string",
                    "description": "Nazwa warstwy wektorowej.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Liczba rekordow do zwrocenia, maksymalnie 100.",
                    "default": 20,
                },
                "offset": {
                    "type": "integer",
                    "description": "Przesuniecie poczatkowe dla stronicowania.",
                    "default": 0,
                },
                "only_selected": {
                    "type": "boolean",
                    "description": "Czy zwrocic tylko zaznaczone obiekty.",
                    "default": False,
                },
            },
            ["layer_name"],
        ),
        make_tool_definition(
            "query_attribute_table",
            (
                "Przeglada tabele atrybutow warstwy wektorowej z filtrem QGIS "
                "expression i zwraca dopasowane rekordy."
            ),
            {
                "layer_name": {
                    "type": "string",
                    "description": "Nazwa warstwy wektorowej.",
                },
                "expression": {
                    "type": "string",
                    "description": "Wyrazenie filtrowania QGIS.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Liczba rekordow do zwrocenia, maksymalnie 100.",
                    "default": 20,
                },
                "offset": {
                    "type": "integer",
                    "description": "Przesuniecie poczatkowe dla stronicowania.",
                    "default": 0,
                },
            },
            ["layer_name", "expression"],
        ),
        make_tool_definition(
            "run_buffer",
            "Alias dla narzedzia buffer.",
            {
                "layer_name": {
                    "type": "string",
                    "description": "Nazwa warstwy wektorowej.",
                },
                "distance": {
                    "type": "number",
                    "description": "Odleglosc bufora w jednostkach warstwy.",
                },
                "segments": {
                    "type": "integer",
                    "description": "Liczba segmentow zaokraglenia bufora.",
                    "default": 8,
                },
                "dissolve": {
                    "type": "boolean",
                    "description": "Czy scalic bufory.",
                    "default": False,
                },
                "output_name": {
                    "type": "string",
                    "description": "Opcjonalna nazwa nowej warstwy wynikowej.",
                },
            },
            ["layer_name", "distance"],
        ),
        make_tool_definition(
            "run_reproject_layer",
            "Alias dla narzedzia reproject_layer.",
            {
                "layer_name": {
                    "type": "string",
                    "description": "Nazwa warstwy wektorowej.",
                },
                "target_crs": {
                    "type": "string",
                    "description": "Docelowy CRS, np. EPSG:2180.",
                },
                "output_name": {
                    "type": "string",
                    "description": "Opcjonalna nazwa nowej warstwy wynikowej.",
                },
            },
            ["layer_name", "target_crs"],
        ),
        make_tool_definition(
            "count_features_within",
            (
                "Liczy i opcjonalnie wyodrebnia obiekty z warstwy points_layer "
                "ktore leza wewnatrz obiektow warstwy polygon_layer. "
                "Opcjonalnie filtruje polygony wyrazeniem filter_expression. "
                "Uzyj tego narzedzia zamiast select_by_expression gdy chcesz policzyc "
                "lub wyodrebnic obiekty na podstawie relacji przestrzennej (within, intersects). "
                "Przyklad: ile miast lezy w danym wojewodztwie, ile punktow w danym obszarze."
            ),
            {
                "points_layer": {
                    "type": "string",
                    "description": "Nazwa warstwy z obiektami do policzenia (np. punkty miast).",
                },
                "polygon_layer": {
                    "type": "string",
                    "description": "Nazwa warstwy z poligonami (np. wojewodztwa, powiaty).",
                },
                "filter_expression": {
                    "type": "string",
                    "description": (
                        "Opcjonalne wyrazenie QGIS filtrujace polygony, np. "
                        "\"JPT_NAZWA_\" ILIKE '%mazow%' lub \"KodWoj\" = '02'. "
                        "Jesli pusty, brane sa wszystkie polygony."
                    ),
                },
                "output_layer_name": {
                    "type": "string",
                    "description": (
                        "Jesli podana, tworzy nowa warstwe w pamieci z wynikowymi obiektami. "
                        "Jesli pusta, tylko liczy bez tworzenia warstwy."
                    ),
                },
            },
            ["points_layer", "polygon_layer"],
        ),
    ]

    def __init__(self, iface):
        self.iface = iface

    def definitions(self):
        return copy.deepcopy(self.TOOL_DEFINITIONS)

    def execute(self, tool_name, arguments=None):
        arguments = arguments or {}
        handlers = {
            "get_project_info": self.get_project_info,
            "list_layers": self.list_layers,
            "get_active_layer_info": self.get_active_layer_info,
            "get_selected_features_info": self.get_selected_features_info,
            "add_vector_layer": self.add_vector_layer,
            "add_raster_layer": self.add_raster_layer,
            "set_active_layer": self.set_active_layer,
            "save_layer_as": self.save_layer_as,
            "get_fields": self.get_fields,
            "calculate_field": self.calculate_field,
            "select_by_expression": self.select_by_expression,
            "filter_layer": self.filter_layer,
            "get_unique_values": self.get_unique_values,
            "summarize_field": self.summarize_field,
            "fix_geometries": self.fix_geometries,
            "buffer": self.buffer,
            "clip": self.clip,
            "intersection": self.intersection,
            "dissolve": self.dissolve,
            "reproject_layer": self.reproject_layer,
            "get_project_crs": self.get_project_crs,
            "get_layer_crs": self.get_layer_crs,
            "set_project_crs": self.set_project_crs,
            "zoom_to_layer": self.zoom_to_layer,
            "zoom_to_selection": self.zoom_to_selection,
            "refresh_canvas": self.refresh_canvas,
            "run_safe_algorithm": self.run_safe_algorithm,
            "generate_pyqgis_code": self.generate_pyqgis_code,
            "insert_into_pyqgis_console": self.insert_into_pyqgis_console,
            "run_pyqgis_code": self.run_pyqgis_code,
            "log_message": self.log_message,
            "show_message_bar": self.show_message_bar,
            "validate_layer": self.validate_layer,
            "preview_action": self.preview_action,
            "get_layer_details": self.get_layer_details,
            "get_selected_features_count": self.get_selected_features_count,
            "get_attribute_table_page": self.get_attribute_table_page,
            "query_attribute_table": self.query_attribute_table,
            "run_buffer": self.run_buffer,
            "run_reproject_layer": self.run_reproject_layer,
            "count_features_within": self.count_features_within,
        }

        handler = handlers.get(tool_name)
        if not handler:
            return {
                "ok": False,
                "tool": tool_name,
                "error": f"Nieznane narzedzie: {tool_name}",
            }

        try:
            result = handler(**arguments)
            if not isinstance(result, dict):
                result = {"result": result}
            if "ok" not in result:
                if "success" in result:
                    result["ok"] = bool(result.get("success"))
                else:
                    result["ok"] = True
            result.setdefault("tool", tool_name)
            return result
        except Exception as exc:
            return {
                "ok": False,
                "tool": tool_name,
                "arguments": arguments,
                "error": str(exc),
            }

    def get_project_info(self):
        project = QgsProject.instance()
        canvas = self.iface.mapCanvas()
        file_path = project.fileName() or ""
        title = project.title().strip() if hasattr(project, "title") else ""
        base_name = project.baseName().strip() if hasattr(project, "baseName") else ""
        project_name = title or base_name or self._derive_layer_name(file_path) or "Untitled project"
        active_layer = self.iface.activeLayer()
        return {
            "project_name": project_name,
            "project_path": file_path,
            "is_saved": bool(file_path),
            "is_dirty": bool(project.isDirty()) if hasattr(project, "isDirty") else False,
            "project_crs": self._crs_details(project.crs()),
            "project_units": self._map_units_to_string(canvas.mapSettings().mapUnits()),
            "map_extent": self._extent_to_dict(canvas.extent()),
            "layer_count": len(project.mapLayers()),
            "active_layer_name": active_layer.name() if active_layer else "",
            "layers": [self._layer_summary(layer) for layer in project.mapLayers().values()],
        }

    def list_layers(self):
        layers = [self._layer_summary(layer) for layer in QgsProject.instance().mapLayers().values()]
        return {
            "count": len(layers),
            "layers": layers,
        }

    def get_active_layer_info(self):
        layer = self._require_active_layer()
        return {
            "active_layer": self._layer_details(layer),
        }

    def get_selected_features_info(self, layer_name="", limit=20):
        layer = self._get_vector_layer(layer_name) if layer_name else self._require_active_vector_layer()
        limit = self._normalize_limit(limit)
        fields = self._field_definitions(layer)
        field_names = [field["name"] for field in fields]
        selected_ids = list(layer.selectedFeatureIds())
        rows = []

        for feature_id in selected_ids[:limit]:
            feature = layer.getFeature(feature_id)
            if feature.isValid():
                rows.append(self._serialize_feature(feature, field_names))

        return {
            "layer_name": layer.name(),
            "selected_features_count": len(selected_ids),
            "returned_count": len(rows),
            "fields": fields,
            "selection_extent": self._selection_extent(layer),
            "rows": rows,
        }

    def add_vector_layer(self, source, layer_name="", provider_name="ogr", make_active=True):
        name = layer_name.strip() or self._derive_layer_name(source) or "vector_layer"
        provider = str(provider_name or "ogr").strip() or "ogr"
        layer = QgsVectorLayer(source, name, provider)
        if not layer.isValid():
            raise Exception(f"Nie udalo sie wczytac warstwy wektorowej ze zrodla: {source}")
        QgsProject.instance().addMapLayer(layer)
        if make_active:
            self._set_active_layer_object(layer)
        return {
            "layer": self._layer_summary(layer),
        }

    def add_raster_layer(self, source, layer_name="", make_active=True):
        name = layer_name.strip() or self._derive_layer_name(source) or "raster_layer"
        layer = QgsRasterLayer(source, name)
        if not layer.isValid():
            raise Exception(f"Nie udalo sie wczytac warstwy rastrowej ze zrodla: {source}")
        QgsProject.instance().addMapLayer(layer)
        if make_active:
            self._set_active_layer_object(layer)
        return {
            "layer": self._layer_summary(layer),
        }

    def set_active_layer(self, layer_name):
        layer = self._get_layer_by_name(layer_name)
        self._set_active_layer_object(layer)
        return {
            "active_layer": self._layer_summary(layer),
        }

    def save_layer_as(
        self,
        layer_name,
        output_path,
        target_crs="",
        add_to_project=False,
        output_name="",
    ):
        layer = self._get_layer_by_name(layer_name)
        output_path = str(output_path or "").strip()
        if not output_path:
            raise Exception("Brak docelowej sciezki output_path.")

        if isinstance(layer, QgsVectorLayer):
            processing = self._processing_module()
            target = self._parse_crs(target_crs) if target_crs else layer.crs()
            processing.run(
                "native:reprojectlayer",
                {
                    "INPUT": layer,
                    "TARGET_CRS": target,
                    "OUTPUT": output_path,
                },
            )
            added_layer = None
            if add_to_project:
                added_layer = QgsVectorLayer(
                    output_path,
                    output_name.strip() or self._derive_layer_name(output_path) or layer.name(),
                    "ogr",
                )
                if not added_layer.isValid():
                    raise Exception("Warstwa zapisala sie, ale nie udalo sie dodac jej do projektu.")
                QgsProject.instance().addMapLayer(added_layer)

            return {
                "source_layer": layer.name(),
                "output_path": output_path,
                "target_crs": target.authid(),
                "added_to_project": bool(add_to_project),
                "added_layer": self._layer_summary(added_layer) if added_layer else None,
            }

        if isinstance(layer, QgsRasterLayer):
            source_path = self._clean_source_path(layer.source())
            if not os.path.exists(source_path):
                raise Exception("Nie udalo sie ustalic zrodlowego pliku rastra do skopiowania.")
            if target_crs:
                target = self._parse_crs(target_crs)
                if target.authid() != layer.crs().authid():
                    raise Exception(
                        "Eksport rastra z reprojekcja nie jest obslugiwany przez save_layer_as. "
                        "Uzyj innego workflow albo dedykowanego algorytmu GDAL."
                    )
            shutil.copy2(source_path, output_path)
            added_layer = None
            if add_to_project:
                added_layer = QgsRasterLayer(
                    output_path,
                    output_name.strip() or self._derive_layer_name(output_path) or layer.name(),
                )
                if not added_layer.isValid():
                    raise Exception("Raster zapisano, ale nie udalo sie dodac go do projektu.")
                QgsProject.instance().addMapLayer(added_layer)

            return {
                "source_layer": layer.name(),
                "output_path": output_path,
                "added_to_project": bool(add_to_project),
                "added_layer": self._layer_summary(added_layer) if added_layer else None,
                "note": "Raster zostal skopiowany bez reprojekcji.",
            }

        raise Exception(f"Nieobslugiwany typ warstwy dla save_layer_as: {layer.name()}")

    def get_fields(self, layer_name):
        layer = self._get_vector_layer(layer_name)
        return {
            "layer_name": layer.name(),
            "fields": self._field_definitions(layer),
        }

    def calculate_field(
        self,
        layer_name,
        field_name,
        expression,
        create_if_missing=False,
        field_type="string",
        field_length=255,
        field_precision=0,
        only_selected=False,
    ):
        layer = self._get_vector_layer(layer_name)
        field_name = str(field_name or "").strip()
        if not field_name:
            raise Exception("Brak nazwy pola do obliczenia.")

        expr = QgsExpression(expression)
        if expr.hasParserError():
            raise Exception(f"Niepoprawne wyrazenie QGIS: {expr.parserErrorString()}")

        started_here = False
        if not layer.isEditable():
            if not layer.startEditing():
                raise Exception(f"Nie udalo sie uruchomic edycji dla warstwy: {layer.name()}")
            started_here = True

        field_index = layer.fields().indexFromName(field_name)
        if field_index < 0:
            if not create_if_missing:
                if started_here and layer.isEditable():
                    layer.rollBack()
                raise Exception(
                    f"Pole '{field_name}' nie istnieje w warstwie '{layer.name()}'. "
                    "Ustaw create_if_missing=True, aby je utworzyc."
                )
            qvariant_type = self._variant_type_from_name(field_type)
            field = QgsField(
                field_name,
                qvariant_type,
                "",
                int(field_length or 0),
                int(field_precision or 0),
            )
            if not layer.addAttribute(field):
                if started_here and layer.isEditable():
                    layer.rollBack()
                raise Exception(f"Nie udalo sie utworzyc pola '{field_name}'.")
            layer.updateFields()
            field_index = layer.fields().indexFromName(field_name)

        context = QgsExpressionContext()
        context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(layer))
        expr.prepare(context)

        request = QgsFeatureRequest()
        if only_selected:
            request.setFilterFids(list(layer.selectedFeatureIds()))

        updated_count = 0
        try:
            for feature in layer.getFeatures(request):
                context.setFeature(feature)
                value = expr.evaluate(context)
                if expr.hasEvalError():
                    raise Exception(f"Blad obliczenia wyrazenia: {expr.evalErrorString()}")
                if not layer.changeAttributeValue(feature.id(), field_index, value):
                    raise Exception(
                        f"Nie udalo sie ustawic wartosci pola '{field_name}' dla obiektu {feature.id()}."
                    )
                updated_count += 1
        except Exception:
            if started_here and layer.isEditable():
                layer.rollBack()
            raise

        if started_here:
            if not layer.commitChanges():
                errors = "; ".join(layer.commitErrors())
                layer.rollBack()
                raise Exception(f"Nie udalo sie zapisac zmian atrybutow: {errors}")
        else:
            layer.triggerRepaint()

        return {
            "layer_name": layer.name(),
            "field_name": field_name,
            "expression": expression,
            "updated_feature_count": updated_count,
            "only_selected": bool(only_selected),
            "committed": bool(started_here),
            "note": (
                "Zmiany zostaly zapisane."
                if started_here
                else "Zmiany pozostaja w aktywnej sesji edycyjnej warstwy."
            ),
        }

    def select_by_expression(self, layer_name, expression, selection_mode="replace"):
        layer = self._get_vector_layer(layer_name)
        expr = QgsExpression(expression)
        if expr.hasParserError():
            raise Exception(f"Niepoprawne wyrazenie QGIS: {expr.parserErrorString()}")

        request = QgsFeatureRequest()
        request.setFilterExpression(expression)
        matched_ids = {feature.id() for feature in layer.getFeatures(request)}
        current_ids = set(layer.selectedFeatureIds())
        mode = str(selection_mode or "replace").strip().lower()

        if mode == "replace":
            new_ids = matched_ids
        elif mode == "add":
            new_ids = current_ids | matched_ids
        elif mode == "remove":
            new_ids = current_ids - matched_ids
        elif mode == "intersect":
            new_ids = current_ids & matched_ids
        else:
            raise Exception("selection_mode musi miec wartosc replace, add, remove albo intersect.")

        layer.selectByIds(list(new_ids))
        return {
            "layer_name": layer.name(),
            "expression": expression,
            "selection_mode": mode,
            "matched_features_count": len(matched_ids),
            "selected_features_count": layer.selectedFeatureCount(),
        }

    def filter_layer(self, layer_name, expression):
        layer = self._get_vector_layer(layer_name)
        previous_filter = layer.subsetString()
        layer.setSubsetString(expression)
        layer.triggerRepaint()
        self.refresh_canvas()
        return {
            "layer_name": layer.name(),
            "previous_filter": previous_filter,
            "current_filter": layer.subsetString(),
            "note": "Filtr zostal ustawiony jako subset string warstwy.",
        }

    def get_unique_values(self, layer_name, field_name, limit=100):
        layer = self._get_vector_layer(layer_name)
        self._field_index(layer, field_name)
        limit = self._normalize_limit(limit)
        values_map = {}

        for feature in layer.getFeatures():
            value = self._serialize_value(feature[field_name])
            key = json.dumps(value, ensure_ascii=False, sort_keys=True)
            values_map[key] = value

        values = list(values_map.values())
        values.sort(key=lambda item: str(item))
        return {
            "layer_name": layer.name(),
            "field_name": field_name,
            "unique_value_count": len(values),
            "values": values[:limit],
            "truncated": len(values) > limit,
        }

    def summarize_field(self, layer_name, field_name, only_selected=False):
        layer = self._get_vector_layer(layer_name)
        self._field_index(layer, field_name)

        request = QgsFeatureRequest()
        if only_selected:
            request.setFilterFids(list(layer.selectedFeatureIds()))

        total_count = 0
        null_count = 0
        numeric_values = []
        lengths = []
        unique_values = {}
        samples = []

        for feature in layer.getFeatures(request):
            total_count += 1
            value = self._serialize_value(feature[field_name])
            if value is None:
                null_count += 1
                continue
            if len(samples) < 10:
                samples.append(value)
            key = json.dumps(value, ensure_ascii=False, sort_keys=True)
            unique_values[key] = value

            if isinstance(value, (int, float)) and not isinstance(value, bool):
                numeric_values.append(float(value))
            else:
                parsed_number = self._try_float(value)
                if parsed_number is not None:
                    numeric_values.append(parsed_number)

            lengths.append(len(str(value)))

        non_null_count = total_count - null_count
        summary = {
            "layer_name": layer.name(),
            "field_name": field_name,
            "only_selected": bool(only_selected),
            "total_feature_count": total_count,
            "non_null_count": non_null_count,
            "null_count": null_count,
            "unique_value_count": len(unique_values),
            "sample_values": samples,
        }

        if numeric_values:
            summary["numeric_summary"] = {
                "count": len(numeric_values),
                "min": min(numeric_values),
                "max": max(numeric_values),
                "mean": sum(numeric_values) / len(numeric_values),
                "sum": sum(numeric_values),
            }

        if lengths:
            summary["text_summary"] = {
                "min_length": min(lengths),
                "max_length": max(lengths),
                "avg_length": sum(lengths) / len(lengths),
            }

        return summary

    def fix_geometries(self, layer_name, output_name=""):
        layer = self._get_vector_layer(layer_name)
        return self._run_processing_vector_algorithm(
            "native:fixgeometries",
            {"INPUT": layer, "OUTPUT": "memory:"},
            output_name=output_name,
            source_layer=layer.name(),
        )

    def buffer(self, layer_name, distance, segments=8, dissolve=False, output_name=""):
        layer = self._get_vector_layer(layer_name)
        return self._run_processing_vector_algorithm(
            "native:buffer",
            {
                "INPUT": layer,
                "DISTANCE": float(distance),
                "SEGMENTS": int(segments),
                "END_CAP_STYLE": 0,
                "JOIN_STYLE": 0,
                "MITER_LIMIT": 2.0,
                "DISSOLVE": bool(dissolve),
                "OUTPUT": "memory:",
            },
            output_name=output_name,
            source_layer=layer.name(),
        )

    def clip(self, input_layer_name, overlay_layer_name, output_name=""):
        input_layer = self._get_vector_layer(input_layer_name)
        overlay_layer = self._get_vector_layer(overlay_layer_name)
        return self._run_processing_vector_algorithm(
            "native:clip",
            {
                "INPUT": input_layer,
                "OVERLAY": overlay_layer,
                "OUTPUT": "memory:",
            },
            output_name=output_name,
            source_layer=input_layer.name(),
            overlay_layer=overlay_layer.name(),
        )

    def intersection(self, input_layer_name, overlay_layer_name, output_name=""):
        input_layer = self._get_vector_layer(input_layer_name)
        overlay_layer = self._get_vector_layer(overlay_layer_name)
        return self._run_processing_vector_algorithm(
            "native:intersection",
            {
                "INPUT": input_layer,
                "OVERLAY": overlay_layer,
                "OUTPUT": "memory:",
            },
            output_name=output_name,
            source_layer=input_layer.name(),
            overlay_layer=overlay_layer.name(),
        )

    def dissolve(self, layer_name, dissolve_field="", separate_disjoint=False, output_name=""):
        layer = self._get_vector_layer(layer_name)
        fields = [dissolve_field] if str(dissolve_field or "").strip() else []
        if fields:
            self._field_index(layer, fields[0])
        return self._run_processing_vector_algorithm(
            "native:dissolve",
            {
                "INPUT": layer,
                "FIELD": fields,
                "SEPARATE_DISJOINT": bool(separate_disjoint),
                "OUTPUT": "memory:",
            },
            output_name=output_name,
            source_layer=layer.name(),
            dissolve_field=fields[0] if fields else "",
        )

    def reproject_layer(self, layer_name, target_crs, output_name=""):
        layer = self._get_vector_layer(layer_name)
        target = self._parse_crs(target_crs)
        return self._run_processing_vector_algorithm(
            "native:reprojectlayer",
            {
                "INPUT": layer,
                "TARGET_CRS": target,
                "OUTPUT": "memory:",
            },
            output_name=output_name,
            source_layer=layer.name(),
            target_crs=target.authid(),
        )

    def get_project_crs(self):
        crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        return {
            "project_crs": self._crs_details(crs),
            "layer_count": len(QgsProject.instance().mapLayers()),
        }

    def get_layer_crs(self, layer_name):
        layer = self._get_layer_by_name(layer_name)
        return {
            "layer_name": layer.name(),
            "layer_crs": self._crs_details(layer.crs()),
        }

    def set_project_crs(self, target_crs):
        project = QgsProject.instance()
        previous_crs = project.crs()
        new_crs = self._parse_crs(target_crs)
        project.setCrs(new_crs)
        try:
            self.iface.mapCanvas().setDestinationCrs(new_crs)
        except Exception:
            pass
        self.refresh_canvas()
        return {
            "previous_crs": self._crs_details(previous_crs),
            "current_crs": self._crs_details(project.crs()),
        }

    def zoom_to_layer(self, layer_name):
        layer = self._get_layer_by_name(layer_name)
        extent = layer.extent()
        if extent.isEmpty():
            raise Exception(f"Warstwa '{layer.name()}' nie ma poprawnego zasiegu.")
        self.iface.mapCanvas().setExtent(extent)
        self.refresh_canvas()
        return {
            "layer_name": layer.name(),
            "extent": self._extent_to_dict(extent),
        }

    def zoom_to_selection(self, layer_name=""):
        layer = self._get_vector_layer(layer_name) if layer_name else self._require_active_vector_layer()
        if layer.selectedFeatureCount() <= 0:
            raise Exception(f"Warstwa '{layer.name()}' nie ma zaznaczonych obiektow.")
        extent = layer.boundingBoxOfSelected()
        self.iface.mapCanvas().setExtent(extent)
        self.refresh_canvas()
        return {
            "layer_name": layer.name(),
            "selection_extent": self._extent_to_dict(extent),
            "selected_features_count": layer.selectedFeatureCount(),
        }

    def refresh_canvas(self):
        self.iface.mapCanvas().refresh()
        return {
            "refreshed": True,
        }

    def run_safe_algorithm(self, algorithm_id, parameters, output_name=""):
        algorithm_id = str(algorithm_id or "").strip()
        if algorithm_id not in self.SAFE_ALGORITHMS:
            allowed = ", ".join(sorted(self.SAFE_ALGORITHMS))
            raise Exception(
                f"Algorytm '{algorithm_id}' nie jest na whiteliscie bezpiecznych algorytmow. "
                f"Dozwolone: {allowed}"
            )
        if not isinstance(parameters, dict):
            raise Exception("Parametr 'parameters' musi byc obiektem JSON.")

        normalized = self._normalize_processing_parameters(parameters)
        normalized.setdefault("OUTPUT", "memory:")
        processing = self._processing_module()
        before_ids = set(QgsProject.instance().mapLayers().keys())
        result = processing.runAndLoadResults(algorithm_id, normalized)
        new_layer = self._find_new_layer(before_ids)
        if new_layer and output_name:
            new_layer.setName(output_name)

        return {
            "algorithm_id": algorithm_id,
            "allowed": True,
            "parameters": self._serialize_value(parameters),
            "output_layer": self._layer_summary(new_layer) if new_layer else None,
            "processing_result": self._serialize_value(result),
        }

    def generate_pyqgis_code(self, task_description, layer_name="", include_project_context=True):
        task_text = str(task_description or "").strip()
        if not task_text:
            raise Exception("Brak opisu zadania do wygenerowania kodu.")

        layer = self._get_layer_by_name(layer_name) if layer_name else self.iface.activeLayer()
        context = self.get_project_info() if include_project_context else {}

        lines = [
            "from qgis.core import QgsProject",
            "",
            "project = QgsProject.instance()",
            "",
            "# Cel:",
            f"# {task_text}",
        ]

        if include_project_context:
            lines.extend(
                [
                    "",
                    "# Kontekst projektu:",
                    f"# Project: {context.get('project_name', '')}",
                    f"# CRS: {context.get('project_crs', {}).get('authid', '')}",
                    "# Warstwy:",
                ]
            )
            for layer_info in context.get("layers", [])[:12]:
                lines.append(
                    f"# - {layer_info.get('name', '')} ({layer_info.get('layer_type', '')}, {layer_info.get('crs', '')})"
                )

        if layer:
            lines.extend(
                [
                    "",
                    f"layers = project.mapLayersByName({layer.name()!r})",
                    "if not layers:",
                    f"    raise Exception('Nie znaleziono warstwy: {layer.name()}')",
                    "layer = layers[0]",
                ]
            )

        lines.extend(
            [
                "",
                "# TODO: uzupelnij logike zadania.",
                "# Przyklad bezpiecznego szkicu:",
                "try:",
                "    print('Rozpoczynam zadanie w QGIS...')",
                "    # tutaj dodaj wlasciwy kod PyQGIS",
                "except Exception as exc:",
                "    print(f'Blad: {exc}')",
            ]
        )

        return {
            "task_description": task_text,
            "summary": f"Wygenerowano szkic PyQGIS dla zadania: {task_text}",
            "code": "\n".join(lines),
            "context": context,
        }

    def insert_into_pyqgis_console(self, code):
        text = str(code or "").rstrip()
        if not text:
            raise Exception("Brak kodu do wstawienia do konsoli PyQGIS.")

        inserted = False
        detail = ""

        try:
            action_getter = getattr(self.iface, "actionShowPythonDialog", None)
            if callable(action_getter):
                action = action_getter()
                if action is not None:
                    action.trigger()
        except Exception:
            pass

        try:
            from console import console

            shell = None
            if hasattr(console, "_console"):
                shell = getattr(console._console, "shell", None)
            if shell is None and hasattr(console, "console"):
                shell = getattr(console.console, "shell", None)

            if shell is not None:
                if hasattr(shell, "insertFromDropPaste"):
                    shell.insertFromDropPaste(text)
                    inserted = True
                elif hasattr(shell, "insertPlainText"):
                    shell.insertPlainText(text)
                    inserted = True
        except Exception as exc:
            detail = str(exc)

        if not inserted:
            from qgis.PyQt.QtWidgets import QApplication

            QApplication.clipboard().setText(text)
            detail = detail or "Nie udalo sie bezposrednio wstawic kodu, skopiowano go do schowka."

        return {
            "inserted_into_console": inserted,
            "used_clipboard_fallback": not inserted,
            "detail": detail,
        }

    def run_pyqgis_code(self, code, action_label=""):
        text = str(code or "").rstrip()
        if not text:
            raise Exception("Brak kodu do wykonania.")

        before_snapshot = self._project_snapshot()
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        started_at = time.perf_counter()
        label = str(action_label or "").strip() or "Kod PyQGIS"

        QgsMessageLog.logMessage(
            f"Start wykonania: {label}",
            "AI Assistant",
            Qgis.Info,
        )

        try:
            compiled = compile(text, "<pyqgis_code>", "exec")
            exec_globals = self._execution_globals()
            with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
                exec(compiled, exec_globals, exec_globals)
        except Exception as exc:
            after_snapshot = self._project_snapshot()
            execution_time_ms = int((time.perf_counter() - started_at) * 1000)
            stderr_text = stderr_buffer.getvalue().strip()
            error_text = str(exc).strip() or exc.__class__.__name__
            if stderr_text:
                error_text = f"{stderr_text}\n{error_text}"
            QgsMessageLog.logMessage(
                f"Blad wykonania: {error_text}",
                "AI Assistant",
                Qgis.Critical,
            )
            return {
                "success": False,
                "ok": False,
                "message": f"Nie udalo sie wykonac: {label}",
                "stdout": stdout_buffer.getvalue().strip(),
                "stderr": error_text,
                "created_layers": self._created_layer_names(before_snapshot, after_snapshot),
                "modified_layers": self._modified_layer_names(before_snapshot, after_snapshot),
                "execution_time_ms": execution_time_ms,
                "risk_level": "high",
            }

        after_snapshot = self._project_snapshot()
        execution_time_ms = int((time.perf_counter() - started_at) * 1000)
        created_layers = self._created_layer_names(before_snapshot, after_snapshot)
        modified_layers = self._modified_layer_names(before_snapshot, after_snapshot)
        QgsMessageLog.logMessage(
            f"Zakonczono wykonanie: {label}",
            "AI Assistant",
            Qgis.Success,
        )
        return {
            "success": True,
            "ok": True,
            "message": f"Wykonano: {label}",
            "stdout": stdout_buffer.getvalue().strip(),
            "stderr": stderr_buffer.getvalue().strip(),
            "created_layers": created_layers,
            "modified_layers": modified_layers,
            "execution_time_ms": execution_time_ms,
            "risk_level": "high",
        }

    def log_message(self, message, level="info", tag="AI Assistant"):
        log_level = self._message_level(level)
        QgsMessageLog.logMessage(str(message), str(tag or "AI Assistant"), log_level)
        return {
            "message": str(message),
            "level": str(level or "info"),
            "tag": str(tag or "AI Assistant"),
        }

    def show_message_bar(self, message, title="AI Assistant", level="info", duration=5):
        msg_level = self._message_level(level)
        self.iface.messageBar().pushMessage(
            str(title or "AI Assistant"),
            str(message),
            level=msg_level,
            duration=max(0, int(duration or 0)),
        )
        return {
            "message": str(message),
            "title": str(title or "AI Assistant"),
            "level": str(level or "info"),
            "duration": max(0, int(duration or 0)),
        }

    def validate_layer(
        self,
        layer_name="",
        require_vector=False,
        require_geometry=False,
        require_fields=False,
    ):
        layer = self._get_layer_by_name(layer_name) if layer_name else self._require_active_layer()
        issues = []
        warnings = []

        if not layer.isValid():
            issues.append("Warstwa nie jest poprawnie zaladowana.")
        if require_vector and not isinstance(layer, QgsVectorLayer):
            issues.append("Wymagana jest warstwa wektorowa.")
        if not layer.crs().isValid():
            issues.append("Warstwa nie ma poprawnego CRS.")
        if require_geometry and not layer.isSpatial():
            issues.append("Warstwa nie ma geometrii.")
        if require_fields and isinstance(layer, QgsVectorLayer) and len(layer.fields()) == 0:
            issues.append("Warstwa nie ma dostepnych pol atrybutowych.")
        if isinstance(layer, QgsVectorLayer) and layer.featureCount() == 0:
            warnings.append("Warstwa nie zawiera obiektow.")

        return {
            "layer": self._layer_summary(layer),
            "ready": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
        }

    def preview_action(
        self,
        action_name,
        target_layers=None,
        output_name="",
        target_crs="",
        expression="",
        notes="",
    ):
        target_layers = list(target_layers or [])
        resolved_layers = []
        missing_layers = []

        for layer_name in target_layers:
            try:
                resolved_layers.append(self._layer_summary(self._get_layer_by_name(layer_name)))
            except Exception:
                missing_layers.append(layer_name)

        mutating_actions = {
            "add_vector_layer",
            "add_raster_layer",
            "buffer",
            "calculate_field",
            "clip",
            "dissolve",
            "filter_layer",
            "fix_geometries",
            "intersection",
            "reproject_layer",
            "run_safe_algorithm",
            "save_layer_as",
            "select_by_expression",
            "set_active_layer",
            "set_project_crs",
        }
        creates_layer_actions = {
            "add_vector_layer",
            "add_raster_layer",
            "buffer",
            "clip",
            "dissolve",
            "fix_geometries",
            "intersection",
            "reproject_layer",
            "run_safe_algorithm",
        }

        summary_lines = [f"Planowana akcja: {action_name}"]
        if target_layers:
            summary_lines.append(f"Warstwy docelowe: {', '.join(target_layers)}")
        if output_name:
            summary_lines.append(f"Warstwa wynikowa: {output_name}")
        if target_crs:
            summary_lines.append(f"Docelowy CRS: {target_crs}")
        if expression:
            summary_lines.append(f"Wyrazenie: {expression}")
        if notes:
            summary_lines.append(f"Uwagi: {notes}")

        return {
            "action_name": action_name,
            "changes_project_or_data": action_name in mutating_actions,
            "creates_new_layer": action_name in creates_layer_actions,
            "requires_confirmation": action_name in mutating_actions,
            "resolved_layers": resolved_layers,
            "missing_layers": missing_layers,
            "output_name": output_name,
            "target_crs": target_crs,
            "expression": expression,
            "notes": notes,
            "summary": " | ".join(summary_lines),
        }

    def get_layer_details(self, layer_name):
        layer = self._get_layer_by_name(layer_name)
        return {
            "layer": self._layer_details(layer),
        }

    def get_selected_features_count(self, layer_name):
        layer = self._get_vector_layer(layer_name)
        return {
            "layer_name": layer.name(),
            "selected_features_count": layer.selectedFeatureCount(),
            "total_features_count": layer.featureCount(),
        }

    def get_attribute_table_page(self, layer_name, limit=20, offset=0, only_selected=False):
        layer = self._get_vector_layer(layer_name)
        limit = self._normalize_limit(limit)
        offset = self._normalize_offset(offset)

        fields = self._field_definitions(layer)
        field_names = [field["name"] for field in fields]

        if only_selected:
            selected_ids = list(layer.selectedFeatureIds())
            total_count = len(selected_ids)
            page_ids = selected_ids[offset: offset + limit]
            rows = []
            for feature_id in page_ids:
                feature = layer.getFeature(feature_id)
                if feature.isValid():
                    rows.append(self._serialize_feature(feature, field_names))
        else:
            total_count = layer.featureCount()
            request = QgsFeatureRequest()
            request.setOffset(offset)
            request.setLimit(limit)
            rows = [
                self._serialize_feature(feature, field_names)
                for feature in layer.getFeatures(request)
            ]

        return {
            "layer_name": layer.name(),
            "fields": fields,
            "offset": offset,
            "limit": limit,
            "only_selected": bool(only_selected),
            "returned_count": len(rows),
            "total_features_count": total_count,
            "has_more": offset + len(rows) < total_count,
            "rows": rows,
        }

    def query_attribute_table(self, layer_name, expression, limit=20, offset=0):
        layer = self._get_vector_layer(layer_name)
        expr = QgsExpression(expression)
        if expr.hasParserError():
            raise Exception(f"Niepoprawne wyrazenie QGIS: {expr.parserErrorString()}")

        limit = self._normalize_limit(limit)
        offset = self._normalize_offset(offset)
        fields = self._field_definitions(layer)
        field_names = [field["name"] for field in fields]

        request = QgsFeatureRequest()
        request.setFilterExpression(expression)

        rows = []
        total_count = 0
        for feature in layer.getFeatures(request):
            if total_count >= offset and len(rows) < limit:
                rows.append(self._serialize_feature(feature, field_names))
            total_count += 1

        return {
            "layer_name": layer.name(),
            "expression": expression,
            "fields": fields,
            "offset": offset,
            "limit": limit,
            "returned_count": len(rows),
            "matched_features_count": total_count,
            "has_more": offset + len(rows) < total_count,
            "rows": rows,
        }

    def run_buffer(self, layer_name, distance, segments=8, dissolve=False, output_name=""):
        return self.buffer(
            layer_name=layer_name,
            distance=distance,
            segments=segments,
            dissolve=dissolve,
            output_name=output_name,
        )

    def run_reproject_layer(self, layer_name, target_crs, output_name=""):
        return self.reproject_layer(
            layer_name=layer_name,
            target_crs=target_crs,
            output_name=output_name,
        )

    def count_features_within(
        self,
        points_layer,
        polygon_layer,
        filter_expression="",
        output_layer_name="",
    ):
        """
        Liczy obiekty z points_layer lezace wewnatrz obiektow polygon_layer.
        Opcjonalnie filtruje polygony wyrazeniem filter_expression.
        Opcjonalnie tworzy nowa warstwe wynikowa w pamieci.
        """
        from qgis.core import (
            QgsExpression,
            QgsFeature,
            QgsFeatureRequest,
            QgsProject,
            QgsVectorLayer,
        )

        pts_layer = self._get_layer_by_name(points_layer)
        poly_layer = self._get_layer_by_name(polygon_layer)

        # Zbierz geometrie polygon (opcjonalnie przefiltrowane)
        poly_geoms = []
        poly_labels = []
        if filter_expression and filter_expression.strip():
            expr = QgsExpression(filter_expression.strip())
            if not expr.isValid():
                raise Exception(
                    f"Niepoprawne wyrazenie filtru: {expr.errorMessage()}"
                )
            req = QgsFeatureRequest(expr)
            for feat in poly_layer.getFeatures(req):
                poly_geoms.append(feat.geometry())
                for fname in ("JPT_NAZWA_", "NAZWA", "nazwa", "name", "NAME", "NazwaJed"):
                    val = feat.attribute(fname) if feat.fieldNameIndex(fname) >= 0 else None
                    if val:
                        poly_labels.append(str(val))
                        break
                else:
                    poly_labels.append(str(feat.id()))
        else:
            for feat in poly_layer.getFeatures():
                poly_geoms.append(feat.geometry())
                poly_labels.append(str(feat.id()))

        if not poly_geoms:
            return {
                "ok": False,
                "count": 0,
                "message": "Filtr nie zwrocil zadnych poligonow.",
                "polygon_count": 0,
            }

        # Polacz wszystkie geometrie poligonow w jedna (union)
        combined = poly_geoms[0]
        for g in poly_geoms[1:]:
            combined = combined.combine(g)

        # Zbierz obiekty wewnatrz
        matching_features = []
        for feat in pts_layer.getFeatures():
            geom = feat.geometry()
            if geom and combined.contains(geom):
                matching_features.append(feat)

        count = len(matching_features)

        # Opcjonalnie stworz warstwe wynikowa
        created_layer = None
        if output_layer_name and output_layer_name.strip():
            geom_type = QgsWkbTypes.displayString(pts_layer.wkbType())
            crs_authid = pts_layer.crs().authid()
            mem_layer = QgsVectorLayer(
                f"{geom_type}?crs={crs_authid}",
                output_layer_name.strip(),
                "memory",
            )
            provider = mem_layer.dataProvider()
            provider.addAttributes(pts_layer.fields().toList())
            mem_layer.updateFields()
            new_feats = []
            for feat in matching_features:
                nf = QgsFeature()
                nf.setGeometry(feat.geometry())
                nf.setAttributes(feat.attributes())
                new_feats.append(nf)
            provider.addFeatures(new_feats)
            mem_layer.updateExtents()
            QgsProject.instance().addMapLayer(mem_layer)
            created_layer = output_layer_name.strip()

        filter_desc = filter_expression.strip() if filter_expression else "brak (wszystkie polygony)"
        polygon_desc = ", ".join(poly_labels[:5])
        if len(poly_labels) > 5:
            polygon_desc += f" ... (+{len(poly_labels) - 5} wiecej)"

        return {
            "ok": True,
            "count": count,
            "points_layer": points_layer,
            "polygon_layer": polygon_layer,
            "filter_expression": filter_expression or "",
            "matching_polygons": polygon_desc,
            "created_layer": created_layer,
            "message": (
                f"Liczba obiektow z '{points_layer}' wewnatrz '{polygon_layer}' "
                f"(filtr: {filter_desc}): {count}"
                + (f". Utworzono warstwe '{created_layer}'." if created_layer else ".")
            ),
        }

    def _layer_summary(self, layer):
        details = {
            "id": layer.id(),
            "name": layer.name(),
            "source": layer.source(),
            "crs": layer.crs().authid(),
            "crs_description": layer.crs().description(),
            "extent": self._extent_to_dict(layer.extent()),
            "is_valid": bool(layer.isValid()),
            "is_active": bool(self.iface.activeLayer() and self.iface.activeLayer().id() == layer.id()),
            "is_spatial": bool(layer.isSpatial()) if hasattr(layer, "isSpatial") else True,
        }
        if isinstance(layer, QgsVectorLayer):
            details.update(
                {
                    "layer_type": "vector",
                    "provider_type": layer.providerType(),
                    "geometry_type": QgsWkbTypes.displayString(layer.wkbType()),
                    "feature_count": layer.featureCount(),
                    "selected_feature_count": layer.selectedFeatureCount(),
                    "subset_string": layer.subsetString(),
                }
            )
        elif isinstance(layer, QgsRasterLayer):
            details.update(
                {
                    "layer_type": "raster",
                    "provider_type": layer.providerType(),
                    "band_count": layer.bandCount(),
                    "width": layer.width(),
                    "height": layer.height(),
                }
            )
        else:
            details["layer_type"] = "unknown"
        return details

    def _layer_details(self, layer):
        details = self._layer_summary(layer)
        if isinstance(layer, QgsVectorLayer):
            details["fields"] = self._field_definitions(layer)
        elif isinstance(layer, QgsRasterLayer):
            details["raster_bands"] = layer.bandCount()
        return details

    def _crs_details(self, crs):
        return {
            "authid": crs.authid(),
            "description": crs.description(),
            "is_valid": bool(crs.isValid()),
            "is_geographic": bool(crs.isGeographic()) if crs.isValid() else False,
        }

    def _extent_to_dict(self, extent):
        return {
            "xmin": extent.xMinimum(),
            "ymin": extent.yMinimum(),
            "xmax": extent.xMaximum(),
            "ymax": extent.yMaximum(),
        }

    def _map_units_to_string(self, units):
        try:
            return QgsUnitTypes.toString(units)
        except Exception:
            return str(units)

    def _field_definitions(self, layer):
        return [
            {
                "name": field.name(),
                "type": field.typeName(),
                "length": field.length(),
                "precision": field.precision(),
            }
            for field in layer.fields()
        ]

    def _serialize_feature(self, feature, field_names):
        return {
            "fid": feature.id(),
            "attributes": {
                field_name: self._serialize_value(feature[field_name])
                for field_name in field_names
            },
        }

    def _serialize_value(self, value):
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, bytes):
            return value.hex()
        if isinstance(value, (list, tuple)):
            return [self._serialize_value(item) for item in value]
        if isinstance(value, dict):
            return {
                str(key): self._serialize_value(item)
                for key, item in value.items()
            }

        text = str(value)
        if text == "NULL":
            return None
        return text

    def _normalize_limit(self, limit):
        try:
            normalized = int(limit)
        except (TypeError, ValueError):
            normalized = 20
        return max(1, min(normalized, 100))

    def _normalize_offset(self, offset):
        try:
            normalized = int(offset)
        except (TypeError, ValueError):
            normalized = 0
        return max(0, normalized)

    def _get_layer_by_name(self, layer_name):
        name = str(layer_name or "").strip()
        if not name:
            raise Exception("Brak nazwy warstwy.")
        layers = QgsProject.instance().mapLayersByName(name)
        if not layers:
            raise Exception(f"Nie znaleziono warstwy o nazwie: {name}")
        return layers[0]

    def _require_active_layer(self):
        layer = self.iface.activeLayer()
        if layer is None:
            raise Exception("Brak aktywnej warstwy w projekcie QGIS.")
        return layer

    def _require_active_vector_layer(self):
        layer = self._require_active_layer()
        if not isinstance(layer, QgsVectorLayer):
            raise Exception("Aktywna warstwa nie jest warstwa wektorowa.")
        return layer

    def _get_vector_layer(self, layer_name):
        layer = self._get_layer_by_name(layer_name)
        if not isinstance(layer, QgsVectorLayer):
            raise Exception(f"Warstwa '{layer_name}' nie jest warstwa wektorowa.")
        return layer

    def _field_index(self, layer, field_name):
        field_index = layer.fields().indexFromName(field_name)
        if field_index < 0:
            raise Exception(f"Warstwa '{layer.name()}' nie ma pola '{field_name}'.")
        return field_index

    def _parse_crs(self, crs_text):
        crs = QgsCoordinateReferenceSystem(str(crs_text or "").strip())
        if not crs.isValid():
            raise Exception(f"Niepoprawny CRS: {crs_text}")
        return crs

    def _selection_extent(self, layer):
        if layer.selectedFeatureCount() <= 0:
            return None
        return self._extent_to_dict(layer.boundingBoxOfSelected())

    def _derive_layer_name(self, source):
        text = str(source or "").strip()
        if not text:
            return ""
        path = text.split("|", 1)[0]
        base = os.path.basename(path)
        name, _ext = os.path.splitext(base)
        return name or text

    def _set_active_layer_object(self, layer):
        self.iface.setActiveLayer(layer)
        try:
            self.iface.layerTreeView().setCurrentLayer(layer)
        except Exception:
            pass

    def _clean_source_path(self, source):
        return str(source or "").split("|", 1)[0]

    def _variant_type_from_name(self, field_type):
        value = str(field_type or "string").strip().lower()
        mapping = {
            "bool": QVariant.Bool,
            "boolean": QVariant.Bool,
            "date": QVariant.Date,
            "datetime": QVariant.DateTime,
            "double": QVariant.Double,
            "float": QVariant.Double,
            "int": QVariant.Int,
            "integer": QVariant.Int,
            "longlong": QVariant.LongLong,
            "string": QVariant.String,
        }
        return mapping.get(value, QVariant.String)

    def _message_level(self, level):
        value = str(level or "info").strip().lower()
        if value in {"warn", "warning"}:
            return Qgis.Warning
        if value in {"critical", "error"}:
            return Qgis.Critical
        if value == "success":
            return Qgis.Success
        return Qgis.Info

    def _try_float(self, value):
        try:
            if isinstance(value, bool):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _normalize_processing_parameters(self, parameters):
        normalized = {}
        for key, value in parameters.items():
            normalized[key] = self._normalize_processing_parameter(key, value)
        return normalized

    def _normalize_processing_parameter(self, key, value):
        if isinstance(value, dict):
            return {
                nested_key: self._normalize_processing_parameter(nested_key, nested_value)
                for nested_key, nested_value in value.items()
            }

        if isinstance(value, list):
            if key in self.LAYER_PARAMETER_KEYS:
                normalized_layers = []
                for item in value:
                    if isinstance(item, str):
                        normalized_layers.append(self._get_layer_by_name(item))
                    else:
                        normalized_layers.append(item)
                return normalized_layers
            return [self._normalize_processing_parameter(key, item) for item in value]

        if isinstance(value, str):
            text = value.strip()
            if key in self.CRS_PARAMETER_KEYS and text:
                return self._parse_crs(text)
            if key in self.LAYER_PARAMETER_KEYS and text:
                try:
                    return self._get_layer_by_name(text)
                except Exception:
                    return value
        return value

    def _run_processing_vector_algorithm(self, algorithm_id, parameters, output_name="", **extra):
        processing = self._processing_module()
        before_ids = set(QgsProject.instance().mapLayers().keys())
        result = processing.runAndLoadResults(algorithm_id, parameters)
        output_layer = self._find_new_vector_layer(before_ids)
        if output_name:
            output_layer.setName(output_name)

        payload = {
            "algorithm_id": algorithm_id,
            "output_layer": output_layer.name(),
            "output_layer_id": output_layer.id(),
            "feature_count": output_layer.featureCount(),
            "crs": output_layer.crs().authid(),
            "geometry_type": QgsWkbTypes.displayString(output_layer.wkbType()),
            "processing_result": self._serialize_value(result),
        }
        payload.update(extra)
        return payload

    def _find_new_layer(self, before_ids):
        new_layers = [
            layer
            for layer_id, layer in QgsProject.instance().mapLayers().items()
            if layer_id not in before_ids
        ]
        if not new_layers:
            return None
        return new_layers[-1]

    def _find_new_vector_layer(self, before_ids):
        new_layers = [
            layer
            for layer_id, layer in QgsProject.instance().mapLayers().items()
            if layer_id not in before_ids and isinstance(layer, QgsVectorLayer)
        ]
        if not new_layers:
            raise Exception("Algorytm nie dodal nowej warstwy wynikowej do projektu.")
        return new_layers[-1]

    def _processing_module(self):
        try:
            import processing
        except ImportError as exc:
            raise Exception("Modul QGIS Processing nie jest dostepny.") from exc
        return processing

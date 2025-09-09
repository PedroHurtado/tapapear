from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import StatusCode, SpanKind
from typing import Sequence
import time
from collections import defaultdict


class TreeConsoleSpanExporter(SpanExporter):
    """
    Exportador de spans para desarrollo: muestra la información agrupada por capas
    arquitectónicas con formato compacto y legible.
    """

    def __init__(self, show_attributes=False):
        self.show_attributes = show_attributes
        self.traces = defaultdict(list)

    def export(self, spans: Sequence) -> SpanExportResult:
        for span in spans:
            trace_id = format(span.context.trace_id, "x")
            self.traces[trace_id].append(span)

        for trace_id, trace_spans in self.traces.items():
            self._print_trace(trace_id, trace_spans)

        self.traces.clear()
        return SpanExportResult.SUCCESS

    # ---------- Helpers para determinar capas ----------
    def _get_layer_from_span(self, span):
        """Determina la capa arquitectónica basándose en el nombre del span"""
        name = getattr(span, "name", "").lower()
        
        if any(method in name for method in ["get", "post", "put", "delete", "patch"]) and "http" not in name:
            return "presentation"
        elif any(keyword in name for keyword in ["mediator", "pipeline", "handler", "application"]):
            return "application"
        elif any(keyword in name for keyword in ["entity", "domain"]):
            return "domain"
        elif any(keyword in name for keyword in ["repository", "firestore", "infrastructure", "infraestructure"]):
            return "infrastructure"
        else:
            # Fallback basado en atributos
            attrs = getattr(span, "attributes", {}) or {}
            if "http.method" in attrs:
                return "presentation"
            elif "mediator.command.type" in attrs:
                return "application"
            else:
                return "infrastructure"  # Default

    def _get_layer_icon_and_name(self, layer):
        """Retorna el icono y nombre de la capa"""
        layer_map = {
            "presentation": ("🌐", "PRESENTATION LAYER"),
            "application": ("⚙️", "APPLICATION LAYER"),
            "domain": ("🏛️", "DOMAIN LAYER"),
            "infrastructure": ("🔧", "INFRASTRUCTURE LAYER")
        }
        return layer_map.get(layer, ("📡", "UNKNOWN LAYER"))

    def _group_spans_by_layer(self, spans):
        """Agrupa spans por capa manteniendo el orden jerárquico"""
        layers = {
            "presentation": [],
            "application": [],
            "domain": [],
            "infrastructure": []
        }
        
        # Construir árbol de spans
        span_tree = self._build_span_tree(spans)
        
        for span in spans:
            layer = self._get_layer_from_span(span)
            layers[layer].append(span)
        
        # Ordenar por tiempo de inicio dentro de cada capa
        for layer in layers:
            layers[layer].sort(key=lambda s: getattr(s, "start_time", 0))
        
        return layers, span_tree

    def _build_span_tree(self, spans):
        """Construye el árbol de relaciones padre-hijo"""
        tree = defaultdict(list)
        span_map = {span.context.span_id: span for span in spans}
        
        for span in spans:
            parent_id = getattr(span.parent, "span_id", None)
            if parent_id and parent_id in span_map:
                tree[parent_id].append(span)
        
        return tree

    def _get_span_hierarchy_prefix(self, span, span_tree, processed_spans, is_root_in_layer=False):
        """DEPRECATED - Método eliminado, ahora usamos indentación simple"""
        return ""

    # ---------- Formateo de información ----------
    def _get_status_display(self, span):
        """Retorna el estado formateado"""
        code = getattr(span.status, "status_code", None)
        if code == StatusCode.OK:
            return "[✅ OK]"
        elif code == StatusCode.ERROR:
            return "[❌ ERROR]"
        return "[⚠️ UNSET]"

    def _get_duration_ms(self, span):
        """Calcula la duración en milisegundos"""
        if getattr(span, "end_time", None) and getattr(span, "start_time", None):
            return (span.end_time - span.start_time) / 1_000_000
        return 0

    def _format_duration(self, duration_ms):
        """Formatea la duración"""
        if duration_ms >= 1000:
            return f"{duration_ms/1000:.3f}s"
        elif duration_ms >= 1:
            return f"{duration_ms:.1f}ms"
        return f"{duration_ms*1000:.0f}μs"

    def _get_extra_info(self, span):
        """Obtiene información extra relevante del span"""
        attrs = getattr(span, "attributes", None) or {}
        
        # HTTP relevante
        if "http.method" in attrs and "http.status_code" in attrs and "http.url" in attrs:
            return f"→ {attrs['http.status_code']} | {attrs['http.url']}"
        
        # Para mediator.send, mostrar solo el comando (sin ID)
        if "mediator.command.type" in attrs and ("mediator.send" in getattr(span, "name", "") or "application.mediator.send" in getattr(span, "name", "")):
            cmd_type = attrs.get("mediator.command.type")
            return f"→ {cmd_type}"
        
        # Para pipelines
        if "mediator.pipeline.name" in attrs:
            name = attrs.get("mediator.pipeline.name")
            return name
        
        # Para handlers
        if "mediator.handler.name" in attrs:
            return attrs.get("mediator.handler.name")
        
        # Para entidades de dominio, mostrar el ID
        if "entity" in getattr(span, "name", "").lower() and "create" in getattr(span, "name", "").lower():
            entity_id = attrs.get("entity.id") or attrs.get("document.id")
            if entity_id:
                return f"→ {entity_id}"
        
        return ""

    # ---------- Impresión ----------
    def _print_trace_header(self, trace_id, spans):
        """Imprime la cabecera del trace"""
        total_duration = max([self._get_duration_ms(s) for s in spans]) if spans else 0
        span_count = len(spans)
        
        print(f"\n🔍 TRACE: {trace_id[:8]}...{trace_id[-8:]} | {self._format_duration(total_duration)} | {span_count} spans")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    def _print_layer_spans(self, layer_spans, layer, span_tree):
        """Imprime los spans de una capa específica"""
        if not layer_spans:
            return
        
        icon, layer_name = self._get_layer_icon_and_name(layer)
        print(f"\n{icon} {layer_name}")
        
        # Agrupar spans por jerarquía dentro de la capa
        processed = set()
        
        for i, span in enumerate(layer_spans):
            if span.context.span_id in processed:
                continue
                
            duration = self._get_duration_ms(span)
            duration_str = self._format_duration(duration)
            status = self._get_status_display(span)
            extra_info = self._get_extra_info(span)
            
            # Determinar si es root en la capa o tiene jerarquía
            prefix = self._get_span_hierarchy_prefix(span, span_tree, layer_spans, len([s for s in layer_spans if getattr(s.parent, "span_id", None) not in [ls.context.span_id for ls in layer_spans]]) > 0 and i == 0)
            
            # Limpiar nombre del span
            clean_name = span.name
            if layer == "application":
                clean_name = clean_name.replace("application.", "")
            elif layer == "infrastructure":
                clean_name = clean_name.replace("infraestructure.", "")
            elif layer == "domain":
                clean_name = clean_name.replace("domain.", "")
            
            line = f"  {prefix}{clean_name} ({duration_str}) {status}"
            if extra_info:
                line += f" {extra_info}"
            
            print(line)
            processed.add(span.context.span_id)

    def _print_trace_summary(self, spans):
        """Imprime el resumen del trace"""
        total_duration = max([self._get_duration_ms(s) for s in spans]) if spans else 0
        ok_count = sum(1 for s in spans if getattr(s.status, "status_code", None) in (StatusCode.OK, StatusCode.UNSET))
        error_count = len(spans) - ok_count
        external_calls = sum(1 for s in spans if getattr(s, "kind", None) == SpanKind.CLIENT)
        
        print(f"\n📊 Summary: {self._format_duration(total_duration)} total | {ok_count} OK, {error_count} ERROR | {external_calls} external calls")

    def _print_trace(self, trace_id: str, spans):
        """Imprime el trace completo en formato por capas"""
        if not spans:
            return
        
        # Cabecera
        self._print_trace_header(trace_id, spans)
        
        # Agrupar por capas
        layers, span_tree = self._group_spans_by_layer(spans)
        
        # Imprimir cada capa que tenga spans
        layer_order = ["presentation", "application", "domain", "infrastructure"]
        for layer in layer_order:
            if layers[layer]:
                self._print_layer_spans(layers[layer], layer, span_tree)
        
        # Resumen
        if len(spans) > 1:
            self._print_trace_summary(spans)
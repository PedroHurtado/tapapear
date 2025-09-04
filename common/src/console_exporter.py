from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import StatusCode, SpanKind
from typing import Sequence
import time
from collections import defaultdict


class TreeConsoleSpanExporter(SpanExporter):
    """
    Exportador personalizado que muestra los spans en formato de árbol
    con iconos y información relevante. Detecta y elimina spans "envoltorio"
    redundantes (mismo nombre que el padre, status UNSET, sin atributos)
    para evitar duplicados en la salida.
    """

    def __init__(self, show_attributes=True, show_slow_only=False, min_duration_ms=0):
        self.show_attributes = show_attributes
        self.show_slow_only = show_slow_only
        self.min_duration_ms = min_duration_ms
        self.traces = defaultdict(list)

    def export(self, spans: Sequence) -> SpanExportResult:
        """Exporta los spans agrupándolos por trace_id"""
        for span in spans:
            trace_id = format(span.context.trace_id, "x")
            self.traces[trace_id].append(span)

        for trace_id, trace_spans in self.traces.items():
            self._print_trace(trace_id, trace_spans)

        self.traces.clear()
        return SpanExportResult.SUCCESS

    # ---------- Helpers para relaciones/validez ----------
    def _has_valid_parent(self, span, spans):
        """Comprueba si 'span' tiene un padre dentro de este conjunto de spans."""
        if not getattr(span, "parent", None):
            return False
        parent_id = getattr(span.parent, "span_id", None)
        return parent_id is not None and any(s.context.span_id == parent_id for s in spans)

    # ---------- Detección de spans redundantes ----------
    def _is_redundant_wrapper(self, child, parent):
        """
        Decide si 'child' es un wrapper redundante respecto a 'parent'.
        Condiciones a la vez (seguras en distintas versiones de OTEL):
        - mismo nombre
        - status UNSET
        - no es SpanKind.SERVER
        - no tiene atributos (evitamos eliminar spans con info importante)
        """
        try:
            same_name = (child.name == parent.name)
            status_unset = getattr(child.status, "status_code", None) == StatusCode.UNSET
            not_server = getattr(child, "kind", None) != SpanKind.SERVER
            no_attrs = not bool(getattr(child, "attributes", None))
            return same_name and status_unset and not_server and no_attrs
        except Exception:
            return False

    def _flatten_children(self, span, tree):
        """
        Devuelve la lista de hijos a mostrar: sustituye cualquier hijo redundante
        por sus propios hijos (recursivamente), eliminando así el wrapper.
        """
        children = list(tree.get(span.context.span_id, []))
        children.sort(key=lambda x: getattr(x, "start_time", 0))
        flat = []
        for child in children:
            if self._is_redundant_wrapper(child, span):
                # añadir los nietos en lugar del hijo redundante
                flat.extend(self._flatten_children(child, tree))
            else:
                flat.append(child)
        return flat

    # ---------- Construcción del árbol ----------
    def _build_span_tree(self, spans):
        """Construye un diccionario padre -> [hijos]"""
        tree = defaultdict(list)
        span_map = {span.context.span_id: span for span in spans}
        for span in spans:
            parent_id = getattr(span.parent, "span_id", None)
            if parent_id and parent_id in span_map:
                tree[parent_id].append(span)
        return tree

    # ---------- Impresión recursiva ----------
    def _print_span_tree(self, span, tree, prefix, is_last):
        """Imprime recursivamente el span y sus hijos (con flatten de wrappers)"""
        duration = self._get_duration_ms(span)
        if self.show_slow_only and duration < self.min_duration_ms:
            return

        connector = "└─" if is_last else "├─"
        icon = self._get_span_icon(span)
        status = self._get_status_display(span)
        duration_str = self._format_duration(duration)
        extra_info = self._get_extra_info(span)

        line = f"{prefix}{connector} {icon} {span.name} ({duration_str}) {status}"
        if extra_info:
            line += f" → {extra_info}"
        print(line)

        if self.show_attributes:
            self._print_span_attributes(span, prefix, is_last)

        # obtener hijos "flattened"
        children = self._flatten_children(span, tree)
        children.sort(key=lambda x: getattr(x, "start_time", 0))

        new_prefix = prefix + ("   " if is_last else "│  ")
        for i, child in enumerate(children):
            self._print_span_tree(child, tree, new_prefix, i == len(children) - 1)

    # ---------- Iconos / displays / utilidades ----------
    def _get_span_icon(self, span):
        name = (span.name or "").lower()
        if any(m in name for m in ["get", "post", "put", "delete", "patch"]):
            # marcar server root más claramente si se quiere más adelante
            return "🌐"
        elif "calcul" in name:
            return "🧮"
        elif "process" in name or "procesar" in name:
            return "⚙️"
        elif "database" in name or "db" in name:
            return "🗄️"
        elif "cache" in name:
            return "💾"
        elif "auth" in name:
            return "🔐"
        return "📡"

    def _get_status_display(self, span):
        code = getattr(span.status, "status_code", None)
        if code == StatusCode.OK:
            return "[✅ OK]"
        elif code == StatusCode.ERROR:
            return "[❌ ERROR]"
        return "[⚠️ UNSET]"

    def _get_duration_ms(self, span):
        if getattr(span, "end_time", None) and getattr(span, "start_time", None):
            return (span.end_time - span.start_time) / 1_000_000
        return 0

    def _format_duration(self, duration_ms):
        if duration_ms >= 1000:
            return f"{duration_ms/1000:.3f}s"
        elif duration_ms >= 1:
            return f"{duration_ms:.1f}ms"
        return f"{duration_ms*1000:.0f}μs"

    def _get_extra_info(self, span):
        attrs = getattr(span, "attributes", None) or {}
        # http
        if "http.method" in attrs and "http.status_code" in attrs:
            return f"{attrs['http.status_code']}"
        # calculadora
        if "calculator.operation" in attrs:
            op = attrs["calculator.operation"]
            operands = attrs.get("calculator.operands", "")
            result = attrs.get("calculator.result", "")
            if operands and result:
                return f"{op}({operands})={result}"
            return op
        # db
        if "db.statement" in attrs:
            stmt = attrs["db.statement"]
            return stmt[:50] + "..." if len(stmt) > 50 else stmt
        return ""

    def _print_span_attributes(self, span, prefix, is_last):
        attrs = getattr(span, "attributes", None) or {}
        relevant = {k: v for k, v in attrs.items() if k in ["user.id", "error.message", "http.url", "db.name"]}
        if relevant:
            attr_prefix = prefix + ("     " if is_last else "│    ")
            for k, v in relevant.items():
                print(f"{attr_prefix}• {k}: {v}")

    # ---------- Resumen del trace ----------
    def _print_trace_summary(self, spans):
        total = max([self._get_duration_ms(s) for s in spans]) if spans else 0
        ok_count = sum(1 for s in spans if getattr(s.status, "status_code", None) in (StatusCode.OK, StatusCode.UNSET))
        error_count = len(spans) - ok_count
        external_calls = sum(1 for s in spans if getattr(s, "kind", None) == SpanKind.CLIENT)
        slowest = max(spans, key=lambda s: self._get_duration_ms(s)) if spans else None

        print("📊 TRACE SUMMARY")
        print(f"├─ Total Duration: {self._format_duration(total)}")
        print(f"├─ Spans: {len(spans)} ({ok_count} OK, {error_count} ERROR)")
        print(f"├─ External Calls: {external_calls}")
        if slowest:
            print(f"└─ Slowest Operation: {slowest.name} ({self._format_duration(self._get_duration_ms(slowest))})")
        else:
            print("└─ Slowest Operation: -")

    # ---------- Punto de entrada para imprimir cada trace ----------
    def _print_trace(self, trace_id: str, spans):
        span_tree = self._build_span_tree(spans)
        print(f"\n🔍 TRACE: {trace_id[:8]}...{trace_id[-8:]}")

        # Preferir SpanKind.SERVER como raíz; si no existe, usar spans sin padre válido
        root_spans = [s for s in spans if getattr(s, "kind", None) == SpanKind.SERVER]
        if not root_spans:
            root_spans = [s for s in spans if not self._has_valid_parent(s, spans)]

        root_spans.sort(key=lambda s: getattr(s, "start_time", 0))
        for i, root_span in enumerate(root_spans):
            self._print_span_tree(root_span, span_tree, "", i == len(root_spans) - 1)

        if len(spans) > 1:
            self._print_trace_summary(spans)


# Función para configurar el exportador
def setup_console_tracing(show_attributes=True, show_slow_only=False, min_duration_ms=0):
    """
    Configura el trazado con el exportador de consola personalizado
    """
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    trace.set_tracer_provider(TracerProvider())
    exporter = TreeConsoleSpanExporter(
        show_attributes=show_attributes,
        show_slow_only=show_slow_only,
        min_duration_ms=min_duration_ms,
    )
    processor = BatchSpanProcessor(exporter)
    trace.get_tracer_provider().add_span_processor(processor)
    return trace.get_tracer(__name__)


# Ejemplo de uso / demo
if __name__ == "__main__":
    tracer = setup_console_tracing(show_attributes=True)

    # Simulación: server span + wrapper internal con mismo nombre + hijos
    with tracer.start_as_current_span("POST /test", kind=SpanKind.SERVER) as root:
        root.set_attribute("http.method", "POST")
        root.set_attribute("http.url", "http://127.0.0.1:8080/test")
        root.set_attribute("http.status_code", 200)

        # wrapper interno redundante (misma name, status UNSET, sin attrs) — será aplanado
        with tracer.start_as_current_span("POST /test") as wrapper:
            # hija real con contenido
            with tracer.start_as_current_span("procesar") as proc:
                proc.set_attribute("method_name", "procesar")
                with tracer.start_as_current_span("calcular") as calc:
                    calc.set_attribute("calculator.operation", "suma")
                    calc.set_attribute("calculator.operands", "5.0,7.0")
                    calc.set_attribute("calculator.result", "12.0")
                    time.sleep(0.00002)

        # llamada externa
        with tracer.start_as_current_span("GET", kind=SpanKind.CLIENT) as http_span:
            http_span.set_attribute(
                "http.url",
                "https://my-json-server.typicode.com/typicode/demo/posts/1",
            )
            http_span.set_attribute("http.method", "GET")
            http_span.set_attribute("http.status_code", 200)
            time.sleep(0.1)

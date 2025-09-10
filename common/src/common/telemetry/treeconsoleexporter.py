from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import StatusCode, SpanKind
from typing import Sequence
from collections import defaultdict


class TreeConsoleSpanExporter(SpanExporter):
    """
    Exportador de spans para desarrollo:
    - Flujo lineal: Presentation → Application → Domain → Infrastructure
    - Solo indentación cuando Infrastructure dispara un evento hacia Application
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

    # ---------- Helpers ----------
    def _get_layer(self, span):
        if getattr(span, "kind", None) == SpanKind.SERVER:
            return "presentation"
        name = getattr(span, "name", "").lower()
        if name.startswith("application."):
            return "application"
        elif name.startswith("domain."):
            return "domain"
        elif name.startswith("infrastructure."):
            return "infrastructure"
        else:
            return "unknown"

    def _get_layer_icon_name(self, layer):
        return {
            "presentation": ("🌐", "PRESENTATION LAYER"),
            "application": ("⚙️", "APPLICATION LAYER"),
            "domain": ("🏛️", "DOMAIN LAYER"),
            "infrastructure": ("🔧", "INFRASTRUCTURE LAYER"),
            "unknown": ("📡", "UNKNOWN LAYER")
        }.get(layer, ("📡", "UNKNOWN LAYER"))

    def _duration_ms(self, span):
        if getattr(span, "end_time", None) and getattr(span, "start_time", None):
            return (span.end_time - span.start_time) / 1_000_000
        return 0

    def _format_duration(self, ms):
        if ms >= 1000:
            return f"{ms/1000:.3f}s"
        elif ms >= 1:
            return f"{ms:.1f}ms"
        return f"{ms*1000:.0f}μs"

    def _status_display(self, span):
        code = getattr(span.status, "status_code", None)
        if code == StatusCode.OK:
            return "[✅ OK]"
        elif code == StatusCode.ERROR:
            return "[❌ ERROR]"
        return "[⚠️ UNSET]"

    def _print_attributes(self, span, indent):
        if not self.show_attributes:
            return
        attrs = getattr(span, "attributes", {}) or {}
        for k, v in attrs.items():
            print(f"{indent}· {k}: {v}")

    def _build_span_tree(self, spans):
        tree = defaultdict(list)
        span_map = {span.context.span_id: span for span in spans}
        for span in spans:
            parent_id = getattr(span.parent, "span_id", None)
            if parent_id and parent_id in span_map:
                tree[parent_id].append(span)
        return tree

    # ---------- Printing ----------
    def _print_trace(self, trace_id, spans):
        if not spans:
            return

        print(f"\n🔍 TRACE: {trace_id[:8]}...{trace_id[-8:]} | {self._format_duration(max(self._duration_ms(s) for s in spans))} | {len(spans)} spans")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        tree = self._build_span_tree(spans)
        self._print_layer_linear(spans, tree)

    def _print_layer_linear(self, spans, tree, indent="", parent_layer=None):
        """
        Imprime los spans linealmente: Presentation → Application → Domain → Infrastructure
        Solo indentación de Application cuando viene desde Infrastructure
        """
        layer_order = ["presentation", "application", "domain", "infrastructure"]
        printed = set()

        def print_span(span, indent_level="", parent_layer=None):
            if span.context.span_id in printed:
                return
            printed.add(span.context.span_id)

            layer = self._get_layer(span)
            icon, _ = self._get_layer_icon_name(layer)
            clean_name = span.name
            for prefix in ["presentation.", "application.", "domain.", "infraestructure.", "infrastructure.", "repository.", "firestore."]:
                clean_name = clean_name.replace(prefix, "")

            line = f"{indent_level}{clean_name} ({self._format_duration(self._duration_ms(span))}) {self._status_display(span)}"
            extra = self._get_extra_info(span)
            if extra:
                line += f" {extra}"
            print(line)

            self._print_attributes(span, indent_level + "  ")

            # Recursión para hijos, solo indent Application desde Infrastructure
            children = tree.get(span.context.span_id, [])
            for child in sorted(children, key=lambda s: getattr(s, "start_time", 0)):
                next_indent = indent_level
                if layer == "infrastructure" and self._get_layer(child) == "application":
                    next_indent += "  "
                print_span(child, next_indent, layer)

        # Empezamos por Presentation
        for layer in layer_order:
            layer_spans = [s for s in spans if self._get_layer(s) == layer and getattr(s.parent, "span_id", None) is None]
            if not layer_spans:
                continue
            icon, layer_name = self._get_layer_icon_name(layer)
            print(f"\n{icon} {layer_name}")
            for span in sorted(layer_spans, key=lambda s: getattr(s, "start_time", 0)):
                print_span(span, "  ")

    def _get_extra_info(self, span):
        attrs = getattr(span, "attributes", {}) or {}
        # HTTP
        if "http.method" in attrs and "http.status_code" in attrs and "http.url" in attrs:
            return f"→ {attrs['http.status_code']} | {attrs['http.url']}"
        # Mediator send
        if "mediator.command.type" in attrs and ("mediator.send" in getattr(span, "name", "")):
            return f"→ {attrs['mediator.command.type']}"
        # Handlers
        if "mediator.handler.name" in attrs:
            return attrs["mediator.handler.name"]
        # Pipeline
        if "mediator.pipeline.name" in attrs:
            return attrs["mediator.pipeline.name"]
        # Domain entities
        if "entity.id" in attrs:
            return f"→ {attrs['entity.id']}"
        return ""

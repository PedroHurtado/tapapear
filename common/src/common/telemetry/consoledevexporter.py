from typing import Sequence
import os
import platform
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import SpanKind
from opentelemetry.sdk.trace import ReadableSpan
from collections import defaultdict


class ConsoleDevExporter(SpanExporter):
    """
    SpanExporter que muestra spans por capas de arquitectura en consola,
    con formato amigable para desarrollo.
    """

    ICONS = {
        "Api": "🌐",
        "Application": "⚙️",
        "Domain": "🏛",
        "Infrastructure": "💾",
    }

    STATUS_ICONS = {
        "OK": "\033[92m✅ OK\033[0m",
        "ERROR": "\033[91m❌ ERROR\033[0m",
        "UNSET": "\033[93m⚠️  UNSET\033[0m",
    }

    COLOR_TRACE = "\033[95m"
    COLOR_ATTR = "\033[90m"  # gris tenue
    COLOR_RESET = "\033[0m"

    def __init__(self, show_attributes: bool = False, clear_console: bool = True):
        self.spans_by_trace = defaultdict(list)
        self.show_attributes = show_attributes
        self.clear_console = clear_console

    def _clear_console(self):
        """
        Limpia la consola y mueve el cursor al principio de manera multiplataforma.
        """
        if not self.clear_console:
            return
            
        try:
            # Detectar el sistema operativo y usar el comando apropiado
            if platform.system() == "Windows":
                os.system('cls')
            else:
                # Unix/Linux/MacOS
                os.system('clear')
        except Exception:
            pass
        
        # Asegurar que el cursor esté al principio usando secuencias ANSI
        # \033[2J - Limpia toda la pantalla
        # \033[H - Mueve el cursor a la posición (1,1) 
        # \033[3J - Limpia el buffer de scroll (en terminales que lo soporten)
        print('\033[2J\033[3J\033[H', end='', flush=True)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        try:
            for span in spans:
                trace_id = span.get_span_context().trace_id
                self.spans_by_trace[trace_id].append(span)

            for trace_id, trace_spans in list(self.spans_by_trace.items()):
                if self._is_trace_complete(trace_spans):
                    self._process_trace(trace_id, trace_spans)
                    del self.spans_by_trace[trace_id]

            return SpanExportResult.SUCCESS

        except Exception as e:
            print(f"Error exporting spans: {e}")
            return SpanExportResult.FAILURE

    def _is_trace_complete(self, spans: list) -> bool:
        return all(span.end_time is not None for span in spans)

    def _format_duration(self, duration: float) -> str:
        """
        Formatea duración en la unidad más adecuada:
        - segundos (s)
        - milisegundos (ms)
        - microsegundos (µs)
        - nanosegundos (ns)
        """
        if duration >= 1000:
            return f"{duration / 1000:.1f} s"
        if duration >= 1:
            return f"{duration:.1f} ms"
        if duration >= 0.001:
            return f"{duration * 1000:.0f} µs"
        return f"{duration * 1_000_000:.0f} ns"

    def _calculate_duration_ms(self, span: ReadableSpan) -> float:
        if span.end_time is None or span.start_time is None:
            return 0.0
        return (span.end_time - span.start_time) / 1_000_000

    def _get_layer(self, span: ReadableSpan) -> str:
        if span.kind == SpanKind.SERVER:
            return "Api"
        name = getattr(span, "name", "")
        return name.split(".")[0].capitalize() if "." in name else name.capitalize()

    def _status_icon(self, span: ReadableSpan) -> str:
        code = span.status.status_code.name
        return self.STATUS_ICONS.get(code, code)

    def _clean_span_name(self, span_name: str) -> str:
        """
        Limpia prefijos redundantes de los nombres de spans.
        """
        for prefix in ["application.", "domain.", "infrastructure."]:
            if span_name.startswith(prefix):
                return span_name[len(prefix):]
        return span_name

    def _process_trace(self, trace_id: int, spans: list):
        # Limpiar la consola antes de mostrar la nueva traza
        self._clear_console()
        
        spans_sorted = sorted(spans, key=lambda s: s.start_time)

        print(f"\n{self.COLOR_TRACE}📌 Trace ID: {hex(trace_id)}{self.COLOR_RESET}")
        print("═" * 65)

        last_layer = None
        stats = {"OK": 0, "ERROR": 0, "UNSET": 0}
        fastest, slowest = None, None

        # Encontrar el primer span (API) y el span más lento excluyendo el primero
        api_span = spans_sorted[0] if spans_sorted else None
        non_api_spans = spans_sorted[1:] if len(spans_sorted) > 1 else []
        
        max_name_len = max(len(self._clean_span_name(span.name)) for span in spans_sorted) + 30

        for span in spans_sorted:
            layer = self._get_layer(span)
            duration = self._calculate_duration_ms(span)
            status = span.status.status_code.name
            stats[status] = stats.get(status, 0) + 1

            if fastest is None or duration < fastest[1]:
                fastest = (span, duration)
            if slowest is None or duration > slowest[1]:
                slowest = (span, duration)

            # Header de capa (espacio fijo después del icono)
            if layer != last_layer:
                icon = self.ICONS.get(layer, "🔹")
                print(f"\n{icon}  {layer}\n")
                last_layer = layer

            clean_name = self._clean_span_name(span.name)
            duration_str = self._format_duration(duration)

            print(
                f"   {clean_name:<{max_name_len}} ⏱ {duration_str:>7}   {self._status_icon(span)}"
            )

            # Mostrar atributos debajo si está activado
            if self.show_attributes:
                attributes = getattr(span, "attributes", {}) or {}
                if attributes:
                    print()  # línea en blanco de separación
                    for key, value in attributes.items():
                        print(f"      {self.COLOR_ATTR}• {key}: {value}{self.COLOR_RESET}")
                    print()  # otra línea en blanco para separar del siguiente span

        # Summary
        print("\n" + "═" * 65)
        print("📊 Summary")

        # Información del API (primer span) - primera línea
        if api_span:
            attributes = getattr(api_span, "attributes", {}) or {}
            method = attributes.get("http.method", "")
            url = attributes.get("http.url", "")
            status_code = attributes.get("http.status_code", "")
            
            api_info = f"{method} {url}"
            if status_code:
                api_info += f" {status_code}"
            print(api_info)
            print()  # Salto de línea

        # Total duration
        total_duration = self._calculate_duration_ms(spans_sorted[0]) if spans_sorted else 0.0
        print(f"   • Total duration: {self._format_duration(total_duration)}")

        # Fastest y Slowest juntos
        if fastest:
            print(
                f"   • Fastest block: {self._clean_span_name(fastest[0].name)} "
                f"({self._format_duration(fastest[1])})"
            )

        if non_api_spans:
            slowest_non_api = max(non_api_spans, key=lambda s: self._calculate_duration_ms(s))
            slowest_duration = self._calculate_duration_ms(slowest_non_api)
            print(
                f"   • Slowest operation: {self._clean_span_name(slowest_non_api.name)} "
                f"({self._format_duration(slowest_duration)})"
            )

        print("   • Status:")
        for k, v in stats.items():
            if v > 0:
                print(f"       {self.STATUS_ICONS.get(k, k)}: {v}")

        final_status = "ERROR" if stats.get("ERROR", 0) > 0 else "OK"
        print(f"   • Final result: {self.STATUS_ICONS.get(final_status)}")
        print("═" * 65)

    def shutdown(self) -> None:
        self.spans_by_trace.clear()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        try:
            for trace_id, spans in list(self.spans_by_trace.items()):
                self._process_trace(trace_id, spans)
            self.spans_by_trace.clear()
            return True
        except Exception:
            return False
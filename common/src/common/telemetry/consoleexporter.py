from typing import Sequence, Dict, Optional, List, Tuple, Any
import os
import platform
from abc import ABC, abstractmethod
from dataclasses import dataclass
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import SpanKind
from opentelemetry.sdk.trace import ReadableSpan
from collections import defaultdict


@dataclass
class UserInfo:
    """Información del usuario extraída de los spans."""
    user_id: Optional[str] = None
    username: Optional[str] = None
    role: Optional[str] = None
    tenant_id: Optional[str] = None

    @property
    def has_user_data(self) -> bool:
        return any([self.user_id, self.username, self.role, self.tenant_id])


@dataclass
class ExternalCallInfo:
    """Información de llamadas externas."""
    info: str
    duration: float
    status: str


@dataclass
class TraceStats:
    """Estadísticas de la traza."""
    status_counts: Dict[str, int]
    total_duration: float
    fastest_span: Optional[Tuple[ReadableSpan, float]]
    slowest_operation: Optional[Tuple[ReadableSpan, float]]
    external_calls: List[ExternalCallInfo]
    user_info: UserInfo


class ConsoleFormatter(ABC):
    """Interfaz para formatear la salida de consola."""
    
    @abstractmethod
    def format_duration(self, duration: float) -> str:
        pass
    
    @abstractmethod
    def format_status(self, status: str) -> str:
        pass


class ColorFormatter(ConsoleFormatter):
    """Formateador con colores ANSI."""
    
    STATUS_ICONS = {
        "OK": "\033[92m✅ OK\033[0m",
        "ERROR": "\033[91m❌ ERROR\033[0m",
        "UNSET": "\033[93m⚠️  UNSET\033[0m",
    }
    
    COLOR_TRACE = "\033[95m"
    COLOR_ATTR = "\033[90m"
    COLOR_RESET = "\033[0m"
    
    def format_duration(self, duration: float) -> str:
        """Formatea duración en la unidad más adecuada."""
        if duration >= 1000:
            return f"{duration / 1000:.1f} s"
        if duration >= 1:
            return f"{duration:.1f} ms"
        if duration >= 0.001:
            return f"{duration * 1000:.0f} µs"
        return f"{duration * 1_000_000:.0f} ns"
    
    def format_status(self, status: str) -> str:
        return self.STATUS_ICONS.get(status, status)


class SpanProcessor:
    """Procesador de spans que extrae información relevante."""
    
    ICONS = {
        "Api": "🌐",
        "Application": "⚙️",
        "Domain": "🏛",
        "Infrastructure": "💾",
        "External": "🔗",
    }
    
    def __init__(self, formatter: ConsoleFormatter):
        self.formatter = formatter
    
    def get_layer(self, span: ReadableSpan) -> str:
        """Determina la capa arquitectónica del span."""
        if span.kind == SpanKind.CLIENT:
            return "External"
        if span.kind == SpanKind.SERVER:
            return "Api"
        
        name = getattr(span, "name", "")
        return name.split(".")[0].capitalize() if "." in name else name.capitalize()
    
    def clean_span_name(self, span_name: str) -> str:
        """Limpia prefijos redundantes de los nombres de spans."""
        prefixes = ["application.", "domain.", "infrastructure."]
        for prefix in prefixes:
            if span_name.startswith(prefix):
                return span_name[len(prefix):]
        return span_name
    
    def calculate_duration_ms(self, span: ReadableSpan) -> float:
        """Calcula la duración del span en milisegundos."""
        if span.end_time is None or span.start_time is None:
            return 0.0
        return (span.end_time - span.start_time) / 1_000_000
    
    def extract_external_call_info(self, span: ReadableSpan) -> str:
        """Extrae información de llamadas externas."""
        attributes = getattr(span, "attributes", {}) or {}
        
        # HTTP calls
        if "http.method" in attributes and "http.url" in attributes:
            method = attributes.get("http.method", "")
            url = attributes.get("http.url", "")
            status_code = attributes.get("http.status_code", "")
            info = f"{method} {url}"
            if status_code:
                info += f" ({status_code})"
            return info
        
        # Database calls
        if "db.statement" in attributes:
            db_name = attributes.get("db.name", "")
            db_type = attributes.get("db.system", "")
            statement = attributes.get("db.statement", "")[:50]
            info = f"DB: {db_type}"
            if db_name:
                info += f"/{db_name}"
            if statement:
                info += f" - {statement}..."
            return info
        
        # RPC calls
        if "rpc.service" in attributes:
            service = attributes.get("rpc.service", "")
            method = attributes.get("rpc.method", "")
            return f"RPC: {service}.{method}" if method else f"RPC: {service}"
        
        return span.name
    
    def extract_user_info(self, spans: List[ReadableSpan]) -> UserInfo:
        """Extrae información del usuario de los spans."""
        user_info = UserInfo()
        
        for span in spans:
            attributes = getattr(span, "attributes", {}) or {}
            
            if not user_info.user_id and "enduser.id" in attributes:
                user_info.user_id = attributes["enduser.id"]
            
            if not user_info.username and "user.username" in attributes:
                user_info.username = attributes["user.username"]
            
            if not user_info.role and "user.role" in attributes:
                user_info.role = attributes["user.role"]
            
            if not user_info.tenant_id and "app.tenant.id" in attributes:
                user_info.tenant_id = attributes["app.tenant.id"]
            
            # Si ya tenemos toda la información, no necesitamos seguir buscando
            if all([user_info.user_id, user_info.username, user_info.role, user_info.tenant_id]):
                break
        
        return user_info


class TraceAnalyzer:
    """Analizador de trazas que genera estadísticas."""
    
    def __init__(self, processor: SpanProcessor):
        self.processor = processor
    
    def analyze_trace(self, spans: List[ReadableSpan]) -> TraceStats:
        """Analiza una traza completa y genera estadísticas."""
        spans_sorted = sorted(spans, key=lambda s: s.start_time)
        
        stats = TraceStats(
            status_counts=defaultdict(int),
            total_duration=0.0,
            fastest_span=None,
            slowest_operation=None,
            external_calls=[],
            user_info=self.processor.extract_user_info(spans)
        )
        
        # Primer span para duración total
        if spans_sorted:
            stats.total_duration = self.processor.calculate_duration_ms(spans_sorted[0])
        
        # Spans no-API para encontrar la operación más lenta
        non_api_spans = spans_sorted[1:] if len(spans_sorted) > 1 else []
        
        for span in spans_sorted:
            layer = self.processor.get_layer(span)
            duration = self.processor.calculate_duration_ms(span)
            status = span.status.status_code.name
            
            stats.status_counts[status] += 1
            
            # Llamadas externas
            if layer == "External":
                external_info = self.processor.extract_external_call_info(span)
                stats.external_calls.append(
                    ExternalCallInfo(external_info, duration, status)
                )
            
            # Span más rápido
            if stats.fastest_span is None or duration < stats.fastest_span[1]:
                stats.fastest_span = (span, duration)
        
        # Operación más lenta (excluyendo API)
        if non_api_spans:
            slowest_span = max(non_api_spans, key=self.processor.calculate_duration_ms)
            slowest_duration = self.processor.calculate_duration_ms(slowest_span)
            stats.slowest_operation = (slowest_span, slowest_duration)
        
        return stats


class ConsoleRenderer:
    """Renderizador de salida de consola."""
    
    def __init__(self, formatter: ColorFormatter, processor: SpanProcessor):
        self.formatter = formatter
        self.processor = processor
    
    def render_trace(self, trace_id: int, spans: List[ReadableSpan], 
                    stats: TraceStats, show_attributes: bool = False):
        """Renderiza una traza completa en consola."""
        spans_sorted = sorted(spans, key=lambda s: s.start_time)
        
        print(f"\n{self.formatter.COLOR_TRACE}📌 Trace ID: {hex(trace_id)}{self.formatter.COLOR_RESET}")
        print("═" * 70)
        
        self._render_user_info(stats.user_info)
        self._render_spans(spans_sorted, show_attributes)
        self._render_summary(spans_sorted, stats)
    
    def _render_user_info(self, user_info: UserInfo):
        """Renderiza información del usuario si está disponible."""
        if not user_info.has_user_data:
            return
        
        print(f"👤 User Information")
        
        info_parts = []
        if user_info.username:
            info_parts.append(f"@{user_info.username}")
        if user_info.role:
            info_parts.append(f"role:{user_info.role}")
        if user_info.tenant_id:
            info_parts.append(f"tenant:{user_info.tenant_id}")
        if user_info.user_id and user_info.user_id != user_info.username:
            info_parts.append(f"id:{user_info.user_id}")
        
        if info_parts:
            print(f"   {' | '.join(info_parts)}")
        
        print("─" * 70)
    
    def _render_spans(self, spans: List[ReadableSpan], show_attributes: bool):
        """Renderiza los spans organizados por capas."""
        last_layer = None
        max_name_len = max(len(self.processor.clean_span_name(span.name)) for span in spans) + 30
        
        for span in spans:
            layer = self.processor.get_layer(span)
            duration = self.processor.calculate_duration_ms(span)
            
            # Header de capa
            if layer != last_layer:
                icon = self.processor.ICONS.get(layer, "🔹")
                print(f"\n{icon}  {layer}\n")
                last_layer = layer
            
            clean_name = self.processor.clean_span_name(span.name)
            duration_str = self.formatter.format_duration(duration)
            status_str = self.formatter.format_status(span.status.status_code.name)
            
            print(f"   {clean_name:<{max_name_len}} ⏱ {duration_str:>7}   {status_str}")
            
            if show_attributes:
                self._render_attributes(span)
    
    def _render_attributes(self, span: ReadableSpan):
        """Renderiza los atributos del span."""
        attributes = getattr(span, "attributes", {}) or {}
        if attributes:
            print()
            for key, value in attributes.items():
                print(f"      {self.formatter.COLOR_ATTR}• {key}: {value}{self.formatter.COLOR_RESET}")
            print()
    
    def _render_summary(self, spans: List[ReadableSpan], stats: TraceStats):
        """Renderiza el resumen de la traza."""
        print("\n" + "═" * 70)
        print("📊 Summary")
        
        # API info (primer span)
        if spans:
            self._render_api_info(spans[0])
        
        # Métricas de rendimiento
        print(f"   • Total duration: {self.formatter.format_duration(stats.total_duration)}")
        
        if stats.fastest_span:
            span, duration = stats.fastest_span
            print(f"   • Fastest block: {self.processor.clean_span_name(span.name)} "
                  f"({self.formatter.format_duration(duration)})")
        
        if stats.slowest_operation:
            span, duration = stats.slowest_operation
            print(f"   • Slowest operation: {self.processor.clean_span_name(span.name)} "
                  f"({self.formatter.format_duration(duration)})")
        
        # Llamadas externas
        if stats.external_calls:
            print("   • External calls:")
            for call in stats.external_calls:
                status_icon = "✅" if call.status == "OK" else "❌" if call.status == "ERROR" else "⚠️"
                print(f"       {status_icon} {call.info} ({self.formatter.format_duration(call.duration)})")
        
        # Estados
        print("   • Status:")
        for status, count in stats.status_counts.items():
            if count > 0:
                print(f"       {self.formatter.format_status(status)}: {count}")
        
        # Resultado final
        final_status = "ERROR" if stats.status_counts.get("ERROR", 0) > 0 else "OK"
        print(f"   • Final result: {self.formatter.format_status(final_status)}")
        print("═" * 70)
        
        # Información del usuario al final
        self._render_user_info_footer(stats.user_info)
    
    def _render_user_info_footer(self, user_info: UserInfo):
        """Renderiza información del usuario al final del summary."""
        if not user_info.has_user_data:
            return
        
        print(f"👤 User Information")
        
        info_parts = []
        if user_info.role:
            info_parts.append(f"role:{user_info.role}")
        if user_info.tenant_id:
            info_parts.append(f"tenant:{user_info.tenant_id}")
        if user_info.user_id:
            info_parts.append(f"id:{user_info.user_id}")
        
        if info_parts:
            print(f"   {' | '.join(info_parts)}")
        
        print("─" * 70)
    
    def _render_api_info(self, api_span: ReadableSpan):
        """Renderiza información del endpoint API."""
        attributes = getattr(api_span, "attributes", {}) or {}
        method = attributes.get("http.method", "")
        url = attributes.get("http.url", "")
        status_code = attributes.get("http.status_code", "")
        
        if method and url:
            api_info = f"{method} {url}"
            if status_code:
                api_info += f" {status_code}"
            print(api_info)
            print()


class ConsoleCleaner:
    """Responsable de limpiar la consola."""
    
    @staticmethod
    def clear_console():
        """Limpia la consola de manera multiplataforma."""
        try:
            if platform.system() == "Windows":
                os.system('cls')
            else:
                os.system('clear')
        except Exception:
            pass
        
        # Secuencias ANSI para asegurar limpieza completa
        print('\033[2J\033[3J\033[H', end='', flush=True)


class ConsoleExporter(SpanExporter):
    """
    SpanExporter que muestra spans por capas de arquitectura en consola,
    con formato amigable para desarrollo.
    
    Refactorizado aplicando principios SOLID:
    - Single Responsibility: Cada clase tiene una responsabilidad específica
    - Open/Closed: Extensible a través de interfaces
    - Liskov Substitution: Implementaciones intercambiables
    - Interface Segregation: Interfaces específicas y cohesivas
    - Dependency Inversion: Depende de abstracciones, no de concreciones
    """
    
    def __init__(self, show_attributes: bool = False, clear_console: bool = True):
        self.spans_by_trace = defaultdict(list)
        self.show_attributes = show_attributes
        self.clear_console = clear_console
        
        # Inyección de dependencias
        formatter = ColorFormatter()
        processor = SpanProcessor(formatter)
        self.analyzer = TraceAnalyzer(processor)
        self.renderer = ConsoleRenderer(formatter, processor)
    
    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Exporta spans y procesa trazas completas."""
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
    
    def _is_trace_complete(self, spans: List[ReadableSpan]) -> bool:
        """Verifica si una traza está completa."""
        return all(span.end_time is not None for span in spans)
    
    def _process_trace(self, trace_id: int, spans: List[ReadableSpan]):
        """Procesa y renderiza una traza completa."""
        if self.clear_console:
            ConsoleCleaner.clear_console()
        
        stats = self.analyzer.analyze_trace(spans)
        self.renderer.render_trace(trace_id, spans, stats, self.show_attributes)
    
    def shutdown(self) -> None:
        """Limpia recursos al cerrar."""
        self.spans_by_trace.clear()
    
    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Fuerza el procesamiento de todas las trazas pendientes."""
        try:
            for trace_id, spans in list(self.spans_by_trace.items()):
                stats = self.analyzer.analyze_trace(spans)
                self.renderer.render_trace(trace_id, spans, stats, self.show_attributes)
            self.spans_by_trace.clear()
            return True
        except Exception:
            return False
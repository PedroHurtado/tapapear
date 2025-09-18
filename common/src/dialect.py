from typing import List, Dict, Any
from datetime import datetime
import json

from common.infrastructure.unit_of_work import DatabaseDialect, AbstractCommand


class ConsoleDialect(DatabaseDialect):
    """Dialecto que muestra los comandos en consola en lugar de ejecutarlos"""
    
    def __init__(self, db=None, transaction=None):
        super().__init__(db, transaction)
        self.db_name = "🔥 Firestore DB (Mock)" if db is None else str(db)
        self.transaction_name = "📦 Transaction (Mock)" if transaction else "🚫 No Transaction"
        self.command_count = 0
    
    def execute_commands(self, commands: List[AbstractCommand]) -> None:
        """Muestra los comandos en consola con formato bonito"""
        if not commands:
            print("✅ No commands to execute")
            return
        
        print(f"\n{'='*60}")
        print(f"🚀 EXECUTING {len(commands)} COMMANDS")
        print(f"🔗 Database: {self.db_name}")
        print(f"📦 Transaction: {self.transaction_name}")
        print(f"⏰ Started at: {datetime.now().strftime('%H:%M:%S')}")
        print(f"{'='*60}")
        
        for i, command in enumerate(commands, 1):
            self.command_count += 1
            
            print(f"\n[{i:02d}/{len(commands)}] Command #{self.command_count}")
            print(f"{'─'*50}")
            print(self._format_command(command))
            print(f"🔥 Firestore: {self._to_firestore_command(command)}")
        
        print(f"\n{'='*60}")
        print(f"✅ EXECUTION COMPLETED")
        print(f"📊 Total commands executed: {len(commands)}")
        print(f"⏰ Finished at: {datetime.now().strftime('%H:%M:%S')}")
        print(f"{'='*60}\n")
    
    def _format_command(self, command: AbstractCommand) -> str:
        """Formatea un comando para mostrar en consola"""
        indent = "  " * command.level
        data_preview = self._format_data(command.data) if command.data else "{}"
        
        return (f"{indent}📝 {command.operation} → {command.entity_path}\n"
               f"{indent}   Level: {command.level}\n"
               f"{indent}   Data: {data_preview}")
    
    def _format_data(self, data: Dict[str, Any]) -> str:
        """Formatea los datos para mostrar"""
        if not data:
            return "{}"
        
        # Limitar la salida para evitar spam en consola
        if len(str(data)) > 200:
            preview = {k: "..." if len(str(v)) > 50 else v for k, v in list(data.items())[:3]}
            if len(data) > 3:
                preview["..."] = f"and {len(data) - 3} more fields"
            return json.dumps(preview, default=str, separators=(',', ':'))
        
        return json.dumps(data, default=str, separators=(',', ':'))
    
    def _to_firestore_command(self, command: AbstractCommand) -> str:
        """Convierte a sintaxis de comando Firestore"""
        path_parts = command.entity_path.split('/')
        
        # Construir referencia estilo Firestore
        firestore_ref = "db"
        for i in range(0, len(path_parts), 2):
            if i < len(path_parts):
                firestore_ref += f".collection('{path_parts[i]}')"
            if i + 1 < len(path_parts):
                firestore_ref += f".document('{path_parts[i + 1]}')"
        
        # Generar comando según operación
        if command.operation == "CREATE":
            data_str = self._format_data(command.data)
            return f"{firestore_ref}.create({data_str})"
        elif command.operation == "UPDATE":
            data_str = self._format_data(command.data)
            return f"{firestore_ref}.update({data_str})"
        elif command.operation == "DELETE":
            return f"{firestore_ref}.delete()"
        else:
            return f"{firestore_ref}.{command.operation.lower()}(...)"


class VerboseConsoleDialect(ConsoleDialect):
    """Versión más detallada del dialecto de consola con análisis profundo"""
    
    def execute_commands(self, commands: List[AbstractCommand]) -> None:
        """Versión extra verbosa para debugging profundo"""
        if not commands:
            print("✅ No commands to execute")
            return
        
        # Análisis previo
        self._print_pre_analysis(commands)
        
        # Ejecutar comandos normalmente
        super().execute_commands(commands)
        
        # Post-análisis
        self._print_post_analysis(commands)
    
    def _print_pre_analysis(self, commands: List[AbstractCommand]) -> None:
        """Imprime análisis previo de los comandos"""
        operations = {}
        levels = {}
        paths = {}
        
        for cmd in commands:
            # Contar operaciones
            operations[cmd.operation] = operations.get(cmd.operation, 0) + 1
            
            # Contar niveles
            levels[cmd.level] = levels.get(cmd.level, 0) + 1
            
            # Analizar collections
            path_parts = cmd.entity_path.split('/')
            for i in range(0, len(path_parts), 2):
                if i < len(path_parts):
                    collection = path_parts[i]
                    paths[collection] = paths.get(collection, 0) + 1
        
        print(f"\n{'🔍 COMMAND ANALYSIS':=^80}")
        print(f"📊 Operations breakdown:")
        for op, count in sorted(operations.items()):
            emoji = {"CREATE": "➕", "UPDATE": "✏️", "DELETE": "🗑️"}.get(op, "🔄")
            print(f"   {emoji} {op}: {count} commands")
        
        print(f"\n📏 Hierarchy levels:")
        for level, count in sorted(levels.items()):
            indent = "  " * level
            print(f"   {indent}📁 Level {level}: {count} documents")
        
        print(f"\n🗂️ Collections affected:")
        for collection, count in sorted(paths.items()):
            print(f"   📋 {collection}: {count} operations")
        
        print(f"{'='*80}")
    
    def _print_post_analysis(self, commands: List[AbstractCommand]) -> None:
        """Imprime análisis posterior de los comandos"""
        if not commands:
            return
        
        operations = {}
        max_level = 0
        
        for cmd in commands:
            operations[cmd.operation] = operations.get(cmd.operation, 0) + 1
            max_level = max(max_level, cmd.level)
        
        print(f"{'📋 EXECUTION SUMMARY':=^80}")
        print(f"🎯 Execution strategy: {'Transactional' if self.transaction != '🚫 No Transaction' else 'Individual operations'}")
        print(f"🏗️ Architecture: Document hierarchy with {max_level + 1} levels")
        
        change_pattern = []
        for op, count in operations.items():
            emoji = {"CREATE": "➕", "UPDATE": "✏️", "DELETE": "🗑️"}.get(op, "🔄")
            change_pattern.append(f"{emoji}{count} {op.lower()}{'s' if count != 1 else ''}")
        
        print(f"🔄 Change pattern: {', '.join(change_pattern)}")
        print(f"⚡ Performance: {len(commands)} operations in single transaction")
        print(f"{'='*80}\n")
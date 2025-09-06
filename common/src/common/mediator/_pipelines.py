from common.ioc import component
from ._mediator import CommandPipeLine, PipelineContext, ordered
from typing import Callable, Any


@component
@ordered(5)
class LogggerPipeLine(CommandPipeLine):
    
    async def handler(self, context: PipelineContext, next_handler: Callable[[], Any]) -> Any:       
        return await next_handler()       
        




from common.ioc import component
from ._command import PipeLine, PipelineContext, ordered
from typing import Callable, Any


@component
@ordered(5)
class LogggerPipeLine(PipeLine):
    
    async def handler(self, context: PipelineContext, next_handler: Callable[[], Any]) -> Any:
        print("Before Logger")
        command = await next_handler()
        print("After Logger")
        return command


@component
@ordered(10)
class TransactionPipeLine(PipeLine):    
    
    async def handler(self, context: PipelineContext, next_handler: Callable[[], Any]) -> Any:
        print("Before Transaction")
        command = await next_handler()
        print("After Transaction")
        return command

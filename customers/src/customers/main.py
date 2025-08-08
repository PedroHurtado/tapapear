import os
from common.server import get_feature_modules

from fastapi import FastAPI, Depends

app = FastAPI()
# app.include_router()

routers, modules = get_feature_modules()
print(routers)

import os
from common.server import get_feature_modules

from fastapi import FastAPI, Depends
from customers.features.customer.commands.create import(
    Service,
    Repository
)
app = FastAPI()
# app.include_router()
print(Service.__name__)
print(Service.__module__)

routers, modules = get_feature_modules()
print(routers)

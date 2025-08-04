from common.infraestructure import(
    InjectsRepo,
    IRepo,
    Document
)
class Foo(Document):...
# Repo concreto
class BarRepo(InjectsRepo, IRepo[Foo]):
    pass

bar_repo = BarRepo()
bar_repo.create_async()
bar_repo.create()




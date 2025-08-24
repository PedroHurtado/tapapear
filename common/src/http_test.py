import asyncio
import json
from common.http import HttpClient, File as FileRequest
from common.ioc import component, ProviderType, container, inject, deps

from pydantic import BaseModel
from typing import List


http = HttpClient("http://localhost:8081")


class Multipart(BaseModel):
    name: str
    file: FileRequest


class User(BaseModel):
    user: str
    password: str


class Post(BaseModel):
    id: int
    title: str


class FileInfo(BaseModel):
    filename: str
    size: int


@component(provider_type=ProviderType.OBJECT)
class PostHttp:

    @http.get("/posts/{id}")
    async def get(id: int) -> Post: ...

    @http.get("/posts")
    async def get_all() -> List[Post]: ...

    @http.post("/customers/multi")
    async def create(form_data: Multipart) -> FileInfo: ...

    @http.post("/customers/form")
    async def form(form: User): ...


@inject
async def main(http: PostHttp = deps(PostHttp)):

    data = {"id": 1, "name": "Pedro"}

    # 🔑 Convertir dict -> JSON -> bytes
    json_bytes = json.dumps(data).encode("utf-8")

    # Crear el objeto File
    file = FileRequest(
        content=json_bytes, filename="data.json", content_type="application/json"
    )

    # Pasarlo al Multipart
    multipart = Multipart(name="Pedro", file=file)

    # Enviar al endpoint
    file_info = await http.create(multipart)

    await http.form(User(user="pedro", password="1234"))
    print(file_info)


if __name__ == "__main__":
    container.wire([__name__])
    asyncio.run(main())


import asyncio
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime
from common.http import HttpClient, File


# ========================
# CONFIGURACIÓN DEL CLIENTE
# ========================

http = HttpClient("http://localhost:8080")


# ========================
# MODELOS DE DATOS
# ========================


class Author(BaseModel):
    id: int
    name: str
    email: str


class PostQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=10, ge=1, le=100)
    category: Optional[str] = None
    published: Optional[bool] = None
    search: Optional[str] = None


class PostFilter(BaseModel):
    tags: Optional[List[str]] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None


class CreatePostRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    category: str
    tags: List[str] = Field(default_factory=list)
    published: bool = False


class UpdatePostRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    content: Optional[str] = Field(None, min_length=1)
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    published: Optional[bool] = None


class PostResponse(BaseModel):
    id: int
    title: str
    content: str
    category: str
    tags: List[str]
    published: bool
    created_at: datetime
    updated_at: datetime
    author: Author


class PostStats(BaseModel):
    views: int
    likes: int
    comments: int


class UploadImageRequest(BaseModel):
    image: File
    alt_text: Optional[str] = None


class BulkUploadRequest(BaseModel):
    images: List[File]
    post_id: int


class PostFormData(BaseModel):
    title: str
    content: str
    category: str
    image: Optional[File] = None
    tags: str


class CommentQuery(BaseModel):
    post_id: int
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=100)


class CommentRequest(BaseModel):
    content: str = Field(min_length=1)
    author_name: str
    author_email: str


class CommentResponse(BaseModel):
    id: int
    content: str
    author_name: str
    author_email: str
    created_at: datetime
    post_id: int


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_in: int


class UserProfile(BaseModel):
    id: int
    username: str
    email: str
    full_name: str


# ========================
# API DE POSTS
# ========================


class PostsAPI:
    """API para gestión de posts - estilo OpenFeign limpio"""

    @http.get("/posts")
    async def get_posts(query: PostQuery) -> List[PostResponse]: ...

    @http.get("/posts/{post_id}")
    async def get_post(post_id: int) -> PostResponse: ...

    @http.get("/posts/search")
    async def search_posts(
        query: PostQuery, body: PostFilter
    ) -> List[PostResponse]: ...

    @http.get("/posts/public", allow_anonymous=True)
    async def get_public_posts(query: PostQuery) -> List[PostResponse]: ...

    @http.post("/posts")
    async def create_post(body: CreatePostRequest) -> PostResponse: ...

    @http.put("/posts/{post_id}")
    async def update_post(post_id: int, body: UpdatePostRequest) -> PostResponse: ...

    @http.patch("/posts/{post_id}")
    async def partial_update(post_id: int, body: UpdatePostRequest) -> PostResponse: ...

    @http.delete("/posts/{post_id}")
    async def delete_post(post_id: int) -> dict: ...

    @http.post("/posts/batch")
    async def batch_create(
        query: PostQuery, body: List[CreatePostRequest]
    ) -> List[PostResponse]: ...

    @http.delete("/posts/batch")
    async def batch_delete(body: List[int]) -> dict: ...

    @http.get("/posts/{post_id}/stats")
    async def get_stats(post_id: int, query: PostQuery) -> PostStats: ...

    @http.get("/posts/{post_id}/download")
    async def download_pdf(post_id: int) -> File: ...

    @http.get("/posts/export", allow_anonymous=True)
    async def export_posts(query: PostQuery) -> File: ...

    # Form simple (application/x-www-form-urlencoded)
    @http.post(
        "/posts/form", headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    async def create_with_form(form: CreatePostRequest) -> PostResponse: ...

    @http.put("/posts/{post_id}/form")
    async def update_with_form(
        post_id: int, query: PostQuery, form: UpdatePostRequest
    ) -> PostResponse: ...

    # Multipart form-data
    @http.post("/posts/with-image")
    async def create_with_image(form_data: PostFormData) -> PostResponse: ...

    @http.post("/posts/{post_id}/upload")
    async def upload_image(post_id: int, form_data: UploadImageRequest) -> dict: ...

    @http.post("/posts/bulk-upload")
    async def bulk_upload(form_data: BulkUploadRequest) -> dict: ...

    @http.patch("/posts/{post_id}/update-with-file")
    async def update_with_file(
        post_id: int, query: PostQuery, form_data: PostFormData
    ) -> PostResponse: ...

    # Body con archivo directo
    @http.post("/posts/{post_id}/single-file")
    async def upload_single_file(post_id: int, body: File) -> dict: ...


# ========================
# API DE COMENTARIOS
# ========================


class CommentsAPI:
    """API para gestión de comentarios"""

    @http.get("/comments")
    async def get_comments(query: CommentQuery) -> List[CommentResponse]: ...

    @http.get("/comments/{comment_id}")
    async def get_comment(comment_id: int) -> CommentResponse: ...

    @http.post("/comments")
    async def create_comment(body: CommentRequest) -> CommentResponse: ...

    @http.put("/comments/{comment_id}")
    async def update_comment(
        comment_id: int, body: CommentRequest
    ) -> CommentResponse: ...

    @http.delete("/comments/{comment_id}")
    async def delete_comment(comment_id: int) -> dict: ...

    @http.post("/comments/with-attachment")
    async def create_with_attachment(
        query: CommentQuery, form_data: CommentRequest
    ) -> CommentResponse: ...


# ========================
# API DE AUTENTICACIÓN
# ========================


class AuthAPI:
    """API para autenticación - endpoints públicos"""

    @http.post("/auth/login", allow_anonymous=True)
    async def login(body: LoginRequest) -> LoginResponse: ...

    @http.post("/auth/logout")
    async def logout() -> dict: ...

    @http.get("/auth/profile")
    async def get_profile() -> UserProfile: ...

    @http.put("/auth/profile")
    async def update_profile(body: UserProfile) -> UserProfile: ...

    @http.post("/auth/refresh", allow_anonymous=True)
    async def refresh_token(body: dict) -> LoginResponse: ...


# ========================
# API DE ARCHIVOS
# ========================


class FilesAPI:
    """API dedicada para manejo de archivos"""

    @http.post("/files/upload")
    async def upload_file(form_data: UploadImageRequest) -> dict: ...

    @http.post("/files/multi-upload")
    async def multi_upload(form_data: BulkUploadRequest) -> dict: ...

    @http.get("/files/{file_id}")
    async def download_file(file_id: str) -> File: ...

    @http.get("/files/{file_id}/info")
    async def get_file_info(file_id: str) -> dict: ...

    @http.delete("/files/{file_id}")
    async def delete_file(file_id: str) -> dict: ...

    @http.post("/files/process")
    async def process_file(query: PostQuery, body: File) -> dict: ...


# ========================
# EJEMPLOS DE USO
# ========================


async def ejemplos_posts():
    """Ejemplos usando PostsAPI"""
    print("=== EJEMPLOS POSTS API ===\n")

    # 1. Query simple
    query = PostQuery(page=1, limit=5, category="tecnologia")
    posts = await PostsAPI().get_posts(query)
    print(f"✓ Obtenidos {len(posts)} posts")

    # 2. Crear post
    new_post = CreatePostRequest(
        title="Nuevo post",
        content="Contenido del post",
        category="tecnologia",
        tags=["python", "api"],
    )
    created = await PostsAPI().create_post(new_post)
    print(f"✓ Post creado: {created.id}")

    # 3. Búsqueda avanzada (query + body)
    search_query = PostQuery(search="python")
    filters = PostFilter(tags=["python"])
    results = await PostsAPI().search_posts(search_query, filters)
    print(f"✓ Búsqueda: {len(results)} resultados")

    # 4. Form simple
    form_post = await PostsAPI().create_with_form(new_post)
    print(f"✓ Post por form: {form_post.title}")

    # 5. Con archivo
    image_data = PostFormData(
        title="Post con imagen",
        content="Contenido",
        category="multimedia",
        image=File(content=b"image_data", filename="test.jpg"),
        tags="imagen",
    )
    with_image = await PostsAPI().create_with_image(image_data)
    print(f"✓ Post con imagen: {with_image.title}")

    # 6. Descargar
    pdf = await PostsAPI().download_pdf(created.id)
    print(f"✓ PDF descargado: {pdf.filename}")


async def ejemplos_comentarios():
    """Ejemplos usando CommentsAPI"""
    print("\n=== EJEMPLOS COMMENTS API ===\n")

    # 1. Obtener comentarios
    query = CommentQuery(post_id=1, page=1, limit=10)
    comments = await CommentsAPI().get_comments(query)
    print(f"✓ Comentarios: {len(comments)}")

    # 2. Crear comentario
    comment = CommentRequest(
        content="Excelente post!",
        author_name="Usuario",
        author_email="user@example.com",
    )
    new_comment = await CommentsAPI().create_comment(comment)
    print(f"✓ Comentario creado: {new_comment.id}")


async def ejemplos_auth():
    """Ejemplos usando AuthAPI"""
    print("\n=== EJEMPLOS AUTH API ===\n")

    # 1. Login (público)
    login_data = LoginRequest(username="admin", password="secret")
    auth_result = await AuthAPI().login(login_data)
    print(f"✓ Login exitoso, token: {auth_result.token[:10]}...")

    # 2. Perfil (autenticado)
    profile = await AuthAPI().get_profile()
    print(f"✓ Perfil: {profile.username}")

    # 3. Logout
    await AuthAPI().logout()
    print("✓ Logout exitoso")


async def ejemplos_archivos():
    """Ejemplos usando FilesAPI"""
    print("\n=== EJEMPLOS FILES API ===\n")

    # 1. Upload simple
    upload_data = UploadImageRequest(
        image=File(content=b"file_content", filename="document.pdf"),
        alt_text="Documento importante",
    )
    upload_result = await FilesAPI().upload_file(upload_data)
    print("✓ Archivo subido")

    # 2. Upload múltiple
    bulk_data = BulkUploadRequest(
        images=[
            File(content=b"img1", filename="img1.jpg"),
            File(content=b"img2", filename="img2.png"),
        ],
        post_id=1,
    )
    await FilesAPI().multi_upload(bulk_data)
    print("✓ Archivos múltiples subidos")

    # 3. Descargar
    file = await FilesAPI().download_file("file-123")
    print(f"✓ Archivo descargado: {file.filename}")


async def demo_completa():
    """Demo completa de todas las APIs"""
    print("🚀 DEMO API ESTILO OPENFEIGN - VERSIÓN MEJORADA")
    print("=" * 60)

    try:
        await ejemplos_posts()
        await ejemplos_comentarios()
        await ejemplos_auth()
        await ejemplos_archivos()

        print("\n" + "=" * 60)
        print("✅ DEMO COMPLETADA - TODAS LAS APIS FUNCIONANDO")
        print("\n🎯 VENTAJAS DE ESTA VERSIÓN:")
        print("  • Sin @staticmethod innecesarios")
        print("  • Código más limpio y legible")
        print("  • Separación clara por dominios")
        print("  • Fácil de usar y mantener")
        print("  • Estilo OpenFeign auténtico")

    except Exception as e:
        print(f"❌ Error: {e}")


def mostrar_comparacion():
    """Muestra la comparación entre versiones"""
    print("\n📊 COMPARACIÓN DE ENFOQUES:")
    print("\n❌ VERSIÓN ANTERIOR (verbosa):")
    print("    @_client.get('/posts')")
    print("    @staticmethod")
    print("    async def get_posts(query: PostQuery) -> List[PostResponse]:")
    print("        pass")

    print("\n✅ VERSIÓN ACTUAL (limpia):")
    print("    @http.get('/posts')")
    print("    async def get_posts(query: PostQuery) -> List[PostResponse]: ...")

    print("\n🎯 BENEFICIOS:")
    print("  • 50% menos líneas de código")
    print("  • Más parecido a OpenFeign real")
    print("  • Sin decoradores innecesarios")
    print("  • Sintaxis más pythónica")


if __name__ == "__main__":
    print("🎯 API ESTILO OPENFEIGN - VERSIÓN MEJORADA")
    print("📚 Múltiples APIs: Posts, Comments, Auth, Files")
    print("🧹 Sin @staticmethod - Código más limpio")

    mostrar_comparacion()

    print("\n💡 Para ejecutar la demo:")
    print("   asyncio.run(demo_completa())")

    # Descomenta para ejecutar:
    # asyncio.run(demo_completa())

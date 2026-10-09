from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from src.domain.errors import (
    CatalogError,
    CategoryInUseError,
    CategoryNotFoundError,
    DuplicateCategoryError,
    DuplicateSkuError,
    InvalidFilterError,
    ProductNotFoundError,
    VersionConflictError,
)

_STATUS: dict[type[CatalogError], tuple[int, str]] = {
    ProductNotFoundError: (status.HTTP_404_NOT_FOUND, "product not found"),
    DuplicateSkuError: (status.HTTP_409_CONFLICT, "sku already exists"),
    VersionConflictError: (
        status.HTTP_412_PRECONDITION_FAILED,
        "product was modified, reload it and retry",
    ),
    CategoryNotFoundError: (status.HTTP_422_UNPROCESSABLE_CONTENT, "category not found"),
    DuplicateCategoryError: (status.HTTP_409_CONFLICT, "category already exists"),
    CategoryInUseError: (status.HTTP_409_CONFLICT, "category has products"),
    InvalidFilterError: (status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid filter"),
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(CatalogError)
    async def catalog_error(request: Request, exc: CatalogError) -> JSONResponse:
        code, detail = _STATUS.get(type(exc), (status.HTTP_400_BAD_REQUEST, "bad request"))
        if isinstance(exc, CategoryNotFoundError) and request.url.path.startswith(
            "/api/v1/categories"
        ):
            code = status.HTTP_404_NOT_FOUND  # сама категория не найдена
        if isinstance(exc, InvalidFilterError) and str(exc):
            detail = str(exc)
        return JSONResponse({"detail": detail}, code)

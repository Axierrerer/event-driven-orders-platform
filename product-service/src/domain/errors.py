class CatalogError(Exception):
    pass


class ProductNotFoundError(CatalogError):
    pass


class DuplicateSkuError(CatalogError):
    pass


class VersionConflictError(CatalogError):
    """Документ изменился с момента чтения (не совпал If-Match)."""


class CategoryNotFoundError(CatalogError):
    pass


class DuplicateCategoryError(CatalogError):
    pass


class CategoryInUseError(CatalogError):
    pass


class InvalidFilterError(CatalogError):
    pass

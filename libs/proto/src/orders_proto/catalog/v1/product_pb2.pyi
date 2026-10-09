from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class GetProductRequest(_message.Message):
    __slots__ = ("product_id",)
    PRODUCT_ID_FIELD_NUMBER: _ClassVar[int]
    product_id: str
    def __init__(self, product_id: _Optional[str] = ...) -> None: ...

class GetProductsRequest(_message.Message):
    __slots__ = ("product_ids",)
    PRODUCT_IDS_FIELD_NUMBER: _ClassVar[int]
    product_ids: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, product_ids: _Optional[_Iterable[str]] = ...) -> None: ...

class GetProductsResponse(_message.Message):
    __slots__ = ("products",)
    PRODUCTS_FIELD_NUMBER: _ClassVar[int]
    products: _containers.RepeatedCompositeFieldContainer[Product]
    def __init__(self, products: _Optional[_Iterable[_Union[Product, _Mapping]]] = ...) -> None: ...

class Product(_message.Message):
    __slots__ = ("id", "sku", "name", "description", "category_id", "price", "currency", "is_published", "version", "images", "attributes_json", "created_at", "updated_at")
    ID_FIELD_NUMBER: _ClassVar[int]
    SKU_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    CATEGORY_ID_FIELD_NUMBER: _ClassVar[int]
    PRICE_FIELD_NUMBER: _ClassVar[int]
    CURRENCY_FIELD_NUMBER: _ClassVar[int]
    IS_PUBLISHED_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    IMAGES_FIELD_NUMBER: _ClassVar[int]
    ATTRIBUTES_JSON_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    UPDATED_AT_FIELD_NUMBER: _ClassVar[int]
    id: str
    sku: str
    name: str
    description: str
    category_id: str
    price: str
    currency: str
    is_published: bool
    version: int
    images: _containers.RepeatedScalarFieldContainer[str]
    attributes_json: str
    created_at: str
    updated_at: str
    def __init__(self, id: _Optional[str] = ..., sku: _Optional[str] = ..., name: _Optional[str] = ..., description: _Optional[str] = ..., category_id: _Optional[str] = ..., price: _Optional[str] = ..., currency: _Optional[str] = ..., is_published: _Optional[bool] = ..., version: _Optional[int] = ..., images: _Optional[_Iterable[str]] = ..., attributes_json: _Optional[str] = ..., created_at: _Optional[str] = ..., updated_at: _Optional[str] = ...) -> None: ...

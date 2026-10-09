from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Item(_message.Message):
    __slots__ = ("product_id", "quantity")
    PRODUCT_ID_FIELD_NUMBER: _ClassVar[int]
    QUANTITY_FIELD_NUMBER: _ClassVar[int]
    product_id: str
    quantity: int
    def __init__(self, product_id: _Optional[str] = ..., quantity: _Optional[int] = ...) -> None: ...

class CheckAvailabilityRequest(_message.Message):
    __slots__ = ("items",)
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    items: _containers.RepeatedCompositeFieldContainer[Item]
    def __init__(self, items: _Optional[_Iterable[_Union[Item, _Mapping]]] = ...) -> None: ...

class ItemAvailability(_message.Message):
    __slots__ = ("product_id", "requested", "available")
    PRODUCT_ID_FIELD_NUMBER: _ClassVar[int]
    REQUESTED_FIELD_NUMBER: _ClassVar[int]
    AVAILABLE_FIELD_NUMBER: _ClassVar[int]
    product_id: str
    requested: int
    available: int
    def __init__(self, product_id: _Optional[str] = ..., requested: _Optional[int] = ..., available: _Optional[int] = ...) -> None: ...

class CheckAvailabilityResponse(_message.Message):
    __slots__ = ("available", "items")
    AVAILABLE_FIELD_NUMBER: _ClassVar[int]
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    available: bool
    items: _containers.RepeatedCompositeFieldContainer[ItemAvailability]
    def __init__(self, available: _Optional[bool] = ..., items: _Optional[_Iterable[_Union[ItemAvailability, _Mapping]]] = ...) -> None: ...

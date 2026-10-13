from typing import Any, ClassVar, Self
from abc import ABCMeta

class _GenericMeta(ABCMeta):
    def __getitem__(cls, args: Any) -> type:
        type_args = args if isinstance(args, tuple) else (args,)
        params = getattr(cls, "__type_params__", ())

        if params and len(type_args) != len(params):
            raise TypeError(
                f"{cls.__name__} expects {len(params)} type argument(s)"
            )

        def type_name(t: Any) -> str:
            return getattr(t, "__name__", repr(t))

        name = f"{cls.__name__}[{', '.join(map(type_name, type_args))}]"

        return _GenericMeta(
            name,
            (cls,),
            {
                "__module__": cls.__module__,
                "__type_args__": type_args,
                "__wire_type__": (
                    type_args[0] if len(type_args) == 1 else type_args
                ),
            },
        )
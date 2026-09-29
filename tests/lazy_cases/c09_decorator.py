def rebuild(cls):
    return type(cls.__name__ + "V2", (cls,), {})


def to_function(cls):
    return lambda: None


@rebuild
class Decorated:
    pass


@to_function
class NoLongerClass:
    pass

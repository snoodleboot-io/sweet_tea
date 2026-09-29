def make_class(name):
    return type(name, (), {"made_by": "helpers"})

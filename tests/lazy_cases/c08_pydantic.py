from pydantic import BaseModel, create_model

DynModel = create_model("DynModel", x=(int, 1))


class Declared(BaseModel):
    x: int = 1

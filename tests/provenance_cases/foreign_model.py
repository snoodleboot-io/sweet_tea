from pydantic import create_model

Thing = create_model("Thing", __module__="totally.other.place")

# Sweet Tea
Universal or Global Python Class Factory

The replaces an older library - that has long since gone to dust. This library will be kept with support for the current
production versions of python. 

At its core, this library is rather simple. It is a registry of all classes either manually added or automatically discovered 
from a given python module. All the classes can then be dynamically generated - a factory without having to build a factory!

## About
Sweet Tea is a global python factory. It is designed to simplify software engineering and increase the maintainability of software. Perhaps one of the most commonly encountered patterns in software engineering is the Factory Pattern and its various relatives. The issue that comes with these patterns is the need to continually update and ammend the factories. 

And, depending how those factories were designed, this will mean one of the following:
1. Leads to chaos through a sequence if/elif statements - possibly with nesting
2. A large dictionary of 'constructors' that has to be manually updated. Sometimes with a register/retrieve pattern - this is a no go at scale.
3. Classes that self register their definitions with the factory - but these have to be in scope before they can register - so yikes.
4. Multiple different factories, abstractions, and a pain to now when and where to modify things.

## Installation

**raw pip**
```bash
pip install sweet_tea
```

**poetry**
```bash
poetry add sweet_tea
```

**uv**
```bash
uv add sweet_tea
```

## Using Sweet Tea in Your Project
To use Sweet Tea you will need to fill the registry from root of your project
```python
from sweet_tea.registry import Registry
Registry.fill_registry()
```

The registry will crawl through all of the python modules from the root level down its tree and register all classes defined in the project. It will register each class with the following information
* class name - cast to lowercase
* library - name of the library the class belongs to
* label (optional) that describes the class 
* module - module the class belongs to
* path - path in the library where the class is located

Once this has been done, the registry can now be used to retrieve an instance of the class from the registry.

Now to create the instance of a class, we only have to do the following:
```python
from sweet_tea.factory import Factory
configuration = {
    #... key-word configuration of the class
}
instance = Factory.generate(key='lowercase_name_of_class', configuration=configuration)
```


## Usage Patterns
The most basic usage is to just use it as above. If, however, you want to be able to use the factory so that it only reflects classes of a specific subtype, then you can use the AbstractFactory as such
```python
from sweet_tea.abstract_factory import AbstractFactory

class SomeFactory(AbstractFactory[Type])

```


## Creating Specialized Factories


## Handling Optional Installs in Your Package
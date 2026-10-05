from sweet_tea.registry import Registry


class Thing:
    pass


# Registered while this module is being imported, which is exactly when the
# resolution that triggered the import is mid-flight.
Registry.register_lazy(
    key="late_alias",
    module="tests.late_registration_cases.selfreg",
    attribute="Thing",
)

import inspect
from bubus import EventBus

# Get dispatch source
print(inspect.getsource(EventBus.dispatch))
